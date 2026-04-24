from __future__ import annotations

from fastapi import APIRouter

from analytics_agent.api import chat, conversations, mcp_apps, oauth, settings

api_router = APIRouter()
api_router.include_router(conversations.router)
api_router.include_router(chat.router)
api_router.include_router(mcp_apps.router)
api_router.include_router(settings.router)
api_router.include_router(oauth.router)


@api_router.get("/api/engines", tags=["engines"])
async def list_engines():
    from analytics_agent.engines.factory import list_engines as _list

    return _list()


@api_router.get("/api/greeting", tags=["user"])
async def get_greeting(name: str = "", time_of_day: str = "day"):
    """Generate a warm, personalized welcome greeting via LLM."""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from analytics_agent.agent.llm import get_delight_llm

        llm = get_delight_llm()
        first_name = name.split()[0] if name else ""
        prompt = (
            f"Generate a two-word elegant phrase to greet a data analyst named {first_name or 'there'} "
            f"on a {time_of_day}. "
            f"Format: exactly two evocative words followed by a comma and the name. "
            f"Examples: 'Golden insights, Alex' / 'Sharp signals, Maya' / 'Clear skies, Jordan'. "
            f"The words should be classy, data-adjacent, and poetic. "
            f"Reply with ONLY the phrase, nothing else."
        )
        response = await llm.ainvoke(
            [
                SystemMessage(
                    content="You craft elegant two-word greeting phrases. Reply with only the phrase — two words, a comma, then the name. No quotes, no explanation."
                ),
                HumanMessage(content=prompt),
            ]
        )
        raw = response.content
        if isinstance(raw, list):
            raw = next(
                (b.get("text", "") for b in raw if isinstance(b, dict) and b.get("type") == "text"),
                "",
            )
        greeting = raw.strip().strip('"').strip("'")
        return {"greeting": greeting}
    except Exception:
        return {"greeting": ""}


@api_router.get("/api/me", tags=["user"])
async def get_me():
    """Return the current DataHub user's display name and username.

    Uses the active context platforms from DB (same as the agent) rather than
    env vars, so it works with MCP-backed DataHub connections.
    """
    try:
        from analytics_agent.context.registry import build_platform
        from analytics_agent.db.base import _get_session_factory
        from analytics_agent.db.repository import ContextPlatformRepo, SettingsRepo

        factory = _get_session_factory()
        async with factory() as session:
            settings_repo = SettingsRepo(session)
            disabled_conns_raw = await settings_repo.get("disabled_connections")
            import contextlib

            import orjson

            disabled_connections: set[str] = set()
            with contextlib.suppress(Exception):
                if disabled_conns_raw:
                    disabled_connections = set(orjson.loads(disabled_conns_raw))

            repo = ContextPlatformRepo(session)
            platforms = await repo.list_all()

        # Try each active platform until we get a valid get_me response
        for row in platforms:
            if row.name in disabled_connections:
                continue
            platform = build_platform(row, disabled_connections=disabled_connections)
            if platform is None:
                continue
            try:
                tools = await platform.get_tools()
                get_me_tool = next((t for t in tools if t.name == "get_me"), None)
                if not get_me_tool:
                    continue
                result = await get_me_tool.ainvoke({})
                # Normalize result — MCP tools return list[{type,text}], native returns dict
                import json as _json

                if isinstance(result, list):
                    text = next(
                        (
                            b.get("text", "")
                            for b in result
                            if isinstance(b, dict) and b.get("type") == "text"
                        ),
                        "",
                    )
                    with contextlib.suppress(Exception):
                        result = _json.loads(text)
                if isinstance(result, str):
                    with contextlib.suppress(Exception):
                        result = _json.loads(result)
                user = (
                    result.get("data", {}).get("corpUser", {}) if isinstance(result, dict) else {}
                )
                username = user.get("username", "")
                info = user.get("info") or user.get("editableInfo") or {}
                display_name = (
                    info.get("displayName")
                    or info.get("fullName")
                    or user.get("properties", {}).get("displayName")
                    or username
                )
                if display_name or username:
                    return {"username": username, "display_name": display_name}
            except Exception:
                continue

        return {"username": "", "display_name": ""}
    except Exception:
        return {"username": "", "display_name": ""}
