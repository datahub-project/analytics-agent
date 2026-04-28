from pathlib import Path

import orjson
import pytest
from analytics_agent.cli import cli
from click.testing import CliRunner
from sqlalchemy import create_engine, inspect


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from analytics_agent import config as _config

    monkeypatch.setattr(_config.settings, "database_url", url)
    from analytics_agent.db import base as _base

    monkeypatch.setattr(_base, "_engine", None, raising=False)
    monkeypatch.setattr(_base, "_AsyncSessionFactory", None, raising=False)
    return db_path


def _chdir_repo_root(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[2])


def test_cli_migrate_creates_schema(sqlite_db, monkeypatch):
    _chdir_repo_root(monkeypatch)
    result = CliRunner().invoke(cli, ["migrate"])
    assert result.exit_code == 0, result.output

    engine = create_engine(f"sqlite:///{sqlite_db}")
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert {"alembic_version", "integrations", "context_platforms", "settings"} <= tables


def test_cli_bootstrap_runs_all_steps_idempotent(sqlite_db, monkeypatch):
    _chdir_repo_root(monkeypatch)

    from analytics_agent import config as _config

    # Pydantic BaseSettings — patch on the class.
    monkeypatch.setattr(_config.Settings, "load_engines_config", lambda self: [])
    monkeypatch.setattr(
        _config.Settings, "load_context_platforms_config", lambda self: []
    )

    runner = CliRunner()
    result1 = runner.invoke(cli, ["bootstrap"])
    assert result1.exit_code == 0, result1.output
    result2 = runner.invoke(cli, ["bootstrap"])
    assert result2.exit_code == 0, result2.output

    # Default settings should have been written
    import asyncio

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import SettingsRepo

    async def _read():
        factory = _get_session_factory()
        async with factory() as session:
            return await SettingsRepo(session).get("enabled_mutation_tools")

    raw = asyncio.run(_read())
    assert orjson.loads(raw) == ["publish_analysis", "save_correction"]


def test_cli_bootstrap_fails_fast_on_migration_error(monkeypatch, tmp_path):
    """If migrate fails, the umbrella command must exit non-zero."""
    _chdir_repo_root(monkeypatch)
    # Point at an unwritable directory to break sqlite mkdir
    bad_url = "sqlite+aiosqlite:////this/path/does/not/exist/test.db"
    monkeypatch.setenv("DATABASE_URL", bad_url)
    from analytics_agent import config as _config

    monkeypatch.setattr(_config.settings, "database_url", bad_url)

    result = CliRunner().invoke(cli, ["bootstrap"], catch_exceptions=True)
    assert result.exit_code != 0
