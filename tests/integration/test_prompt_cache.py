"""
Integration test for prompt caching (PR #10).

Requires a real Anthropic API key. Skipped automatically unless ANTHROPIC_API_KEY
is set. Runs two turns against a minimal agent (no DataHub, no SQL engine) and
verifies that:
  - Turn 1 writes the cache (cache_creation_tokens > 0)
  - Turn 2 reads the cache (cache_read_tokens > 0)
  - USAGE events include model and provider fields

The cached content is the system prompt + tool definitions injected by build_graph
via the cache_control marker on the system block. The two turns use different
questions (same graph) so the only shared prefix is the system prompt — proving
the marker is what drives the cache hit, not the conversation history.

Run:
  ANTHROPIC_API_KEY=sk-ant-... uv run pytest tests/integration/test_prompt_cache.py -v -s
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY must be set to run prompt-cache integration tests",
)


# ---------------------------------------------------------------------------
# Fixture: build the graph once for all tests in this module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cached_graph():
    """Minimal agent graph with caching enabled, no external dependencies."""
    from analytics_agent.agent.graph import build_graph
    from analytics_agent.config import settings

    original_cache = settings.enable_prompt_cache
    original_provider = settings.llm_provider
    settings.enable_prompt_cache = True
    settings.llm_provider = "anthropic"
    try:
        # Pass pre-built (empty) tool lists so build_graph skips DataHub and
        # SQL engine lookups — the test only needs the system prompt to be cached.
        graph = build_graph(
            engine_name="none",
            context_tools=[],
            engine_tools=[],
            disabled_tools={"create_chart"},
        )
    finally:
        settings.enable_prompt_cache = original_cache
        settings.llm_provider = original_provider

    return graph


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _first_usage(graph, question: str) -> dict:
    """Run one turn and return the first USAGE payload, or {} if none emitted."""
    from analytics_agent.agent.streaming import stream_graph_events

    async for event in stream_graph_events(graph, question, "integ-cache-conv", "none"):
        if event["event"] == "USAGE":
            return event["payload"]
    return {}


# ---------------------------------------------------------------------------
# Tests — must run in order (turn 1 primes, turn 2 reads)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_1_primes_cache(cached_graph) -> None:
    """First call should write the cache (cache_creation_tokens > 0)."""
    usage = await _first_usage(cached_graph, "Say hello in one word.")
    print(f"\nTurn 1 usage: {usage}")
    assert usage, "No USAGE event emitted on turn 1"
    assert usage.get("cache_creation_tokens", 0) > 0, (
        "Expected cache_creation_tokens > 0 on turn 1 — "
        "the system prompt may be below the 1024-token minimum for caching, "
        f"or cache_control was not injected. Full payload: {usage}"
    )


@pytest.mark.asyncio
async def test_turn_2_reads_cache(cached_graph) -> None:
    """Second call with the same graph should read from cache (cache_read_tokens > 0)."""
    usage = await _first_usage(cached_graph, "Say goodbye in one word.")
    print(f"\nTurn 2 usage: {usage}")
    assert usage, "No USAGE event emitted on turn 2"
    assert usage.get("cache_read_tokens", 0) > 0, (
        "Expected cache_read_tokens > 0 on turn 2. "
        "If turn 1 passed but this failed, the 5-minute cache TTL may have "
        f"expired between the two calls. Full payload: {usage}"
    )


@pytest.mark.asyncio
async def test_usage_event_carries_model_and_provider(cached_graph) -> None:
    """USAGE payload must include model and provider (model-tracking feature in PR #10)."""
    usage = await _first_usage(cached_graph, "What is 1 + 1?")
    print(f"\nUsage for model/provider check: {usage}")
    assert usage, "No USAGE event emitted"
    assert usage.get("model"), f"model field missing or empty in USAGE payload: {usage}"
    assert usage.get("provider") == "anthropic", (
        f"Expected provider='anthropic', got: {usage.get('provider')}"
    )


@pytest.mark.asyncio
async def test_caching_disabled_produces_no_cache_tokens(cached_graph) -> None:
    """When enable_prompt_cache=False, a freshly built graph should have zero cache tokens."""
    from analytics_agent.agent.graph import build_graph
    from analytics_agent.config import settings

    original_cache = settings.enable_prompt_cache
    original_provider = settings.llm_provider
    settings.enable_prompt_cache = False
    settings.llm_provider = "anthropic"
    try:
        no_cache_graph = build_graph(
            engine_name="none",
            context_tools=[],
            engine_tools=[],
            disabled_tools={"create_chart"},
        )
    finally:
        settings.enable_prompt_cache = original_cache
        settings.llm_provider = original_provider

    usage = await _first_usage(no_cache_graph, "Say hi.")
    print(f"\nNo-cache usage: {usage}")
    assert usage, "No USAGE event emitted"
    assert usage.get("cache_creation_tokens", 0) == 0, (
        f"Expected zero cache_creation_tokens when caching is disabled, got: {usage}"
    )
    assert usage.get("cache_read_tokens", 0) == 0, (
        f"Expected zero cache_read_tokens when caching is disabled, got: {usage}"
    )
