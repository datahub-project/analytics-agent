"""
Tests for connection-pool wiring in db.base._get_engine (PR #72).

Verifies the branch that gates pool kwargs on engine type:
  - SQLite engines must NOT receive pool_size/pre_ping/etc. (the default
    SQLite pool rejects those args), and keep check_same_thread=False.
  - MySQL / PostgreSQL engines must receive the five configured pool knobs.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import analytics_agent.db.base as db_base

_POOL_KWARGS = {
    "pool_size",
    "max_overflow",
    "pool_recycle",
    "pool_pre_ping",
    "pool_timeout",
}


def _fake_settings(database_url: str, command_timeout: int = 30) -> SimpleNamespace:
    return SimpleNamespace(
        database_url=database_url,
        log_level="INFO",
        db_pool_size=10,
        db_max_overflow=20,
        db_pool_recycle=1800,
        db_pool_pre_ping=True,
        db_pool_timeout=10,
        db_command_timeout=command_timeout,
    )


def _call_get_engine(database_url: str, command_timeout: int = 30):
    """Reset the module singletons and capture the create_async_engine call."""
    with (
        patch.object(db_base, "_engine", None),
        patch.object(db_base, "_AsyncSessionFactory", None),
        patch.object(db_base, "settings", _fake_settings(database_url, command_timeout)),
        patch.object(db_base, "create_async_engine", MagicMock()) as mock_create,
        patch.object(db_base, "async_sessionmaker", MagicMock()),
    ):
        db_base._get_engine()
    assert mock_create.call_count == 1
    return mock_create.call_args


def test_sqlite_engine_omits_pool_kwargs():
    args, kwargs = _call_get_engine("sqlite+aiosqlite:///./data/dev.db")
    assert _POOL_KWARGS.isdisjoint(kwargs)
    assert kwargs["connect_args"] == {"check_same_thread": False}


def test_postgres_engine_applies_pool_kwargs_and_command_timeout():
    args, kwargs = _call_get_engine("postgresql+asyncpg://u:p@host/db")
    assert kwargs["pool_size"] == 10
    assert kwargs["max_overflow"] == 20
    assert kwargs["pool_recycle"] == 1800
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_timeout"] == 10
    # asyncpg gets a per-statement timeout so a wedged pre-ping fails fast.
    assert kwargs["connect_args"] == {"command_timeout": 30}


def test_postgres_command_timeout_disabled_when_zero():
    args, kwargs = _call_get_engine("postgresql+asyncpg://u:p@host/db", command_timeout=0)
    assert kwargs["connect_args"] == {}
    assert _POOL_KWARGS.issubset(kwargs)


def test_mysql_engine_applies_pool_kwargs_without_command_timeout():
    """command_timeout is asyncpg-specific; MySQL must not receive it."""
    args, kwargs = _call_get_engine("mysql+asyncmy://u:p@host/db")
    assert _POOL_KWARGS.issubset(kwargs)
    assert kwargs["connect_args"] == {}
