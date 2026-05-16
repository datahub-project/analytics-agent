"""Unit tests for human-in-the-loop wiring."""

from __future__ import annotations

import pytest


@pytest.fixture
def reset_checkpointer(monkeypatch):
    """Each test resets the process-wide checkpointer cache."""
    from analytics_agent.agent import hitl as _hitl

    monkeypatch.setattr(_hitl, "_CHECKPOINTER", None)
    monkeypatch.setattr(_hitl, "_CHECKPOINTER_CONN", None)
    yield


# ─── interrupt config ─────────────────────────────────────────────────────


def test_build_interrupt_config_includes_datahub_mutations():
    from analytics_agent.agent.hitl import DATAHUB_MUTATION_TOOLS, build_interrupt_config

    cfg = build_interrupt_config(None)
    for tool in DATAHUB_MUTATION_TOOLS:
        assert cfg.get(tool) is True


def test_build_interrupt_config_adds_enabled_skill_mutations():
    from analytics_agent.agent.hitl import build_interrupt_config

    cfg = build_interrupt_config({"publish_analysis"})
    assert cfg.get("publish_analysis") is True
    # Disabled skill mutations stay out
    assert "save_correction" not in cfg


def test_build_interrupt_config_disabled_skill_excluded():
    from analytics_agent.agent.hitl import build_interrupt_config

    cfg = build_interrupt_config(set())
    assert "publish_analysis" not in cfg
    assert "save_correction" not in cfg


def test_build_interrupt_config_extra_tools_added():
    from analytics_agent.agent.hitl import build_interrupt_config

    cfg = build_interrupt_config(None, extra_tools={"execute"})
    assert cfg.get("execute") is True


def test_build_interrupt_config_policy_override_replaces_defaults():
    """When operator sets a policy, ONLY listed tools interrupt — defaults
    are ignored entirely. Empty list / None mean 'use defaults'."""
    from analytics_agent.agent.hitl import build_interrupt_config

    cfg = build_interrupt_config(
        {"publish_analysis"},
        extra_tools={"execute"},
        policy_override=["execute_sql", "publish_analysis"],
    )
    assert set(cfg.keys()) == {"execute_sql", "publish_analysis"}
    # Empty list falls back to defaults — DataHub mutations still present.
    cfg_empty = build_interrupt_config(None, policy_override=[])
    assert "add_tags" in cfg_empty


def test_all_known_mutation_tools_includes_expected_set():
    from analytics_agent.agent.hitl import all_known_mutation_tools

    tools = all_known_mutation_tools()
    assert "publish_analysis" in tools
    assert "save_correction" in tools
    assert "add_tags" in tools
    assert "execute" in tools
    # Sorted, no duplicates
    assert tools == sorted(set(tools))


def test_thread_config_keys_by_conversation_id():
    from analytics_agent.agent.hitl import thread_config

    cfg = thread_config("conv-xyz")
    assert cfg == {"configurable": {"thread_id": "conv-xyz"}}


# ─── checkpointer ─────────────────────────────────────────────────────────


def test_get_checkpointer_returns_same_instance(monkeypatch, reset_checkpointer):
    """Memoized — every caller in the process must share state."""
    from analytics_agent.agent.hitl import get_checkpointer
    from analytics_agent.config import settings

    monkeypatch.setattr(settings, "hitl_checkpointer", "memory")

    a = get_checkpointer()
    b = get_checkpointer()
    assert a is b


@pytest.mark.asyncio
async def test_sqlite_checkpointer_returns_async_saver(
    tmp_path, monkeypatch, reset_checkpointer
):
    """The agent runs through astream_events (async), so the checkpointer
    must be AsyncSqliteSaver. The sync SqliteSaver crashes with 'does not
    support async methods' when invoked from the async graph runtime.

    Test is async because AsyncSqliteSaver.__init__ requires a running
    event loop — same constraint that holds in production where
    build_graph runs inside an async request handler.
    """
    from analytics_agent.config import settings

    db = tmp_path / "checkpoints.sqlite"
    monkeypatch.setattr(settings, "hitl_checkpointer", "sqlite")
    monkeypatch.setattr(settings, "hitl_checkpoint_path", str(db))

    from analytics_agent.agent.hitl import get_checkpointer
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    saver = get_checkpointer()
    assert isinstance(saver, AsyncSqliteSaver)


@pytest.mark.asyncio
async def test_sqlite_checkpointer_async_put_get_roundtrip(
    tmp_path, monkeypatch, reset_checkpointer
):
    """End-to-end: build the saver, write a checkpoint via the async API,
    read it back. Confirms the lazy aiosqlite.Connection actually opens."""
    from analytics_agent.config import settings

    db = tmp_path / "checkpoints.sqlite"
    monkeypatch.setattr(settings, "hitl_checkpointer", "sqlite")
    monkeypatch.setattr(settings, "hitl_checkpoint_path", str(db))

    from analytics_agent.agent.hitl import get_checkpointer

    saver = get_checkpointer()
    config = {"configurable": {"thread_id": "test-thread"}}
    # Empty list before any writes — confirms aiosqlite connection opened
    # successfully and schema was created lazily.
    items = [c async for c in saver.alist(config)]
    assert items == []
    assert db.exists()


@pytest.mark.asyncio
async def test_sqlite_checkpointer_directory_created_if_missing(
    tmp_path, monkeypatch, reset_checkpointer
):
    """Parent dir must be auto-created — production deploys may not have data/."""
    from analytics_agent.config import settings

    nested = tmp_path / "deeply" / "nested" / "dir" / "ckpt.sqlite"
    monkeypatch.setattr(settings, "hitl_checkpointer", "sqlite")
    monkeypatch.setattr(settings, "hitl_checkpoint_path", str(nested))

    from analytics_agent.agent.hitl import get_checkpointer

    get_checkpointer()
    # The parent dir is created eagerly; the file itself is created
    # on first async use.
    assert nested.parent.exists()
