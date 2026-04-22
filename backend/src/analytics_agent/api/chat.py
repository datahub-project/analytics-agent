from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import orjson
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from analytics_agent.agent.analysis import CONTEXT_TOOLS
from analytics_agent.db.base import get_session
from analytics_agent.db.models import Message
from analytics_agent.db.repository import ConversationRepo, MessageRepo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["chat"])

# ── Real-time background quality computation ─────────────────────────────────
# Process-local throttle state. Safe for single-worker uvicorn.
_QUALITY_MIN_INTERVAL = 30.0  # seconds minimum between background computes
_quality_throttle: dict[str, float] = {}  # conv_id → monotonic time of last compute
_quality_last_count: dict[str, int] = {}  # conv_id → context call count at last compute
_context_call_counts: dict[str, int] = {}  # conv_id → running count of context TOOL_RESULTs


def _maybe_schedule_quality(conv_id: str, factory) -> None:
    """Fire a background quality task if throttle allows and new context results exist."""
    now = time.monotonic()
    current = _context_call_counts.get(conv_id, 0)
    if current <= _quality_last_count.get(conv_id, 0):
        return  # nothing new since last compute
    if now - _quality_throttle.get(conv_id, 0) < _QUALITY_MIN_INTERVAL:
        return  # too soon
    _quality_throttle[conv_id] = now
    _quality_last_count[conv_id] = current
    asyncio.create_task(_compute_quality_background(conv_id, factory))


async def _compute_quality_background(conv_id: str, factory) -> None:
    """Async background task: load messages, run LLM quality assessment, store result."""
    try:
        from analytics_agent.agent.analysis import compute_context_quality

        async with factory() as session:
            messages = await MessageRepo(session).list_for_conversation(conv_id)
            quality = await compute_context_quality(messages)
            await ConversationRepo(session).update_quality(
                conv_id,
                quality.score,
                quality.label,
                quality.breakdown.get("reason", ""),
            )
    except Exception as exc:
        logger.debug("Background quality update failed for %s: %s", conv_id, exc)


class ChatMessageRequest(BaseModel):
    text: str


async def _persist_message(
    session: AsyncSession,
    conversation_id: str,
    event_type: str,
    role: str,
    payload: dict,
    sequence: int,
) -> None:
    msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        event_type=event_type,
        role=role,
        payload=orjson.dumps(payload).decode(),
        sequence=sequence,
        created_at=datetime.now(UTC),
    )
    repo = MessageRepo(session)
    await repo.create(msg)
    conv_repo = ConversationRepo(session)
    await conv_repo.touch(conversation_id)


