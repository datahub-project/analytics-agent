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
    Generate a validated chart intent or Vega fallback from the last SQL result.
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

        from analytics_agent.agent.viz import build_chart_payload

        payload = build_chart_payload(result, sql_result["rows"])
        payload["truncated"] = bool(sql_result.get("truncated", False))
        return {"pending_chart": payload}
    except Exception:
        logger.exception("Chart generation failed (non-fatal)")

    return {}
