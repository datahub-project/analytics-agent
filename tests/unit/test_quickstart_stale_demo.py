"""
Tests for self-healing recovery when `quickstart` runs against a stale demo
DATABASE_URL left in ~/.datahub/analytics-agent/.env by a previous `demo` run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from analytics_agent.quickstart import _is_stale_demo_db_failure, _strip_env_vars

# ── _is_stale_demo_db_failure ────────────────────────────────────────────────

_DEMO_URL_MAC = "mysql+aiomysql://datahub:datahub@host.docker.internal:3306/talkster"
_DEMO_URL_LINUX = "mysql+aiomysql://datahub:datahub@172.17.0.1:3306/talkster"
_CONNECT_ERR_MAC = "OperationalError: (pymysql.err.OperationalError) (2003, \"Can't connect to MySQL server on 'host.docker.internal'\")"
_CONNECT_ERR_DNS = "socket.gaierror: [Errno 8] nodename nor servname provided, or not known"


@pytest.mark.parametrize("url", [_DEMO_URL_MAC, _DEMO_URL_LINUX])
def test_stale_demo_detected_on_mac_and_linux(url):
    assert _is_stale_demo_db_failure(url, _CONNECT_ERR_MAC)
    assert _is_stale_demo_db_failure(url, _CONNECT_ERR_DNS)


def test_non_demo_mysql_not_treated_as_stale():
    """A user-supplied MySQL URL must NOT trigger auto-cleanup, even on connect failure."""
    user_url = "mysql+aiomysql://prod_user:secret@my-db.example.com:3306/analytics"
    assert not _is_stale_demo_db_failure(user_url, _CONNECT_ERR_MAC)


def test_demo_url_but_unrelated_stderr():
    """Random stderr (e.g. migration syntax error) must not falsely trigger recovery."""
    assert not _is_stale_demo_db_failure(
        _DEMO_URL_MAC, "alembic.util.exc.CommandError: Can't locate revision"
    )


def test_empty_db_url():
    assert not _is_stale_demo_db_failure("", _CONNECT_ERR_MAC)


def test_sqlite_url_is_not_stale():
    assert not _is_stale_demo_db_failure("sqlite+aiosqlite:///x.db", _CONNECT_ERR_MAC)


# ── _strip_env_vars ──────────────────────────────────────────────────────────


def test_strip_env_vars_removes_only_named_keys(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ANTHROPIC_API_KEY=sk-ant-xxx\n"
        "DATABASE_URL=mysql+aiomysql://datahub:datahub@host.docker.internal:3306/talkster\n"
        "# A comment line\n"
        "DATAHUB_GMS_URL=http://localhost:8080\n"
        "\n"
        "LLM_PROVIDER=anthropic\n"
    )
    _strip_env_vars(env_file, {"DATABASE_URL"})
    remaining = env_file.read_text()
    assert "DATABASE_URL" not in remaining
    assert "ANTHROPIC_API_KEY=sk-ant-xxx" in remaining
    assert "DATAHUB_GMS_URL=http://localhost:8080" in remaining
    assert "# A comment line" in remaining
    assert "LLM_PROVIDER=anthropic" in remaining


def test_strip_env_vars_multiple_keys(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\nB=2\nC=3\n")
    _strip_env_vars(env_file, {"A", "C"})
    assert env_file.read_text() == "B=2\n"


def test_strip_env_vars_missing_file_is_noop(tmp_path: Path):
    """Should not raise when the file doesn't exist."""
    _strip_env_vars(tmp_path / "nonexistent.env", {"X"})


def test_strip_env_vars_key_not_present(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\nB=2\n")
    _strip_env_vars(env_file, {"DOES_NOT_EXIST"})
    assert env_file.read_text() == "A=1\nB=2\n"
