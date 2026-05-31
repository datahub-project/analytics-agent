"""
Contract tests for engine connectors.

Every supported engine type must be wired through several touchpoints — the
engine factory, the secret-env-vars registry, the per-type tools registry, the
status renderer, and the frontend plugin index. Forgetting any one of them
produces silent UX failures (e.g. a connection that always shows as
"unconfigured", or an empty tool-toggles panel) that don't fail in CI.

This test enumerates every known engine type and asserts each touchpoint
handles it. Add a new entry to MINIMAL_CONFIGS to introduce a connector —
each test will then enforce that the rest of the wiring is in place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Minimal config that should yield a "connected" status for each engine type.
# When adding a new connector, add it here.
MINIMAL_CONFIGS: dict[str, dict[str, str]] = {
    "snowflake": {"account": "x", "user": "y", "password": "z"},
    "hive": {"host": "x", "user": "y", "password": "z"},
    "bigquery": {"project": "x", "credentials_json": '{"x":"y"}'},
    "mysql": {"host": "x", "database": "y", "user": "z", "password": "p"},
    "postgresql": {"host": "x", "database": "y", "user": "z", "password": "p"},
    "sqlite": {"dialect": "sqlite", "database": "/tmp/x.db"},
    "duckdb": {"dialect": "duckdb", "database": "/tmp/x.duckdb"},
}

ENGINE_TYPES = sorted(MINIMAL_CONFIGS)

# Every query engine exposes the same four tools — anything missing means the
# tool-toggles panel in Settings will be incomplete.
_REQUIRED_SQL_TOOLS = {"execute_sql", "list_tables", "get_schema", "preview_table"}

# Plugins in the frontend index follow the convention `${type}Plugin`.
_FRONTEND_INDEX = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "components"
    / "Settings"
    / "connections"
    / "index.ts"
)


@pytest.mark.parametrize("engine_type", ENGINE_TYPES)
def test_factory_returns_callable(engine_type):
    """_engine_cls must return a factory for every known type."""
    from analytics_agent.engines.factory import _engine_cls

    fn = _engine_cls(engine_type)
    assert fn is not None, (
        f"_engine_cls({engine_type!r}) returned None — add it to the dispatch dict in factory.py"
    )
    assert callable(fn)


@pytest.mark.parametrize("engine_type", ENGINE_TYPES)
def test_secret_env_vars_returns_dict(engine_type):
    """get_secret_env_vars must return a dict (possibly empty) for every type."""
    from analytics_agent.engines.factory import get_secret_env_vars

    result = get_secret_env_vars(engine_type)
    assert isinstance(result, dict), (
        f"get_secret_env_vars({engine_type!r}) returned {type(result).__name__}, expected dict"
    )


@pytest.mark.parametrize("engine_type", ENGINE_TYPES)
def test_known_tools_has_standard_sql_tools(engine_type):
    """_KNOWN_TOOLS must list the four standard SQL tools — otherwise the toggle UI is empty."""
    from analytics_agent.api.settings import _KNOWN_TOOLS

    assert engine_type in _KNOWN_TOOLS, (
        f"_KNOWN_TOOLS missing entry for {engine_type!r} — tool toggles panel will be empty"
    )
    tool_names = {t["name"] for t in _KNOWN_TOOLS[engine_type]}
    missing = _REQUIRED_SQL_TOOLS - tool_names
    assert not missing, f"_KNOWN_TOOLS[{engine_type!r}] missing tools: {missing}"


@pytest.mark.parametrize("engine_type", ENGINE_TYPES)
def test_minimal_config_renders_as_connected(engine_type):
    """A minimally-configured connection must show 'connected', not 'unconfigured'."""
    from analytics_agent.api.settings import _compute_engine_status

    status = _compute_engine_status(engine_type, MINIMAL_CONFIGS[engine_type])
    assert status == "connected", (
        f"{engine_type} with minimal config rendered as {status!r}; "
        f"add it to _compute_engine_status (or to the engine's ConnectorSpec)"
    )


@pytest.mark.parametrize("engine_type", ENGINE_TYPES)
def test_empty_config_renders_as_unconfigured(engine_type):
    """An empty config must show 'unconfigured' — the status check is meaningful."""
    from analytics_agent.api.settings import _compute_engine_status

    assert _compute_engine_status(engine_type, {}) == "unconfigured"


@pytest.mark.parametrize("engine_type", ENGINE_TYPES)
def test_frontend_plugin_registered(engine_type):
    """frontend index.ts must import a `${type}Plugin` — otherwise the type is missing from the picker."""
    content = _FRONTEND_INDEX.read_text()
    expected = f"{engine_type}Plugin"
    assert expected in content, (
        f"frontend index.ts missing `{expected}` — add the plugin import and "
        f"register it in CONNECTION_PLUGINS"
    )
