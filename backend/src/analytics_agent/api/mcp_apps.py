"""MCP App endpoints.

Phase 1: GET /api/conversations/{conversation_id}/mcp-app/{message_id}/ui

Resolves the persisted {connection_key, resource_uri} from the MCP_APP message
row, fetches HTML via MCPResourceClient (cache-first, live-server fallback), and
returns {html, csp, permissions}.

Returns HTTP 404 when both the cache and the live MCP server are unavailable.

Phase 2: POST /api/conversations/{conversation_id}/mcp-app/{app_id}/tool-call

Scoped MCP tool proxy. The iframe sends {tool_name, arguments}; this endpoint:
  1. Loads the PendingApp from the in-memory side-channel (fast path, live
     during streaming) or rehydrates from the persisted MCP_APP message row.
  2. Validates that (connection_key, tool_name) is in the per-app allow-list
     so the iframe can never reach engine tools, other MCP servers, or
     create_chart.
  3. Dispatches tools/call on the originating MCP client session.
  4. Returns the CallToolResult as JSON.
"""

from __future__ import annotations

import logging
from typing import Any

import orjson
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from analytics_agent.db.base import get_session
from analytics_agent.db.repository import ConversationRepo, MessageRepo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["mcp-apps"])


# ── Phase 2 helpers ───────────────────────────────────────────────────────────


class _AppContext:
    """Minimal info needed to authorise and dispatch a scoped tool call."""

    def __init__(self, connection_key: str, server_name: str, allowed_tools: list[str]) -> None:
        self.connection_key = connection_key
        self.server_name = server_name
        self.allowed_tools = allowed_tools


async def _load_app_context(
    conversation_id: str,
    app_id: str,
    session: AsyncSession,
) -> _AppContext:
    """Return app context from the in-memory side-channel or the DB row.

    Prefers the in-memory PendingApp (available while streaming is active or
    before it was popped by on_tool_end). Falls back to scanning the
    conversation's MCP_APP message rows when the in-memory entry is gone
    (replay / post-stream calls).

    Raises HTTPException 404 if neither source has a record for this app_id.
    """
    from analytics_agent.agent.mcp_app_tool import _pending_apps

    pending = _pending_apps.get(app_id)
    if pending is not None:
        return _AppContext(
            connection_key=pending.connection_key,
            server_name=pending.server_name,
            allowed_tools=pending.allowed_tools,
        )

    # Rehydrate from persisted message rows.
    msg_repo = MessageRepo(session)
    messages = await msg_repo.list_for_conversation(conversation_id)
    for msg in messages:
        if msg.event_type != "MCP_APP" or not msg.payload:
            continue
        try:
            payload: dict = orjson.loads(msg.payload)
        except Exception:
            continue
        if payload.get("app_id") == app_id:
            connection_key = payload.get("connection_key", "")
            server_name = payload.get("server_name", "")
            allowed_tools: list[str] = payload.get("allowed_tools") or []
            if not connection_key:
                break
            return _AppContext(
                connection_key=connection_key,
                server_name=server_name,
                allowed_tools=allowed_tools,
            )

    raise HTTPException(status_code=404, detail=f"MCP App not found: app_id={app_id!r}")


