from __future__ import annotations

from typing import Any

from deepagents.middleware.filesystem import FilesystemState
from langchain.agents.middleware.todo import PlanningState


# Inherit from both so the deepagents subgraph's `files` (DeltaChannel) and
# `todos` channels propagate up through our outer StateGraph — otherwise
# subgraph state stays in its own checkpoint namespace and `/conversations/
# {id}/files` (which reads outer channel_values) returns empty, missing
# write_file results and FilesystemMiddleware's large-tool-result evictions.
class AgentState(FilesystemState, PlanningState[None]):
    last_sql_result: dict[str, Any] | None
    pending_chart: dict[str, Any] | None  # set by chart_node, emitted by streaming.py
    conversation_id: str
    engine_name: str
    user_question: str
