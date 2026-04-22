from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import AgentState as _LangChainAgentState


class AgentState(_LangChainAgentState[None]):
    last_sql_result: dict[str, Any] | None
    pending_chart: dict[str, Any] | None  # set by chart_node, emitted by streaming.py
    conversation_id: str
    engine_name: str
    user_question: str
