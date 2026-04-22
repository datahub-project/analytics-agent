from __future__ import annotations

import logging
import uuid

import orjson
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Side-channel: keyed by chart_id so streaming.py can fetch the spec
# without the model ever seeing the full JSON.
_pending_charts: dict[str, dict] = {}


@tool
async def create_chart(
    data: list[dict] | None = None,
    question: str = "",
    title: str = "",
    color_scheme: str = "",
) -> str:
    """
    Generate a Vega-Lite chart from structured data. Call this when the user asks
    for a chart, graph, or visualization. The chart renders automatically in the UI.

    Args:
        data: list of dicts with consistent keys (e.g. [{"platform": "snowflake", "count": 2290}])
        question: the user's question or description of what to visualize
        title: optional chart title
        color_scheme: optional color instruction e.g. "rainbow", "blue", "categorical", "green"

    On follow-up requests to change chart colors or style, call this again with the
    same data and the new color_scheme.

    Example: create_chart(data=[...], question="datasets by platform", color_scheme="rainbow")
    """
    from analytics_agent.agent.llm import get_chart_llm
    from analytics_agent.prompts.chart import CHART_SYSTEM_PROMPT, build_chart_user_prompt

    if not data:
        return "No data provided — cannot create chart."

    columns = list(data[0].keys()) if data else []
    llm = get_chart_llm()

    full_question = question or title
    if color_scheme:
        full_question = f"{full_question} (use {color_scheme} color scheme)"

    user_prompt = build_chart_user_prompt(
        question=full_question,
        sql="",
        columns=columns,
        sample_rows=data[:50],
    )

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        response = await llm.ainvoke(
            [SystemMessage(content=CHART_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
        )

        raw = response.content
        if isinstance(raw, list):
            raw = next(
                (b.get("text", "") for b in raw if isinstance(b, dict) and b.get("type") == "text"),
                "",
            )
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = orjson.loads(raw.strip())

        chart_schema = result.get("chart_schema", {})
        chart_type = result.get("chart_type", "")

        if chart_schema and chart_type:
            chart_schema["data"] = {"values": data}

        # Store spec in side-channel — return a short human-readable summary so
        # the model retains context for follow-up requests (e.g. "change color")
        chart_id = str(uuid.uuid4())
        _pending_charts[chart_id] = {
            "vega_lite_spec": chart_schema,
            "reasoning": result.get("reasoning", ""),
            "chart_type": chart_type,
        }
        color_note = f", color_scheme={color_scheme!r}" if color_scheme else ""
        # Include the full data inline so the model can reuse it on follow-up requests
        # (e.g. "redraw with different colors")
        data_summary = orjson.dumps(data).decode()
        return (
            f"CHART_READY:{chart_id} "
            f"({chart_type} chart, {len(data)} rows{color_note})\n"
            f"data={data_summary}"
        )

    except Exception as e:
        logger.exception("create_chart failed")
        return f"Chart generation failed: {e}"
