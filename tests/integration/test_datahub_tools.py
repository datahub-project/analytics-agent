"""
Integration tests against a live DataHub instance (fieldeng.acryl.io).

Credentials are resolved automatically — no manual env vars needed if you've run:
  datahub init --host https://fieldeng.acryl.io/gms --token <token>
  (or: datahub init --sso --host https://fieldeng.acryl.io/gms)

That writes ~/.datahubenv which DataHubClient.from_env() reads.
Alternatively set DATAHUB_GMS_URL + DATAHUB_GMS_TOKEN env vars.

Run with:
  uv run pytest tests/integration/test_datahub_tools.py -v -s
"""

import os
import pathlib

import pytest

_has_credentials = (
    os.environ.get("DATAHUB_GMS_URL") and os.environ.get("DATAHUB_GMS_TOKEN")
) or pathlib.Path("~/.datahubenv").expanduser().exists()

pytestmark = pytest.mark.skipif(
    not _has_credentials,
    reason="No DataHub credentials: run `datahub init --host https://fieldeng.acryl.io/gms --token <token>`",
)


@pytest.fixture(scope="module")
def datahub_client():
    from datahub.sdk.main_client import DataHubClient

    return DataHubClient.from_env()


@pytest.fixture(scope="module")
def tools(datahub_client):
    from datahub_agent_context.langchain_tools import build_langchain_tools

    return {t.name: t for t in build_langchain_tools(datahub_client, include_mutations=False)}


# ── Tool loading ────────────────────────────────────────────────────────────


def test_tools_load(tools):
    assert set(tools.keys()), "No tools loaded"
    # Spot-check the stable core tools rather than asserting exact equality —
    # new tools are added in datahub-agent-context without breaking the agent.
    required = {"search", "get_entities", "list_schema_fields", "get_me"}
    assert required <= set(tools.keys()), f"Missing required tools: {required - set(tools.keys())}"


# ── get_me ──────────────────────────────────────────────────────────────────


def test_get_me(tools):
    result = tools["get_me"].invoke({})
    print("\nget_me:", result)
    assert result  # non-empty response


# ── search ──────────────────────────────────────────────────────────────────


def test_search_wildcard(tools):
    import orjson

    result = tools["search"].invoke({"query": "*", "num_results": 5})
    parsed = orjson.loads(result) if isinstance(result, str) else result
    print("\nsearch(*) result:", str(parsed)[:300])
    assert parsed


def test_search_keyword(tools):
    import orjson

    result = tools["search"].invoke({"query": "customer", "num_results": 3})
    parsed = orjson.loads(result) if isinstance(result, str) else result
    print("\nsearch(customer):", str(parsed)[:300])
    assert parsed is not None


# ── search_documents ─────────────────────────────────────────────────────────


def test_search_documents(tools):
    import orjson

    result = tools["search_documents"].invoke({"query": "*", "num_results": 3})
    parsed = orjson.loads(result) if isinstance(result, str) else result
    print("\nsearch_documents:", str(parsed)[:300])
    assert parsed is not None


# ── Full agent round-trip (requires OPENAI_API_KEY) ────────────────────────


@pytest.mark.skipif(
    not (os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")),
    reason="OPENAI_API_KEY or ANTHROPIC_API_KEY must be set",
)
async def test_agent_search_question():
    """Run the full LangGraph agent with DataHub tools only (no query engine)."""
    import orjson
    from analytics_agent.agent.llm import get_llm
    from analytics_agent.agent.state import AgentState
    from analytics_agent.agent.streaming import stream_graph_events
    from analytics_agent.context.datahub import build_datahub_tools

    # Build a minimal graph without a query engine (DataHub tools only)
    from langchain.agents import create_agent
    from langgraph.graph import END, START, StateGraph

    llm = get_llm(streaming=True)
    tools = build_datahub_tools()
    assert tools, "No DataHub tools loaded — check DATAHUB_GMS_URL/TOKEN"

    agent = create_agent(
        model=llm,
        tools=tools,
        state_schema=AgentState,
        system_prompt="You are a data catalog assistant. Answer questions about available datasets using the provided tools.",
    )

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", END)
    compiled = graph.compile()

    events = []
    async for sse_str in stream_graph_events(
        graph=compiled,
        user_text="What datasets are available? Give me 3 examples.",
        conversation_id="test-conv-1",
        engine_name="none",
    ):
        if sse_str.startswith("data:"):
            evt = orjson.loads(sse_str[5:].strip())
            events.append(evt)
            print(
                f"  [{evt['event']}]",
                evt["payload"].get("text", evt["payload"].get("tool_name", ""))[:80],
            )

    event_types = {e["event"] for e in events}
    print("\nEvent types seen:", event_types)
    assert "COMPLETE" in event_types
    assert "TEXT" in event_types or "TOOL_RESULT" in event_types
