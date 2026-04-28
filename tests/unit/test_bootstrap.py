from pathlib import Path

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
