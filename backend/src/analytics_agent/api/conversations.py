from __future__ import annotations

import uuid
from datetime import UTC, datetime

import orjson
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from analytics_agent.db.base import get_session
from analytics_agent.db.models import Conversation
from analytics_agent.db.repository import ConversationRepo, MessageRepo

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = "New Conversation"
    engine_name: str


class ConversationSummary(BaseModel):
    id: str
    title: str
    engine_name: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class MessageOut(BaseModel):
    id: str
    event_type: str
    role: str
    payload: dict
    sequence: int
    created_at: datetime


class ConversationDetail(BaseModel):
    id: str
    title: str
    engine_name: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]
    is_streaming: bool = False


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(session: AsyncSession = Depends(get_session)):
    repo = ConversationRepo(session)
    msg_repo = MessageRepo(session)
    conversations = await repo.list()
    result = []
    for conv in conversations:
        msgs = await msg_repo.list_for_conversation(conv.id)
        result.append(
            ConversationSummary(
                id=conv.id,
                title=conv.title,
                engine_name=conv.engine_name,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                message_count=len(msgs),
            )
        )
    return result


@router.post("", response_model=ConversationSummary, status_code=201)
async def create_conversation(
    body: ConversationCreate, session: AsyncSession = Depends(get_session)
):
    repo = ConversationRepo(session)
    now = datetime.now(UTC)
    conv = Conversation(
        id=str(uuid.uuid4()),
        title=body.title,
        engine_name=body.engine_name,
        created_at=now,
        updated_at=now,
    )
    conv = await repo.create(conv)
    return ConversationSummary(
        id=conv.id,
        title=conv.title,
        engine_name=conv.engine_name,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=0,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, session: AsyncSession = Depends(get_session)):
    repo = ConversationRepo(session)
    conv = await repo.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = [
        MessageOut(
            id=msg.id,
            event_type=msg.event_type,
            role=msg.role,
            payload=orjson.loads(msg.payload),
            sequence=msg.sequence,
            created_at=msg.created_at,
        )
        for msg in conv.messages
    ]
    from analytics_agent.api.chat import _active_streams

    is_streaming = conversation_id in _active_streams

    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        engine_name=conv.engine_name,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=messages,
        is_streaming=is_streaming,
    )


@router.post("/{conversation_id}/generate-title")
async def generate_title(conversation_id: str, session: AsyncSession = Depends(get_session)):
    """Generate or refresh the conversation title using a cheap LLM call."""
    repo = ConversationRepo(session)
    conv = await repo.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Collect text content: user questions + assistant COMPLETE responses
    msg_repo = MessageRepo(session)
    messages = await msg_repo.list_for_conversation(conversation_id)

    exchanges: list[str] = []
    for m in messages:
        payload = orjson.loads(m.payload)
        if m.role == "user" and m.event_type == "TEXT":
            exchanges.append(f"User: {payload.get('text', '')[:200]}")
        elif m.role == "assistant" and m.event_type == "COMPLETE":
            text = payload.get("text", "")[:200]
            if text:
                exchanges.append(f"Assistant: {text}")

    if not exchanges:
        return {"title": conv.title}

    # Build prompt
    current_title = conv.title if conv.title != "New Conversation" else ""
    conversation_snippet = "\n".join(exchanges[:6])  # first 3 exchanges

    if current_title:
        prompt = (
            f'Current title: "{current_title}"\n\n'
            f"Conversation so far:\n{conversation_snippet}\n\n"
            "Update the title only if the subject has changed or become clearer. "
            "Keep it under 6 words. Data/technical terms are fine. No punctuation at the end. "
            "Reply with ONLY the title, nothing else."
        )
    else:
        prompt = (
            f"Conversation:\n{conversation_snippet}\n\n"
            "Generate a concise title (under 6 words) that captures the subject. "
            "Data/technical terms are fine. No punctuation at the end. "
            "Reply with ONLY the title, nothing else."
        )

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from analytics_agent.agent.llm import get_delight_llm

        llm = get_delight_llm()
        response = await llm.ainvoke(
            [
                SystemMessage(
                    content="You generate short, precise conversation titles for a data analytics chat tool."
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
        title = raw.strip().strip('"').strip("'")[:60]
        if title and title != current_title:
            await repo.update_title(conversation_id, title)
            return {"title": title, "updated": True}
    except Exception:
        pass

    return {"title": conv.title, "updated": False}


@router.patch("/{conversation_id}/engine")
async def update_engine(
    conversation_id: str,
    body: dict,
    session: AsyncSession = Depends(get_session),
):
    repo = ConversationRepo(session)
    conv = await repo.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    engine_name = body.get("engine_name", "").strip()
    if not engine_name:
        raise HTTPException(status_code=422, detail="engine_name is required")
    conv.engine_name = engine_name
    await session.commit()
    return {"engine_name": engine_name}


@router.get("/{conversation_id}/quality")
async def get_context_quality(conversation_id: str, session: AsyncSession = Depends(get_session)):
    """Return the stored context quality score for a conversation (pure DB read)."""
    repo = ConversationRepo(session)
    conv = await repo.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conv.quality_score is None:
        return {"score": 3, "label": "Neutral", "breakdown": {"reason": "No assessment yet"}}

    return {
        "score": conv.quality_score,
        "label": conv.quality_label,
        "breakdown": {"reason": conv.quality_reason or ""},
    }


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, session: AsyncSession = Depends(get_session)):
    repo = ConversationRepo(session)
    deleted = await repo.delete(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
