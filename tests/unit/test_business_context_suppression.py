"""
Unit tests for the `search_business_context` skill suppression introduced when a
`datahub-mcp` context platform advertises a `get_context` tool.

Covers:
- build_system_prompt(include_business_context=True/False)
- build_graph(suppress_business_context_skill=True/False) — tool-list filtering
  and system-prompt section injection.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from analytics_agent.prompts.system import build_system_prompt

_SECTION_HEADING = "## Skill: search_business_context"


# ─── build_system_prompt ─────────────────────────────────────────────────────


def test_build_system_prompt_includes_business_context_by_default():
    prompt = build_system_prompt("snowflake")
    assert _SECTION_HEADING in prompt


def test_build_system_prompt_excludes_business_context_when_disabled():
    prompt = build_system_prompt("snowflake", include_business_context=False)
    assert _SECTION_HEADING not in prompt
    assert "## Meta-Skill: /improve-context" in prompt  # unrelated section still present


# ─── build_graph tool-list + prompt injection ────────────────────────────────


def _capture_build_graph(suppress: bool):
    """Build a graph with a stubbed LLM and capture the args passed to create_agent.

    Returns (tool_names, system_prompt_text).
    """
    from analytics_agent.agent import graph as graph_mod

    fake_llm = MagicMock(name="fake_llm")
    captured: dict = {}

    def fake_create_agent(*, model, tools, state_schema, system_prompt):
        captured["tools"] = tools
        captured["system_prompt"] = system_prompt
        compiled = MagicMock(name="react_agent")
        return compiled

    with (
        patch.object(graph_mod, "get_llm", return_value=fake_llm),
        patch.object(graph_mod, "create_agent", side_effect=fake_create_agent),
    ):
        graph_mod.build_graph(
            engine_name="snowflake",
            engine=MagicMock(get_tools=MagicMock(return_value=[])),
            context_tools=[],
            engine_tools=[],
            suppress_business_context_skill=suppress,
        )

    tool_names = {t.name for t in captured["tools"]}
    return tool_names, captured["system_prompt"]


def test_build_graph_includes_search_business_context_by_default():
    tool_names, system_prompt = _capture_build_graph(suppress=False)
    assert "search_business_context" in tool_names
    assert _SECTION_HEADING in system_prompt


def test_build_graph_suppresses_search_business_context_when_flag_set():
    tool_names, system_prompt = _capture_build_graph(suppress=True)
    assert "search_business_context" not in tool_names
    assert _SECTION_HEADING not in system_prompt


def test_build_graph_suppression_also_applies_to_system_prompt_override():
    """When a custom system_prompt_override is used, the section must still be gated."""
    from analytics_agent.agent import graph as graph_mod

    fake_llm = MagicMock(name="fake_llm")
    captured: dict = {}

    def fake_create_agent(*, model, tools, state_schema, system_prompt):
        captured["system_prompt"] = system_prompt
        return MagicMock()

    with (
        patch.object(graph_mod, "get_llm", return_value=fake_llm),
        patch.object(graph_mod, "create_agent", side_effect=fake_create_agent),
    ):
        graph_mod.build_graph(
            engine_name="snowflake",
            engine=MagicMock(get_tools=MagicMock(return_value=[])),
            context_tools=[],
            engine_tools=[],
            system_prompt_override="You are an analyst for {engine_name}.",
            suppress_business_context_skill=True,
        )

    assert _SECTION_HEADING not in captured["system_prompt"]


# ─── chat.py detection logic (row.type + tool name) ──────────────────────────


@pytest.mark.parametrize(
    "row_type, tool_names, expected",
    [
        ("datahub-mcp", ["get_context", "search"], True),
        ("datahub-mcp", ["search", "get_entities"], False),
        ("datahub", ["get_context"], False),  # native DataHub must not trigger
        ("other-mcp", ["get_context"], False),  # unrelated MCP must not trigger
    ],
)
def test_detection_matches_datahub_mcp_with_get_context(row_type, tool_names, expected):
    """Mirror the inline check in chat.py to lock its contract."""
    row = MagicMock(type=row_type)
    tools = [MagicMock(name=n) for n in tool_names]
    # MagicMock assigns `.name` differently than we expect when passed to constructor;
    # set it explicitly.
    for tool, n in zip(tools, tool_names):
        tool.name = n

    triggered = row.type == "datahub-mcp" and any(t.name == "get_context" for t in tools)
    assert triggered is expected
