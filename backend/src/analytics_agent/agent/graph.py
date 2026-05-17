from __future__ import annotations

from typing import Any, Literal

import orjson
from deepagents import create_deep_agent
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from analytics_agent.agent.hitl import build_interrupt_config, get_checkpointer
from analytics_agent.agent.llm import get_llm
from analytics_agent.agent.state import AgentState
from analytics_agent.agent.subagents import (
    SubagentsConfig,
    ToolPool,
    build_subagents,
    split_datahub_tools,
)
from analytics_agent.config import settings
from analytics_agent.prompts.system import build_system_prompt
from analytics_agent.skills.loader import build_skill_sources


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
    hitl_policy_override: list[str] | None = None,  # operator-set list of tools to intercept
    subagents_config: SubagentsConfig | None = None,  # operator-set sub-agent overlay
    conversation_id: str | None = None,  # per-conversation Python sandbox cwd
):
    """Build the agent graph backed by `deepagents.create_deep_agent`.

    The inner agent gains a planning tool (`write_todos`), a virtual filesystem
    (`ls`/`read_file`/`write_file`/`edit_file`), and a `task` tool for
    delegating to sub-agents — keeping high-volume turns out of the parent's
    context window.

    Sub-agents are assembled from a builtin registry (sql-author,
    lineage-tracer, data-profiler, datahub-explorer, datahub-editor) plus
    any custom ones the operator has configured via
    `/api/settings/subagents`. Builtins can be individually disabled or
    have their description/system_prompt/tool list overridden.

    The outer `StateGraph` keeps the conditional `chart_node` post-step.
    """
    from analytics_agent.agent.chart_generator import chart_node
    from analytics_agent.agent.chart_tool import create_chart
    from analytics_agent.engines.factory import get_registry

    disabled = disabled_tools or set()
    llm = get_llm(streaming=True)

    # Context platform tools — built dynamically from DB at request time.
    # Falls back to env-var based build only when caller doesn't provide them.
    if context_tools is not None:
        datahub_tools = [t for t in context_tools if t.name not in disabled]
    else:
        from analytics_agent.context.datahub import build_datahub_tools

        datahub_tools = [t for t in build_datahub_tools() if t.name not in disabled]

    # Always-on skills (context search etc.) + opt-in write-back skills
    from analytics_agent.skills.loader import build_always_on_skill_tools, build_skill_tools

    skill_tools = build_always_on_skill_tools() + build_skill_tools(enabled_mutations or set())

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

    from analytics_agent.agent.ask_user import ask_user

    ask_user_tools = [] if "ask_user" in disabled else [ask_user]
    all_tools = datahub_tools + skill_tools + engine_tools + chart_tools + ask_user_tools

    if system_prompt_override:
        system_prompt = system_prompt_override.format(engine_name=engine_name)
    else:
        system_prompt = build_system_prompt(engine_name)

    # Enable per-tool error handling so validation errors (e.g. hallucinated
    # arguments like filter= on get_entities) are returned as tool messages
    # the agent can read and recover from, rather than crashing the loop.
    for tool in all_tools:
        tool.handle_tool_error = True

    # Prompt caching for the system prompt + tool definitions. A breakpoint on
    # the last system block caches tools+system together (render order is
    # tools → system → messages). Anthropic and Bedrock use different syntaxes;
    # other providers ignore the marker entirely.
    system_for_agent: str | SystemMessage = system_prompt
    if settings.enable_prompt_cache:
        if settings.llm_provider == "anthropic":
            system_for_agent = SystemMessage(
                content=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            )
        elif settings.llm_provider == "bedrock":
            # Bedrock Converse uses a separate cachePoint block as a separator
            # rather than an inline cache_control field.
            system_for_agent = SystemMessage(
                content=[
                    {"text": system_prompt},
                    {"cachePoint": {"type": "default"}},
                ]
            )

    # Sub-agents: builtins (sql-author, lineage-tracer, data-profiler,
    # datahub-explorer, datahub-editor) overlaid with operator config.
    # The parent agent does NOT receive datahub_tools directly — catalog
    # reads/writes go through the relevant sub-agent, which keeps entity
    # blobs out of the parent's context window.
    datahub_reads, datahub_writes = split_datahub_tools(datahub_tools)
    tool_pool = ToolPool(
        datahub_reads=datahub_reads,
        datahub_writes=datahub_writes,
        engine_tools=engine_tools,
        skill_tools=skill_tools,
    )
    sub_agents = build_subagents(tool_pool, subagents_config or SubagentsConfig())

    # Per-conversation Python + datahub-CLI sandbox. Off unless explicitly
    # enabled. When off, deepagents falls back to its default StateBackend
    # which provides the virtual filesystem but stubs `execute`.
    backend = None
    if settings.enable_python_sandbox and conversation_id:
        from analytics_agent.agent.sandbox import build_sandbox_backend

        backend = build_sandbox_backend(conversation_id)

    # Human-in-the-loop: pause the graph before mutation tools execute so
    # the user can approve / reject / edit. Tools not in this set
    # auto-proceed. Resume via POST /api/conversations/{id}/resume.
    extra_interrupt_tools: set[str] = set()
    if settings.hitl_interrupt_execute and settings.enable_python_sandbox:
        extra_interrupt_tools.add("execute")
    interrupt_on = build_interrupt_config(
        enabled_mutations,
        extra_interrupt_tools,
        policy_override=hitl_policy_override,
    )

    # Shared checkpointer: required for interrupts to be resumable. The
    # outer StateGraph and the inner deep_agent both need it.
    checkpointer = get_checkpointer()

    deep_agent_kwargs: dict[str, Any] = dict(
        model=llm,
        tools=all_tools,
        system_prompt=system_for_agent,
        subagents=sub_agents,
        skills=build_skill_sources(enabled_mutations),
        interrupt_on=interrupt_on or None,
        checkpointer=checkpointer,
    )
    if backend is not None:
        deep_agent_kwargs["backend"] = backend

    # Typed final-response: agent emits its answer via a structured-output
    # tool call so the frontend can render summary + follow-ups deterministically.
    if settings.enable_structured_response:
        from analytics_agent.agent.response_format import AnalystResponse

        deep_agent_kwargs["response_format"] = AnalystResponse

    # Manual conversation-compaction tool — pairs with the auto-summarization
    # middleware deepagents already adds by default. Lets the agent (or a UI
    # button via a synthetic user turn) trigger compaction on demand.
    extra_middleware: list = []
    if settings.enable_compact_tool:
        try:
            from deepagents.backends.state import StateBackend
            from deepagents.middleware.summarization import (
                create_summarization_tool_middleware,
            )

            # Reuse the sandbox backend when present so conversation
            # history offloads land in the same per-conversation dir as
            # everything else; otherwise StateBackend is fine.
            compact_backend = backend if backend is not None else StateBackend()
            extra_middleware.append(
                create_summarization_tool_middleware(llm, compact_backend)
            )
        except Exception:
            # Older deepagents versions don't expose this factory — skip
            # rather than fail the graph build.
            pass
    if extra_middleware:
        deep_agent_kwargs["middleware"] = extra_middleware
    deep_agent = create_deep_agent(**deep_agent_kwargs)

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

    return graph.compile(checkpointer=checkpointer)
