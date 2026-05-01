"""Spike: deepagents-based agent graph.

Parallel implementation of `graph.build_graph` that routes through
`deepagents.create_deep_agent` instead of `langchain.agents.create_agent`.
Selected at request time via `settings.use_deep_agents` (USE_DEEP_AGENTS=1).

What changes vs. graph.py:
  - Inner agent is created with `create_deep_agent`, which adds a planning tool
    (`write_todos`), a virtual filesystem (`ls`/`read_file`/`write_file`/
    `edit_file`), and a `task` tool for delegating to sub-agents.
  - One sub-agent is registered: `datahub-explorer`, scoped to DataHub context
    tools so entity search / schema lookup runs in an isolated context window
    and only its summary returns to the parent.

What stays identical:
  - Outer `StateGraph` with the conditional `chart_node` post-step.
  - Tool composition (datahub + skills + engine + chart).
  - System prompt assembly via `build_system_prompt` / overrides.
  - `handle_tool_error = True` on every tool.
"""

from __future__ import annotations

from deepagents import SubAgent, create_deep_agent
from langgraph.graph import END, START, StateGraph

from analytics_agent.agent.graph import _route_after_agent
from analytics_agent.agent.llm import get_llm
from analytics_agent.agent.state import AgentState
from analytics_agent.prompts.system import build_system_prompt


def build_deep_graph(
    engine_name: str,
    engine=None,
    system_prompt_override: str | None = None,
    disabled_tools: set[str] | None = None,
    enabled_mutations: set[str] | None = None,
    context_tools: list | None = None,
    engine_tools: list | None = None,
):
    from analytics_agent.agent.chart_generator import chart_node
    from analytics_agent.agent.chart_tool import create_chart
    from analytics_agent.engines.factory import get_registry

    disabled = disabled_tools or set()
    llm = get_llm(streaming=True)

    # Context tools (DataHub) — same resolution as build_graph.
    if context_tools is not None:
        datahub_tools = [t for t in context_tools if t.name not in disabled]
    else:
        from analytics_agent.context.datahub import build_datahub_tools

        datahub_tools = [t for t in build_datahub_tools() if t.name not in disabled]

    from analytics_agent.skills.loader import build_always_on_skill_tools, build_skill_tools

    skill_tools = build_always_on_skill_tools() + build_skill_tools(enabled_mutations or set())

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
        system_prompt += get_search_business_context_section()
        system_prompt += get_improve_context_prompt_section()
        if enabled_mutations:
            system_prompt += get_skill_system_prompt_section(enabled_mutations)
    else:
        system_prompt = build_system_prompt(engine_name, enabled_skills=enabled_mutations)

    for tool in all_tools:
        tool.handle_tool_error = True

    # Sub-agent: DataHub exploration. Isolates the high-volume entity/schema
    # lookup turns from the parent's context. Returns only a textual summary.
    datahub_explorer = SubAgent(
        name="datahub-explorer",
        description=(
            "Use to research DataHub metadata: find datasets, look up schemas, "
            "search business glossary terms, inspect lineage. Returns a concise "
            "summary of relevant entities and their fields. Prefer this over "
            "calling DataHub tools directly when the question requires more than "
            "one or two lookups."
        ),
        system_prompt=(
            "You are a DataHub metadata research assistant. Use the provided "
            "DataHub tools to answer the parent agent's question precisely. "
            "Return a short, structured summary: dataset URNs, table names, "
            "relevant column names with types, and any business context. Do NOT "
            "execute SQL or generate charts — only research metadata."
        ),
        tools=datahub_tools,
    )

    deep_agent = create_deep_agent(
        model=llm,
        tools=all_tools,
        system_prompt=system_prompt,
        subagents=[datahub_explorer],
    )

    graph = StateGraph(AgentState)
    graph.add_node("agent", deep_agent)
    graph.add_node("chart", chart_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_agent,
        {"chart": "chart", "__end__": END},
    )
    graph.add_edge("chart", END)

    return graph.compile()
