from __future__ import annotations

from typing import Literal

import orjson
from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph

from analytics_agent.agent.llm import get_llm
from analytics_agent.agent.state import AgentState
from analytics_agent.prompts.system import build_system_prompt

# Write-back skills are opt-in; only included when explicitly enabled by the user
_SKILL_TOOL_NAMES: frozenset[str] = frozenset({"publish_analysis", "save_correction"})
_MUTATION_TOOL_NAMES = _SKILL_TOOL_NAMES  # alias used in filter below


def get_last_sql_result(state: AgentState) -> dict | None:
    """Scan message history for the last execute_sql ToolMessage and parse its content."""
    for msg in reversed(state["messages"]):
        if isinstance(msg, ToolMessage) and getattr(msg, "name", None) == "execute_sql":
            try:
                if isinstance(msg.content, str):
                    return orjson.loads(msg.content)
            except Exception:
                pass
    return None


def _route_after_agent(state: AgentState) -> Literal["chart", "__end__"]:
    result = get_last_sql_result(state)
    if result and result.get("rows"):
        return "chart"
    return "__end__"


def build_graph(
    engine_name: str,
    engine=None,  # pre-resolved engine from resolver.py; if None falls back to registry
    system_prompt_override: str | None = None,
    disabled_tools: set[str] | None = None,
    enabled_mutations: set[str] | None = None,
    context_tools: list | None = None,  # pre-built from DB context platforms at request time
    engine_tools: list | None = None,  # pre-built for MCP data sources (bypasses QueryEngine)
    suppress_business_context_skill: bool = False,
):
    from analytics_agent.agent.chart_generator import chart_node
    from analytics_agent.engines.factory import get_registry

    disabled = disabled_tools or set()
    llm = get_llm(streaming=True)

    from analytics_agent.agent.chart_tool import create_chart

    # Context platform tools — built dynamically from DB at request time.
    # Falls back to env-var based build only when caller doesn't provide them.
    if context_tools is not None:
        datahub_tools = [t for t in context_tools if t.name not in disabled]
    else:
        from analytics_agent.context.datahub import build_datahub_tools

        datahub_tools = [t for t in build_datahub_tools() if t.name not in disabled]

    # Always-on skills (context search etc.) + opt-in write-back skills
    from analytics_agent.skills.loader import build_always_on_skill_tools, build_skill_tools

    always_on_skills = build_always_on_skill_tools()
    if suppress_business_context_skill:
        always_on_skills = [t for t in always_on_skills if t.name != "search_business_context"]
    skill_tools = always_on_skills + build_skill_tools(enabled_mutations or set())

    # Engine tools — MCP data sources supply pre-built tools; native engines use QueryEngine
    if engine_tools is not None:
        engine_tools = [t for t in engine_tools if t.name not in disabled]
    else:
        if engine is None:
            registry = get_registry()
            engine = registry.get(engine_name)
            if not engine:
                raise ValueError(f"Engine '{engine_name}' not found.")
        engine_tools = [t for t in engine.get_tools() if t.name not in disabled]
    chart_tools = [] if "create_chart" in disabled else [create_chart]
    all_tools = datahub_tools + skill_tools + engine_tools + chart_tools

    if system_prompt_override:
        from analytics_agent.skills.loader import (
            get_improve_context_prompt_section,
            get_search_business_context_section,
            get_skill_system_prompt_section,
        )

        system_prompt = system_prompt_override.format(engine_name=engine_name)
        if not suppress_business_context_skill:
            system_prompt += get_search_business_context_section()
        system_prompt += get_improve_context_prompt_section()
        if enabled_mutations:
            system_prompt += get_skill_system_prompt_section(enabled_mutations)
    else:
        system_prompt = build_system_prompt(
            engine_name,
            enabled_skills=enabled_mutations,
            include_business_context=not suppress_business_context_skill,
        )

    # Enable per-tool error handling so validation errors (e.g. hallucinated
    # arguments like filter= on get_entities) are returned as tool messages
    # the agent can read and recover from, rather than crashing the loop.
    for tool in all_tools:
        tool.handle_tool_error = True

    react_agent = create_agent(
        model=llm,
        tools=all_tools,
        state_schema=AgentState,
        system_prompt=system_prompt,
    )

    graph = StateGraph(AgentState)
    graph.add_node("agent", react_agent)
    graph.add_node("chart", chart_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_agent,
        {"chart": "chart", "__end__": END},
    )
    graph.add_edge("chart", END)

    return graph.compile()
