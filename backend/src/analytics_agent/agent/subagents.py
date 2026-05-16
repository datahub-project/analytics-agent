"""Configurable sub-agent registry for the deep-agent graph.

Two concepts coexist here:

  - **Builtins** (sql-author, lineage-tracer, data-profiler,
    datahub-explorer, datahub-editor): shipped defaults. Each defines
    a name, description, system prompt, and a `default_tools`
    selector that resolves against the request-time tool pool (so the
    set auto-adapts when tools are added or renamed). Operators can
    disable any builtin and/or override its description, system
    prompt, and tool list via the `subagents_config` setting.

  - **Custom**: user-defined sub-agents. Each is just a stored
    record with name + description + system_prompt + tool_names; the
    tool list is resolved by name against the same pool.

`build_subagents` reads the persisted config, applies overrides, and
returns the final `list[SubAgent]` for `create_deep_agent`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from deepagents import SubAgent
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SqlAuthorResult(BaseModel):
    """Typed return from the sql-author sub-agent (mirrors execute_sql)."""

    sql: str = Field(description="The final, executed SQL query.")
    columns: list[str] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)
    row_count: int = Field(default=0)
    summary: str = Field(description="One- or two-sentence answer.")
    error: str | None = Field(default=None)


_LINEAGE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_lineage",
        "get_entities",
        "search",
        "list_schema_fields",
        "search_documents",
        "get_dataset_queries",
    }
)


# Selector receives a `ToolPool` and returns the list of tools that
# sub-agent should receive when no operator override is in effect.
ToolSelector = Callable[["ToolPool"], list[BaseTool]]


@dataclass(frozen=True)
class BuiltinSpec:
    """Compile-time spec for a builtin sub-agent.

    `default_tools` is a callable so the tool set auto-adapts to which
    tools are actually registered at request time (e.g. mutation tools
    only appear when enabled_mutations is non-empty).
    """

    name: str
    description: str
    system_prompt: str
    default_tools: ToolSelector
    response_format: type[BaseModel] | None = None


@dataclass
class ToolPool:
    """Bundle of request-time tools, partitioned by class.

    Builders pick from these to assemble each sub-agent's tool list.
    """

    datahub_reads: list[BaseTool] = field(default_factory=list)
    datahub_writes: list[BaseTool] = field(default_factory=list)
    engine_tools: list[BaseTool] = field(default_factory=list)
    skill_tools: list[BaseTool] = field(default_factory=list)
    research_tools: list[BaseTool] = field(default_factory=list)

    def by_name(self) -> dict[str, BaseTool]:
        """All tools indexed by name. Used to resolve custom sub-agent tool lists."""
        merged: dict[str, BaseTool] = {}
        for bucket in (
            self.datahub_reads,
            self.datahub_writes,
            self.engine_tools,
            self.skill_tools,
            self.research_tools,
        ):
            for t in bucket:
                merged[t.name] = t
        return merged


def split_datahub_tools(
    datahub_tools: list[BaseTool],
) -> tuple[list[BaseTool], list[BaseTool]]:
    """Partition DataHub tools into (reads, writes) by HITL mutation set."""
    from analytics_agent.agent.hitl import DATAHUB_MUTATION_TOOLS

    reads = [t for t in datahub_tools if t.name not in DATAHUB_MUTATION_TOOLS]
    writes = [t for t in datahub_tools if t.name in DATAHUB_MUTATION_TOOLS]
    return reads, writes


# ── Builtin specs ─────────────────────────────────────────────────────────

BUILTINS: dict[str, BuiltinSpec] = {
    "datahub-explorer": BuiltinSpec(
        name="datahub-explorer",
        description=(
            "USE THIS for any DataHub catalog read — find datasets, look up "
            "schemas, search business glossary terms, fetch entity metadata, "
            "inspect upstream/downstream lineage. Owns every read-class DataHub "
            "tool plus `search_business_context`. The parent has no direct "
            "DataHub tools; route all catalog research through here."
        ),
        system_prompt=(
            "You are a DataHub metadata research assistant. Use the provided "
            "DataHub tools to answer the parent agent's question precisely. "
            "When the question mentions a business concept or metric (e.g. "
            "'churn', 'active seller'), call `search_business_context` first.\n\n"
            "Return a short, structured summary: dataset URNs, table names, "
            "relevant column names with types, ownership/glossary/domain "
            "context, and any documentation that bears on the parent's "
            "question. Do NOT execute SQL or generate charts — only research."
        ),
        default_tools=lambda p: p.datahub_reads + p.research_tools,
    ),
    "datahub-editor": BuiltinSpec(
        name="datahub-editor",
        description=(
            "USE THIS to apply approved changes to DataHub — add/remove tags or "
            "glossary terms, update descriptions, set domains, set or remove "
            "owners. Every action surfaces a HITL approval card. Only invoke "
            "AFTER the user has explicitly authorized the change."
        ),
        system_prompt=(
            "You are a DataHub catalog editor. The parent has decided that a "
            "specific change should be made and the user has authorized it.\n\n"
            "  1. Confirm the URN(s) and the exact change before calling a "
            "mutation. If the parent gave you a name instead of a URN, ask "
            "for the URN — don't guess.\n"
            "  2. Call the appropriate mutation tool. Each call pauses for "
            "user approval.\n"
            "  3. Return a short summary: which entities were updated, what "
            "changed, and any rejected/skipped calls with reasons."
        ),
        default_tools=lambda p: p.datahub_writes,
    ),
    "sql-author": BuiltinSpec(
        name="sql-author",
        description=(
            "Use when the user's question requires authoring and executing SQL. "
            "Handles schema lookup, query drafting, execution, and retry in an "
            "isolated context. Returns the final SQL plus a structured result "
            "(columns, rows, summary)."
        ),
        system_prompt=(
            "You are a SQL authoring specialist.\n\n"
            "Workflow:\n"
            "  1. Confirm schema via `list_tables` / `get_schema` if the parent "
            "did not already supply a target table + columns.\n"
            "  2. Draft SQL conservatively — explicit column lists, qualify "
            "tables, prefer LIMIT for exploratory queries.\n"
            "  3. Execute via `execute_sql`. On failure, read the error, fix, "
            "and retry up to 3 times. Do NOT ask the parent for help.\n"
            "  4. Return a SqlAuthorResult: include `sql`, `columns`, `rows`, "
            "`row_count`, and a 1–2 sentence `summary`. If you cannot produce "
            "a working query, set `error` and leave rows empty."
        ),
        default_tools=lambda p: p.engine_tools + p.datahub_reads,
        response_format=SqlAuthorResult,
    ),
    "lineage-tracer": BuiltinSpec(
        name="lineage-tracer",
        description=(
            "Use to trace data lineage — find upstream sources, identify "
            "downstream consumers, or assess blast radius. Walks the lineage "
            "graph and returns a concise summary (root sources, key hops, "
            "terminal consumers, gaps)."
        ),
        system_prompt=(
            "You are a DataHub lineage analyst. Use `get_lineage` and related "
            "tools to traverse the lineage graph for the dataset(s) the "
            "parent names. Walk at most 5 hops.\n\n"
            "Return a structured summary:\n"
            "  - Root sources (datasets with no upstream)\n"
            "  - Key transformations (notable hops, jobs, query patterns)\n"
            "  - Terminal consumers (dashboards, ML features, downstream tables)\n"
            "  - Gaps (any hops where lineage was missing or ambiguous)\n\n"
            "Do NOT execute SQL or generate charts."
        ),
        default_tools=lambda p: (
            [t for t in p.datahub_reads if t.name in _LINEAGE_TOOL_NAMES]
            or p.datahub_reads
        ),
    ),
    "data-profiler": BuiltinSpec(
        name="data-profiler",
        description=(
            "Use to characterize a table before writing analysis SQL — column "
            "types, null rates, cardinality, value distributions, sample rows. "
            "Returns a column-level profile summary."
        ),
        system_prompt=(
            "You are a data profiling specialist.\n\n"
            "Given a fully-qualified table name from the parent:\n"
            "  1. `get_schema` to enumerate columns + types.\n"
            "  2. `preview_table` (limit 20) for sample values.\n"
            "  3. For non-trivial columns, batch profiling stats into one "
            "`execute_sql`: COUNT(*), COUNT(DISTINCT col), null counts. Use "
            "TABLESAMPLE if the warehouse supports it.\n"
            "  4. Return a per-column summary. Do NOT dump full result rows."
        ),
        default_tools=lambda p: p.engine_tools,
    ),
}


# ── Config ────────────────────────────────────────────────────────────────


_SETTINGS_KEY = "subagents_config"


@dataclass
class SubagentsConfig:
    """Operator-controlled overlay on top of BUILTINS."""

    disabled_builtins: list[str] = field(default_factory=list)
    # Override description / system_prompt / tool_names per builtin name.
    # Any field that's missing or null falls back to the builtin's default.
    builtin_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Custom user-defined sub-agents. `tool_names` is resolved by name
    # against the request-time pool; unresolved names are dropped with a warning.
    custom: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> SubagentsConfig:
        if not raw:
            return cls()
        return cls(
            disabled_builtins=list(raw.get("disabled_builtins") or []),
            builtin_overrides=dict(raw.get("builtin_overrides") or {}),
            custom=list(raw.get("custom") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "disabled_builtins": list(self.disabled_builtins),
            "builtin_overrides": dict(self.builtin_overrides),
            "custom": list(self.custom),
        }


SETTINGS_KEY = _SETTINGS_KEY  # public re-export for the API layer


def parse_config(raw: str | None) -> SubagentsConfig:
    """Parse a JSON-encoded subagents_config blob from the settings table.

    Returns an empty config when raw is None/empty or unparseable.
    """
    import orjson

    if not raw:
        return SubagentsConfig()
    try:
        return SubagentsConfig.from_dict(orjson.loads(raw))
    except Exception:
        logger.exception("subagents_config row is not valid JSON; ignoring")
        return SubagentsConfig()


# ── Build ─────────────────────────────────────────────────────────────────


def _resolve_tool_names(names: list[str], pool: ToolPool) -> list[BaseTool]:
    by_name = pool.by_name()
    out: list[BaseTool] = []
    missing: list[str] = []
    for n in names:
        t = by_name.get(n)
        if t is None:
            missing.append(n)
        else:
            out.append(t)
    if missing:
        logger.warning("sub-agent tool names not found in pool: %s", missing)
    return out


def _build_builtin(
    spec: BuiltinSpec,
    override: dict[str, Any] | None,
    pool: ToolPool,
) -> SubAgent | None:
    """Instantiate a builtin, applying any override fields.

    Returns None when the resolved tool list is empty — registering a
    sub-agent with zero tools misleads the parent (the description
    promises capabilities the agent can't use).
    """
    description = (override or {}).get("description") or spec.description
    system_prompt = (override or {}).get("system_prompt") or spec.system_prompt
    override_tool_names = (override or {}).get("tool_names")
    if override_tool_names:
        tools = _resolve_tool_names(list(override_tool_names), pool)
    else:
        tools = spec.default_tools(pool)
    if not tools:
        logger.info("skipping builtin %r — no tools resolved", spec.name)
        return None
    kwargs: dict[str, Any] = dict(
        name=spec.name,
        description=description,
        system_prompt=system_prompt,
        tools=tools,
    )
    if spec.response_format is not None:
        kwargs["response_format"] = spec.response_format
    return SubAgent(**kwargs)


def _build_custom(record: dict[str, Any], pool: ToolPool) -> SubAgent | None:
    name = (record.get("name") or "").strip()
    if not name:
        logger.warning("custom sub-agent missing name; skipping: %r", record)
        return None
    if name in BUILTINS:
        logger.warning("custom sub-agent %r collides with builtin name; skipping", name)
        return None
    description = (record.get("description") or "").strip()
    system_prompt = (record.get("system_prompt") or "").strip()
    if not description or not system_prompt:
        logger.warning(
            "custom sub-agent %r missing description or system_prompt; skipping", name
        )
        return None
    tools = _resolve_tool_names(list(record.get("tool_names") or []), pool)
    if not tools:
        logger.warning("custom sub-agent %r has no resolvable tools; skipping", name)
        return None
    return SubAgent(
        name=name, description=description, system_prompt=system_prompt, tools=tools
    )


def build_subagents(
    pool: ToolPool,
    config: SubagentsConfig,
) -> list[SubAgent]:
    """Construct the SubAgent list for `create_deep_agent`.

    Builtins not in `disabled_builtins` are included with any override
    applied; custom records are appended. Sub-agents that resolve to an
    empty tool list are silently dropped.
    """
    cfg = config
    disabled = set(cfg.disabled_builtins)
    out: list[SubAgent] = []
    for name, spec in BUILTINS.items():
        if name in disabled:
            continue
        sub = _build_builtin(spec, cfg.builtin_overrides.get(name), pool)
        if sub is not None:
            out.append(sub)
    for rec in cfg.custom:
        sub = _build_custom(rec, pool)
        if sub is not None:
            out.append(sub)
    return out


def list_builtins() -> list[dict[str, Any]]:
    """Public read of builtin specs for the settings API.

    Returns name, description, system_prompt, default tool selector
    description (the callable can't be serialized — we send a marker
    indicating "auto"). Used by the UI to show editable defaults.
    """
    return [
        {
            "name": s.name,
            "description": s.description,
            "system_prompt": s.system_prompt,
            "has_response_format": s.response_format is not None,
        }
        for s in BUILTINS.values()
    ]
