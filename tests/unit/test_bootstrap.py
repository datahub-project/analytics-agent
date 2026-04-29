from pathlib import Path

import orjson
import pytest
from analytics_agent import bootstrap
from sqlalchemy import create_engine, inspect


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    """Point settings at a fresh sqlite file for the duration of the test."""
    db_path = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    # Force the settings singleton to pick up the new URL.
    from analytics_agent import config as _config

    monkeypatch.setattr(_config.settings, "database_url", url)
    # Reset the cached engine and session factory globals so they pick up the
    # new URL on next call. The names match db/base.py exactly.
    from analytics_agent.db import base as _base

    monkeypatch.setattr(_base, "_engine", None, raising=False)
    monkeypatch.setattr(_base, "_AsyncSessionFactory", None, raising=False)
    return db_path


def test_run_migrations_creates_tables(sqlite_db, monkeypatch):
    # Alembic must be invoked from the repo root where alembic.ini lives.
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repo_root)

    bootstrap.run_migrations()

    sync_url = f"sqlite:///{sqlite_db}"
    engine = create_engine(sync_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    assert "alembic_version" in tables
    assert "integrations" in tables
    assert "context_platforms" in tables
    assert "settings" in tables


@pytest.mark.asyncio
async def test_seed_integrations_idempotent(sqlite_db, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repo_root)
    bootstrap.run_migrations()

    # Stub out load_engines_config to return a single yaml engine.
    from analytics_agent import config as _config

    fake_cfg = _config.EngineConfig(
        type="snowflake",
        name="test_sf",
        connection={"account": "x", "user": "y"},
    )
    monkeypatch.setattr(
        _config.Settings,
        "load_engines_config",
        lambda self: [fake_cfg],
    )

    await bootstrap.seed_integrations_from_yaml()
    await bootstrap.seed_integrations_from_yaml()  # second run must be a no-op

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import IntegrationRepo

    factory = _get_session_factory()
    async with factory() as session:
        rows = await IntegrationRepo(session).list_all()

    assert len(rows) == 1
    assert rows[0].name == "test_sf"
    assert rows[0].source == "yaml"
    assert orjson.loads(rows[0].config) == {"account": "x", "user": "y"}


@pytest.mark.asyncio
async def test_seed_integrations_removes_stale_yaml(sqlite_db, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repo_root)
    bootstrap.run_migrations()

    from analytics_agent import config as _config

    cfg_a = _config.EngineConfig(type="snowflake", name="a", connection={})
    cfg_b = _config.EngineConfig(type="snowflake", name="b", connection={})

    monkeypatch.setattr(_config.Settings, "load_engines_config", lambda self: [cfg_a, cfg_b])
    await bootstrap.seed_integrations_from_yaml()

    monkeypatch.setattr(_config.Settings, "load_engines_config", lambda self: [cfg_a])
    await bootstrap.seed_integrations_from_yaml()

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import IntegrationRepo

    factory = _get_session_factory()
    async with factory() as session:
        rows = await IntegrationRepo(session).list_all()

    names = {r.name for r in rows}
    assert names == {"a"}


@pytest.mark.asyncio
async def test_seed_integrations_skips_ui_managed(sqlite_db, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repo_root)
    bootstrap.run_migrations()

    from analytics_agent import config as _config

    cfg = _config.EngineConfig(type="snowflake", name="x", connection={"v": "yaml"})
    monkeypatch.setattr(_config.Settings, "load_engines_config", lambda self: [cfg])

    await bootstrap.seed_integrations_from_yaml()

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import IntegrationRepo

    factory = _get_session_factory()
    async with factory() as session:
        repo = IntegrationRepo(session)
        row = await repo.get("x")
        row.source = "ui"
        row.config = orjson.dumps({"v": "ui-edited"}).decode()
        await session.commit()

    await bootstrap.seed_integrations_from_yaml()  # must not overwrite ui edits

    async with factory() as session:
        row = await IntegrationRepo(session).get("x")
        assert row.source == "ui"
        assert orjson.loads(row.config) == {"v": "ui-edited"}


@pytest.mark.asyncio
async def test_seed_context_platforms_idempotent(sqlite_db, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repo_root)
    bootstrap.run_migrations()

    from analytics_agent import config as _config

    fake = _config.DataHubPlatformConfig(
        type="datahub",
        name="default",
        label="DataHub",
        url="http://gms",
        token="t",
    )
    # Pydantic BaseSettings rejects instance attribute assignment, so patch
    # on the class. (The Task 4 implementer hit the same issue.)
    monkeypatch.setattr(
        _config.Settings,
        "load_context_platforms_config",
        lambda self: [fake],
    )

    await bootstrap.seed_context_platforms_from_yaml()
    await bootstrap.seed_context_platforms_from_yaml()

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import ContextPlatformRepo

    factory = _get_session_factory()
    async with factory() as session:
        rows = await ContextPlatformRepo(session).list_all()

    assert len(rows) == 1
    assert rows[0].name == "default"
    assert rows[0].source == "yaml"


@pytest.mark.asyncio
async def test_seed_context_platforms_removes_stale(sqlite_db, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repo_root)
    bootstrap.run_migrations()

    from analytics_agent import config as _config

    a = _config.DataHubPlatformConfig(type="datahub", name="a", url="http://a", token="t")
    b = _config.DataHubPlatformConfig(type="datahub", name="b", url="http://b", token="t")

    monkeypatch.setattr(
        _config.Settings,
        "load_context_platforms_config",
        lambda self: [a, b],
    )
    await bootstrap.seed_context_platforms_from_yaml()

    monkeypatch.setattr(
        _config.Settings,
        "load_context_platforms_config",
        lambda self: [a],
    )
    await bootstrap.seed_context_platforms_from_yaml()

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import ContextPlatformRepo

    factory = _get_session_factory()
    async with factory() as session:
        rows = await ContextPlatformRepo(session).list_all()
    assert {r.name for r in rows} == {"a"}


@pytest.mark.asyncio
async def test_seed_default_settings_writes_first_run_defaults(sqlite_db, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repo_root)
    bootstrap.run_migrations()

    await bootstrap.seed_default_settings()

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import SettingsRepo

    factory = _get_session_factory()
    async with factory() as session:
        raw = await SettingsRepo(session).get("enabled_mutation_tools")

    assert orjson.loads(raw) == ["publish_analysis", "save_correction"]


@pytest.mark.asyncio
async def test_seed_default_settings_does_not_overwrite(sqlite_db, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repo_root)
    bootstrap.run_migrations()

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import SettingsRepo

    factory = _get_session_factory()
    async with factory() as session:
        await SettingsRepo(session).set("enabled_mutation_tools", orjson.dumps(["custom"]).decode())

    await bootstrap.seed_default_settings()

    async with factory() as session:
        raw = await SettingsRepo(session).get("enabled_mutation_tools")
    assert orjson.loads(raw) == ["custom"]
