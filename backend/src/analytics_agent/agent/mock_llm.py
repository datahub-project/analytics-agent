"""
Mock LLM streaming for E2E tests.

Activated when MOCK_LLM=1 is set. Bypasses the real LLM and graph entirely;
emits pre-configured TEXT chunks via real HTTP SSE with per-chunk delays so the
frontend sees genuine chunked streaming (not a Playwright network mock).

MOCK_LLM_DELAY_MS controls the inter-chunk delay (default 80ms). Use a value
large enough to guarantee the test can switch conversations mid-stream.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

_MOCK_CHUNKS = [
    "MOCK_LLM ",
    "stream ",
    "chunk ",
    "one. ",
    "MOCK_LLM ",
    "stream ",
    "chunk ",
    "two.",
]


async def mock_stream_events(conversation_id: str, user_text: str) -> AsyncIterator[dict]:
    """Yield TEXT event dicts with inter-chunk delays, then a COMPLETE event."""
    delay = float(os.environ.get("MOCK_LLM_DELAY_MS", "80")) / 1000
    run_id = str(uuid.uuid4())
    full_text = ""

    for chunk in _MOCK_CHUNKS:
        await asyncio.sleep(delay)
        full_text += chunk
        yield {
            "event": "TEXT",
            "conversation_id": conversation_id,
            "message_id": run_id,
            "payload": {"text": chunk},
        }

    yield {
        "event": "COMPLETE",
        "conversation_id": conversation_id,
        "message_id": str(uuid.uuid4()),
        "payload": {"text": full_text},
    }
