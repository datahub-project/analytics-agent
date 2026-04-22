from __future__ import annotations

import logging

import orjson
from langchain_core.messages import HumanMessage, SystemMessage

from analytics_agent.agent.llm import get_chart_llm
from analytics_agent.agent.state import AgentState
from analytics_agent.prompts.chart import CHART_SYSTEM_PROMPT, build_chart_user_prompt

logger = logging.getLogger(__name__)


async def chart_node(state: AgentState) -> dict:
    """
    Generate a Vega-Lite chart spec from the last SQL result and store it in state.
    streaming.py reads it from state after the graph completes.
    """
    from analytics_agent.agent.graph import get_last_sql_result

    sql_result = get_last_sql_result(state)
    if not sql_result or not sql_result.get("rows"):
        return {}

    llm = get_chart_llm()

    user_prompt = build_chart_user_prompt(
        question=state.get("user_question", ""),
        sql=sql_result.get("sql", ""),
        columns=sql_result.get("columns", []),
        sample_rows=sql_result.get("rows", []),
    )

    try:
        response = await llm.ainvoke(
            [SystemMessage(content=CHART_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
        )

        raw = response.content
        if isinstance(raw, list):
            # Anthropic returns list of content blocks
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
            chart_schema["data"] = {"values": sql_result.get("rows", [])}

        # Store in state so streaming.py can emit it after graph completion
        return {
            "pending_chart": {
                "vega_lite_spec": chart_schema,
                "reasoning": result.get("reasoning", ""),
                "chart_type": chart_type,
            }
        }
    except Exception:
        logger.exception("Chart generation failed (non-fatal)")

    return {}
