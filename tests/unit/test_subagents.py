"""Unit tests for the configurable sub-agent builder."""

from __future__ import annotations

import pytest
from langchain_core.tools import BaseTool, tool

from analytics_agent.agent.subagents import (
    BUILTINS,
    SqlAuthorResult,
    SubagentsConfig,
    ToolPool,
    build_subagents,
    list_builtins,
    parse_config,
    split_datahub_tools,
)


def _make_tool(name: str) -> BaseTool:
    @tool(name)
    def _fn(arg: str) -> str:
        """Stub."""
        return arg

    return _fn


@pytest.fixture
def pool() -> ToolPool:
    return ToolPool(
        datahub_reads=[_make_tool("search"), _make_tool("get_entities"), _make_tool("get_lineage")],
        datahub_writes=[_make_tool("add_tags"), _make_tool("set_owners")],
        engine_tools=[_make_tool("execute_sql"), _make_tool("get_schema"), _make_tool("preview_table")],
        skill_tools=[_make_tool("search_documents")],
        research_tools=[_make_tool("search_business_context")],
    )


def test_empty_config_builds_all_builtins_when_pool_supports_them(pool):
    # An empty SubagentsConfig() (the dataclass default, not parse_config)
    # still enables every builtin. The "everything disabled by default"
    # policy lives in parse_config() — see test_parse_config_no_row_disables_all_builtins.
    subs = build_subagents(pool, SubagentsConfig())
    names = sorted(s["name"] for s in subs)
    assert names == sorted(BUILTINS.keys())


def test_parse_config_no_row_disables_all_builtins():
    cfg = parse_config(None)
    assert set(cfg.disabled_builtins) == set(BUILTINS.keys())


def test_parse_config_empty_blob_disables_all_builtins():
    cfg = parse_config("{}")
    assert set(cfg.disabled_builtins) == set(BUILTINS.keys())


def test_parse_config_saved_blob_used_verbatim():
    # Once any non-empty config is saved, it's used verbatim — including
    # one that opts every builtin back in.
    cfg = parse_config('{"disabled_builtins": [], "custom": []}')
    assert cfg.disabled_builtins == []


def test_disabled_builtin_is_excluded(pool):
    cfg = SubagentsConfig(disabled_builtins=["data-profiler"])
    subs = build_subagents(pool, cfg)
    assert "data-profiler" not in {s["name"] for s in subs}


def test_builtin_with_empty_pool_is_dropped():
    # datahub-editor needs datahub_writes; with none in the pool it must
    # not be registered (otherwise the agent has a sub-agent it can't use).
    pool = ToolPool(
        datahub_reads=[_make_tool("search")],
        engine_tools=[_make_tool("execute_sql")],
    )
    subs = build_subagents(pool, SubagentsConfig())
    assert "datahub-editor" not in {s["name"] for s in subs}


def test_builtin_override_replaces_description_and_tools(pool):
    cfg = SubagentsConfig(
        builtin_overrides={
            "sql-author": {
                "description": "custom desc",
                "tool_names": ["execute_sql"],
            }
        }
    )
    subs = build_subagents(pool, cfg)
    sql_author = next(s for s in subs if s["name"] == "sql-author")
    # SubAgent is a TypedDict in deepagents; field access via subscripting.
    assert sql_author["description"] == "custom desc"
    assert [t.name for t in sql_author["tools"]] == ["execute_sql"]


def test_sql_author_keeps_response_format(pool):
    subs = build_subagents(pool, SubagentsConfig())
    sql_author = next(s for s in subs if s["name"] == "sql-author")
    assert sql_author.get("response_format") is SqlAuthorResult


def test_custom_subagent_resolves_tools(pool):
    cfg = SubagentsConfig(
        custom=[
            {
                "name": "metrics-doctor",
                "description": "Diagnose metric definitions.",
                "system_prompt": "You diagnose metric definitions.",
                "tool_names": ["search_documents", "search_business_context"],
            }
        ]
    )
    subs = build_subagents(pool, cfg)
    md = next(s for s in subs if s["name"] == "metrics-doctor")
    assert sorted(t.name for t in md["tools"]) == [
        "search_business_context",
        "search_documents",
    ]


def test_custom_with_unknown_tool_drops_unknowns_but_keeps_known(pool):
    cfg = SubagentsConfig(
        custom=[
            {
                "name": "x",
                "description": "d",
                "system_prompt": "s",
                "tool_names": ["search_documents", "nope_does_not_exist"],
            }
        ]
    )
    subs = build_subagents(pool, cfg)
    x = next(s for s in subs if s["name"] == "x")
    assert [t.name for t in x["tools"]] == ["search_documents"]


def test_custom_with_zero_resolved_tools_is_dropped(pool):
    cfg = SubagentsConfig(
        custom=[
            {
                "name": "x",
                "description": "d",
                "system_prompt": "s",
                "tool_names": ["nope_a", "nope_b"],
            }
        ]
    )
    subs = build_subagents(pool, cfg)
    assert "x" not in {s["name"] for s in subs}


def test_custom_colliding_with_builtin_name_is_dropped(pool):
    cfg = SubagentsConfig(
        custom=[
            {
                "name": "sql-author",
                "description": "d",
                "system_prompt": "s",
                "tool_names": ["execute_sql"],
            }
        ]
    )
    subs = build_subagents(pool, cfg)
    sql_authors = [s for s in subs if s["name"] == "sql-author"]
    # Builtin is still there, custom collision is dropped — single entry.
    assert len(sql_authors) == 1


def test_parse_config_handles_missing_and_garbage():
    # Missing / empty / unparseable all fall back to "all disabled".
    assert set(parse_config(None).disabled_builtins) == set(BUILTINS.keys())
    assert set(parse_config("").disabled_builtins) == set(BUILTINS.keys())
    assert set(parse_config("not-json").disabled_builtins) == set(BUILTINS.keys())


def test_parse_config_round_trip():
    cfg = SubagentsConfig(
        disabled_builtins=["data-profiler"],
        builtin_overrides={"sql-author": {"description": "x"}},
        custom=[{"name": "c", "description": "d", "system_prompt": "s", "tool_names": ["t"]}],
    )
    import orjson

    parsed = parse_config(orjson.dumps(cfg.to_dict()).decode())
    assert parsed.disabled_builtins == ["data-profiler"]
    assert parsed.builtin_overrides == {"sql-author": {"description": "x"}}
    assert parsed.custom[0]["name"] == "c"


def test_split_datahub_tools_separates_mutations():
    reads = [_make_tool("search")]
    writes = [_make_tool("add_tags")]
    r, w = split_datahub_tools(reads + writes)
    assert [t.name for t in r] == ["search"]
    assert [t.name for t in w] == ["add_tags"]


def test_list_builtins_shape():
    items = list_builtins()
    names = {i["name"] for i in items}
    assert names == set(BUILTINS.keys())
    sql_author = next(i for i in items if i["name"] == "sql-author")
    assert sql_author["has_response_format"] is True
    explorer = next(i for i in items if i["name"] == "datahub-explorer")
    assert explorer["has_response_format"] is False