async def _dispatch_tool_call(
    connection_key: str,
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict:
    """Call tool_name on the originating MCP client; return the CallToolResult dict."""
    from analytics_agent.context.mcp_resources import _mcp_clients

    if connection_key not in _mcp_clients:
        raise HTTPException(
            status_code=503,
            detail=f"MCP client for connection {connection_key!r} is not available — "
            "the server may have restarted. Reload the page to reconnect.",
        )

    client, _sname = _mcp_clients[connection_key]
    if server_name and _sname != server_name:
        # server_name mismatch — use the one from the registry to be safe
        logger.warning(
            "server_name mismatch for connection_key=%s: stored=%s registry=%s",
            connection_key,
            server_name,
            _sname,
        )
        server_name = _sname

    try:
        async with client.session(server_name) as mcp_session:
            result = await mcp_session.call_tool(tool_name, arguments)
    except Exception as exc:
        logger.error(
            "MCP tool call failed: connection=%s server=%s tool=%s: %s",
            connection_key,
            server_name,
            tool_name,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail=f"MCP tool call failed: {exc}",
        ) from exc

    # Serialise the result into a plain dict (content blocks list).
    content: list[dict] = []
    for block in result.content or []:
        if hasattr(block, "model_dump"):
            content.append(block.model_dump())
        elif isinstance(block, dict):
            content.append(block)
        else:
            content.append({"type": "text", "text": str(block)})

    return {
        "content": content,
        "isError": getattr(result, "isError", False) or False,
    }


class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = {}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/{conversation_id}/mcp-app/{message_id}/ui")
async def get_mcp_app_ui(
    conversation_id: str,
    message_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Return the HTML, CSP, and permissions for a persisted MCP App message.

    Cache-first: serves from disk cache within TTL.  Falls back to a live
    resources/read call when the cache is stale or missing.  Returns 404 with
    a structured placeholder when both the cache and the live server are
    unavailable.
    """
    conv_repo = ConversationRepo(session)
    conv = await conv_repo.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_repo = MessageRepo(session)
    message = await msg_repo.get_by_id(message_id)

    if message is None or message.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Message not found")

    if message.event_type != "MCP_APP":
        raise HTTPException(status_code=404, detail="Message is not an MCP App event")

    try:
        payload: dict = orjson.loads(message.payload)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupt message payload")

    connection_key: str | None = payload.get("connection_key")
    resource_uri: str | None = payload.get("resource_uri")

    if not connection_key or not resource_uri:
        raise HTTPException(
            status_code=404,
            detail="Message payload missing connection_key or resource_uri",
        )

    from analytics_agent.context.mcp_resources import resource_client

    try:
        result = await resource_client.read_ui_resource(connection_key, resource_uri)
    except RuntimeError as exc:
        logger.warning(
            "MCP app UI unavailable for message_id=%s connection_key=%s uri=%s: %s",
            message_id,
            connection_key,
            resource_uri,
            exc,
        )
        raise HTTPException(
            status_code=404,
            detail={
                "message": "MCP app HTML unavailable — server offline and no cache",
                "connection_key": connection_key,
                "resource_uri": resource_uri,
            },
        )

    return {
        "html": result["html"],
        "csp": result.get("csp"),
        "permissions": result.get("permissions", []),
        "is_stale": result.get("is_stale", False),
    }


@router.post("/{conversation_id}/mcp-app/{app_id}/tool-call")
async def mcp_app_tool_call(
    conversation_id: str,
    app_id: str,
    body: ToolCallRequest,
    session: AsyncSession = Depends(get_session),
):
    """Phase 2: scoped MCP tool proxy for iframe apps.

    Validates the requested (connection_key, tool_name) pair against the
    per-app allow-list, then dispatches tools/call on the originating MCP
    client session. Never routes to engine tools, other connections, or
    create_chart.
    """
    conv_repo = ConversationRepo(session)
    conv = await conv_repo.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    app_ctx = await _load_app_context(conversation_id, app_id, session)

    # Security: ensure the requested tool is in the per-app allow-list.
    if app_ctx.allowed_tools and body.tool_name not in app_ctx.allowed_tools:
        logger.warning(
            "Blocked tool call from iframe: app_id=%s tool=%s allowed=%s",
            app_id,
            body.tool_name,
            app_ctx.allowed_tools,
        )
        raise HTTPException(
            status_code=403,
            detail=f"Tool {body.tool_name!r} is not in the allow-list for this app.",
        )

    result = await _dispatch_tool_call(
        connection_key=app_ctx.connection_key,
        server_name=app_ctx.server_name,
        tool_name=body.tool_name,
        arguments=body.arguments,
    )
    return result
