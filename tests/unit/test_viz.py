"""Offline regression coverage for intent binding, both generation paths, and SSE."""

from unittest.mock import AsyncMock, patch

import orjson
import pytest
from analytics_agent.agent.viz import build_chart_payload
from langchain_core.messages import AIMessage

ROWS = [
    {"month": "2026-01", "revenue": 120},
    {"month": "2026-02", "revenue": None},
    {"month": "2026-03", "revenue": -20},
]
INTENT = {"version": 1, "kind": "line", "title": "Revenue", "category": "month", "value": "revenue"}


def test_binds_actual_rows_and_roundtrips():
    payload = build_chart_payload({"viz_intent": INTENT, "rows": [{"revenue": 999}]}, ROWS)
    assert payload["rows"] == ROWS
    assert payload["viz_intent"]["version"] == 1
    assert orjson.loads(orjson.dumps(payload)) == payload


@pytest.mark.parametrize(
    "intent,rows",
    [
        ({**INTENT, "version": 2}, ROWS),
        ({**INTENT, "value": "invented"}, ROWS),
        ({**INTENT, "category": "invented"}, ROWS),
        ({**INTENT, "kind": "javascript"}, ROWS),
        ({**INTENT, "category": "revenue"}, ROWS),
        (INTENT, ROWS + ROWS),
        (INTENT, [{"month": "Jan", "revenue": float("inf")}]),
        (INTENT, [{"month": "Jan", "revenue": True}]),
        (INTENT, [{"month": "Jan", "revenue": "1.20"}]),
        (INTENT, [{"month": "Jan", "revenue": None}]),
        (INTENT, []),
        ({**INTENT, "kind": "bar"}, [{"month": str(i), "revenue": i} for i in range(51)]),
        (
            {**INTENT, "series": "group"},
            [{"month": "Jan", "revenue": 1, "group": str(i)} for i in range(9)],
        ),
        ({"version": 1, "kind": "kpi", "title": "Revenue", "value": "revenue"}, ROWS),
    ],
)
def test_unsupported_input_keeps_table(intent, rows):
    result = build_chart_payload({"viz_intent": intent}, rows)
    assert result["chart_type"] == "table"
    assert result["rows"] == rows
    assert "viz_error" in result


@pytest.mark.parametrize("kind", ["kpi", "bar", "diverging_bar", "line", "area"])
def test_catalog_supports_negative_and_null_values(kind):
    assert build_chart_payload({"viz_intent": {**INTENT, "kind": kind}}, ROWS)["chart_type"] == kind


def test_vega_fallback_uses_full_rows():
    result = build_chart_payload(
        {"chart_type": "pie", "chart_schema": {"mark": "arc", "data": {"values": []}}}, ROWS
    )
    assert result["vega_lite_spec"]["data"]["values"] == ROWS
    assert result["vega_lite_spec"]["mark"] == "arc"


async def test_chart_node_sse_and_tool_share_contract():
    from analytics_agent.agent.chart_generator import chart_node
    from analytics_agent.agent.chart_tool import _pending_charts, create_chart
    from analytics_agent.agent.streaming import stream_graph_events

    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content=orjson.dumps({"viz_intent": INTENT}).decode())
    with (
        patch("analytics_agent.agent.chart_generator.get_chart_llm", return_value=llm),
        patch(
            "analytics_agent.agent.graph.get_last_sql_result",
            return_value={"rows": ROWS, "columns": ["month", "revenue"]},
        ),
    ):
        state = await chart_node({"user_question": "Revenue trend"})

    class Graph:
        async def astream_events(self, *args, **kwargs):
            yield {"event": "on_chain_end", "name": "LangGraph", "data": {"output": state}}

    events = [e async for e in stream_graph_events(Graph(), "Revenue", "conv", "engine")]
    chart = next(e["payload"] for e in events if e["event"] == "CHART")
    assert chart["rows"] == ROWS
    assert chart["viz_intent"]["kind"] == "line"
    with patch("analytics_agent.agent.llm.get_chart_llm", return_value=llm):
        summary = await create_chart.ainvoke({"data": ROWS, "question": "Revenue"})
    chart_id = summary.split()[0].removeprefix("CHART_READY:")
    tool_chart = _pending_charts.pop(chart_id)
    assert tool_chart == {k: v for k, v in chart.items() if k != "truncated"}
    assert "viz_intent" not in summary


async def test_chart_payload_survives_database_reload():
    from analytics_agent.db.models import Base, Conversation, Message
    from analytics_agent.db.repository import ConversationRepo, MessageRepo
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    payload = build_chart_payload({"viz_intent": INTENT}, ROWS)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await ConversationRepo(session).create(
                Conversation(id="viz", title="Chart", engine_name="demo")
            )
            await MessageRepo(session).create(
                Message(
                    id="chart",
                    conversation_id="viz",
                    role="assistant",
                    event_type="CHART",
                    payload=orjson.dumps(payload).decode(),
                    sequence=0,
                )
            )
        async with AsyncSession(engine) as session:
            stored = await MessageRepo(session).list_for_conversation("viz")
            assert orjson.loads(stored[0].payload) == payload
    finally:
        await engine.dispose()