async def _event_stream(
    conversation_id: str,
    user_text: str,
    engine_name: str,
    keepalive_interval: int,
) -> AsyncIterator[str]:
    """
    SSE generator. Opens its own DB session so it stays alive for the full
    stream (FastAPI closes Depends sessions before StreamingResponse iterates).
    Yields SSE-formatted strings.
    """
    from analytics_agent.agent.graph import build_graph
    from analytics_agent.agent.streaming import stream_graph_events, to_sse
    from analytics_agent.db.base import _get_session_factory

    factory = _get_session_factory()
    async with factory() as session:
        msg_repo = MessageRepo(session)
        sequence = await msg_repo.next_sequence(conversation_id)

        await _persist_message(
            session, conversation_id, "TEXT", "user", {"text": user_text}, sequence
        )
        sequence += 1

        # Load prior messages to give the agent conversation history
        from analytics_agent.agent.compactor_registry import get_compactor
        from analytics_agent.agent.history import build_history
        from analytics_agent.config import settings as _settings

        prior_messages = await msg_repo.list_for_conversation(conversation_id)
        # Exclude the user message we just persisted (last item) — build_history adds current text itself
        history = build_history(
            prior_messages[:-1],
            user_text,
            compactor=get_compactor(),
            max_history_tokens=_settings.max_history_tokens,
        )

        from analytics_agent.context.registry import build_platform
        from analytics_agent.db.repository import ContextPlatformRepo, SettingsRepo
        from analytics_agent.engines.mcp.engine import MCPQueryEngine
        from analytics_agent.engines.resolver import resolve_engine

        settings_repo = SettingsRepo(session)
        custom_prompt = await settings_repo.get("system_prompt")
        disabled_raw = await settings_repo.get("disabled_tools")
        disabled_tools: set[str] = set()
        if disabled_raw:
            with contextlib.suppress(Exception):
                disabled_tools = set(orjson.loads(disabled_raw))

        mutations_raw = await settings_repo.get("enabled_mutation_tools")
        enabled_mutations: set[str] = set()
        if mutations_raw:
            with contextlib.suppress(Exception):
                enabled_mutations = set(orjson.loads(mutations_raw))

        disabled_conns_raw = await settings_repo.get("disabled_connections")
        disabled_connections: set[str] = set()
        if disabled_conns_raw:
            with contextlib.suppress(Exception):
                disabled_connections = set(orjson.loads(disabled_conns_raw))

        cp_repo = ContextPlatformRepo(session)
        all_cp_rows = await cp_repo.list_all()

        try:
            context_tools: list = []
            include_mutations = bool(enabled_mutations)

            # Each platform owns its disabled_tools and include_mutations state.
            # build_platform() reads from DB config; get_tools() filters internally.
            for row in all_cp_rows:
                platform = build_platform(
                    row,
                    disabled_connections=disabled_connections,
                    include_mutations=include_mutations,
                )
                if platform is None:
                    continue
                tools = await platform.get_tools()
                context_tools.extend(tools)

            logger.info(
                "Total context_tools=%d for conversation %s", len(context_tools), conversation_id
            )
            engine = await resolve_engine(engine_name, session)
            engine_tools = None
            if isinstance(engine, MCPQueryEngine):
                mcp_tools = await engine.get_tools_async()
                engine_tools = [t for t in mcp_tools if t.name not in disabled_tools]

            graph = build_graph(
                engine=engine if not isinstance(engine, MCPQueryEngine) else None,
                engine_name=engine_name,
                system_prompt_override=custom_prompt,
                disabled_tools=disabled_tools,
                enabled_mutations=enabled_mutations,
                context_tools=context_tools,
                engine_tools=engine_tools,
            )
        except Exception as exc:
            yield to_sse(
                {
                    "event": "ERROR",
                    "conversation_id": conversation_id,
                    "message_id": str(uuid.uuid4()),
                    "payload": {"error": str(exc)},
                }
            )
            yield to_sse(
                {
                    "event": "COMPLETE",
                    "conversation_id": conversation_id,
                    "message_id": str(uuid.uuid4()),
                    "payload": {"text": ""},
                }
            )
            return

        async for evt in stream_graph_events(
            graph=graph,
            user_text=user_text,
            conversation_id=conversation_id,
            engine_name=engine_name,
            keepalive_interval=keepalive_interval,
            history=history,
        ):
            # evt is a dict — persist then yield as SSE string
            if evt.get("event") not in (None, "KEEPALIVE"):
                try:
                    await _persist_message(
                        session,
                        conversation_id,
                        evt["event"],
                        "assistant",
                        evt.get("payload", {}),
                        sequence,
                    )
                    sequence += 1
                except Exception:
                    pass

                # Track context tool results and maybe trigger background quality compute
                if evt.get("event") == "TOOL_RESULT":
                    tool_name = evt.get("payload", {}).get("tool_name", "")
                    if tool_name in CONTEXT_TOOLS:
                        _context_call_counts[conversation_id] = (
                            _context_call_counts.get(conversation_id, 0) + 1
                        )
                        _maybe_schedule_quality(conversation_id, factory)

            yield to_sse(evt)

        # Clean up per-turn tracking (keep throttle to rate-limit next turn's first compute)
        _context_call_counts.pop(conversation_id, None)
        _quality_last_count.pop(conversation_id, None)

        # Final end-of-turn quality compute — always runs, bypasses throttle, ensures accuracy
        try:
            from analytics_agent.agent.analysis import compute_context_quality

            all_messages = await msg_repo.list_for_conversation(conversation_id)
            quality = await compute_context_quality(all_messages)
            await ConversationRepo(session).update_quality(
                conversation_id,
                quality.score,
                quality.label,
                quality.breakdown.get("reason", ""),
            )
        except Exception:
            pass


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: ChatMessageRequest,
    session: AsyncSession = Depends(get_session),
):
    from analytics_agent.config import settings

    conv_repo = ConversationRepo(session)
    conv = await conv_repo.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not body.text.strip():
        raise HTTPException(status_code=422, detail="Message text cannot be empty")

    return StreamingResponse(
        _event_stream(
            conversation_id=conversation_id,
            user_text=body.text.strip(),
            engine_name=conv.engine_name,
            keepalive_interval=settings.sse_keepalive_interval,
        ),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
