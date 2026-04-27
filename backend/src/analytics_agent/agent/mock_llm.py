"""
Mock LLM streaming for E2E tests.

Activated when MOCK_LLM=1 is set. Bypasses the real LLM and graph entirely;
emits pre-configured TEXT chunks via real HTTP SSE with per-chunk delays so the
frontend sees genuine chunked streaming (not a Playwright network mock).

MOCK_LLM_DELAY_MS controls the inter-chunk delay (default 80ms). Use a value
large enough to guarantee the test can switch conversations mid-stream.

Behavior varies by prompt keyword so different E2E tests can exercise distinct
UI paths without a real LLM:
  - "data" in prompt  → thinking text + one tool call + result + final text + USAGE
  - anything else     → plain text response + USAGE
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

_TEXT_CHUNKS = [
    "MOCK_LLM ",
    "stream ",
    "chunk ",
    "one. ",
    "MOCK_LLM ",
    "stream ",
    "chunk ",
    "two.",
]

_MOCK_USAGE = {
    "input_tokens": 120,
    "output_tokens": 45,
    "total_tokens": 165,
    "cache_read_tokens": 0,
    "cache_creation_tokens": 0,
    "node": "mock",
}


async def mock_stream_events(conversation_id: str, user_text: str) -> AsyncIterator[dict]:
    """Yield SSE event dicts with inter-chunk delays."""
    delay = float(os.environ.get("MOCK_LLM_DELAY_MS", "80")) / 1000

    if "data" in user_text.lower():
        yield _evt(conversation_id, "TEXT", str(uuid.uuid4()), {"text": "Let me check what data is available."})
        await asyncio.sleep(delay)

        tool_call_id = str(uuid.uuid4())
        yield _evt(conversation_id, "TOOL_CALL", tool_call_id, {
            "tool_name": "list_datasets",
            "tool_input": {},
        })
        await asyncio.sleep(delay)

        yield _evt(conversation_id, "TOOL_RESULT", str(uuid.uuid4()), {
            "tool_name": "list_datasets",
            "result": '["orders", "customers", "products"]',
            "is_error": False,
        })
        await asyncio.sleep(delay)

        final_id = str(uuid.uuid4())
        final_text = "You have orders, customers, and products datasets available."
        yield _evt(conversation_id, "TEXT", final_id, {"text": final_text})
        await asyncio.sleep(delay)

        yield _evt(conversation_id, "USAGE", str(uuid.uuid4()), _MOCK_USAGE)
        await asyncio.sleep(delay)

        yield _evt(conversation_id, "COMPLETE", str(uuid.uuid4()), {"text": final_text})
    else:
        run_id = str(uuid.uuid4())
        full_text = ""
        for chunk in _TEXT_CHUNKS:
            await asyncio.sleep(delay)
            full_text += chunk
            yield _evt(conversation_id, "TEXT", run_id, {"text": chunk})

        yield _evt(conversation_id, "USAGE", str(uuid.uuid4()), _MOCK_USAGE)
        await asyncio.sleep(delay)

        yield _evt(conversation_id, "COMPLETE", str(uuid.uuid4()), {"text": full_text})


def _evt(conversation_id: str, event: str, message_id: str, payload: dict) -> dict:
    return {
        "event": event,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "payload": payload,
    }
