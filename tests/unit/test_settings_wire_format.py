"""
Tests for the secrets-to-credentials Step 1 wire format:
  - PUT /connections/{name} with {config, secrets}
  - PUT /connections/{name} with legacy {fields}
  - POST /connections with {config, secrets}
  - _upsert_env_vars round-trips for tricky values
"""

from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import orjson
import pytest
from analytics_agent.api.settings import (
    CreateConnectionRequest,
    UpdateConnectionRequest,
    _resolve_secrets,
    _upsert_env_vars,
    create_connection,
    update_connection,
)
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# _upsert_env_vars round-trip tests
# ---------------------------------------------------------------------------


def _read_env(p: pathlib.Path) -> dict[str, str]:
    """Parse a .env file into a plain dict, handling multiline double-quoted values."""
    import re

    result: dict[str, str] = {}
    content = p.read_text()
    # Match KEY="..." (possibly multiline) or KEY=bare-value
    for m in re.finditer(
        r'^([A-Za-z_][A-Za-z0-9_]*)=((?:"(?:\\.|[^"\\])*")|(?:[^\n]*))',
        content,
        re.MULTILINE | re.DOTALL,
    ):
        k = m.group(1)
        v = m.group(2)
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        result[k] = v
    return result


def test_upsert_simple_value(tmp_path: pathlib.Path) -> None:
    env = tmp_path / ".env"
    _upsert_env_vars(env, {"FOO": "bar"})
    assert _read_env(env)["FOO"] == "bar"


def test_upsert_always_quotes(tmp_path: pathlib.Path) -> None:
    env = tmp_path / ".env"
    _upsert_env_vars(env, {"PLAIN": "simple"})
    raw = env.read_text()
    assert 'PLAIN="simple"' in raw


def test_upsert_roundtrip_pem(tmp_path: pathlib.Path) -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\naGVsbG8K\n-----END RSA PRIVATE KEY-----"
    env = tmp_path / ".env"
    _upsert_env_vars(env, {"SNOWFLAKE_PRIVATE_KEY": pem})
    assert _read_env(env)["SNOWFLAKE_PRIVATE_KEY"] == pem


def test_upsert_roundtrip_hash(tmp_path: pathlib.Path) -> None:
    value = "pass#word"
    env = tmp_path / ".env"
    _upsert_env_vars(env, {"SNOWFLAKE_PASSWORD": value})
    assert _read_env(env)["SNOWFLAKE_PASSWORD"] == value


def test_upsert_roundtrip_backslash(tmp_path: pathlib.Path) -> None:
    value = r"C:\Users\me\key.p8"
    env = tmp_path / ".env"
    _upsert_env_vars(env, {"KEY_PATH": value})
    assert _read_env(env)["KEY_PATH"] == value


def test_upsert_roundtrip_embedded_quote(tmp_path: pathlib.Path) -> None:
    value = 'say "hello"'
    env = tmp_path / ".env"
    _upsert_env_vars(env, {"GREETING": value})
    assert _read_env(env)["GREETING"] == value


def test_upsert_roundtrip_leading_trailing_whitespace(tmp_path: pathlib.Path) -> None:
    value = "  spaced  "
    env = tmp_path / ".env"
    _upsert_env_vars(env, {"PADDED": value})
    assert _read_env(env)["PADDED"] == value


def test_upsert_updates_existing_entry(tmp_path: pathlib.Path) -> None:
    env = tmp_path / ".env"
    env.write_text('FOO="old"\n')
    _upsert_env_vars(env, {"FOO": "new"})
    lines = [line for line in env.read_text().splitlines() if line.startswith("FOO=")]
    assert len(lines) == 1
    assert _read_env(env)["FOO"] == "new"


def test_upsert_updates_multiline_existing(tmp_path: pathlib.Path) -> None:
    pem_old = "-----BEGIN RSA PRIVATE KEY-----\noldkey\n-----END RSA PRIVATE KEY-----"
    pem_new = "-----BEGIN RSA PRIVATE KEY-----\nnewkey\n-----END RSA PRIVATE KEY-----"
    env = tmp_path / ".env"
    _upsert_env_vars(env, {"SNOWFLAKE_PRIVATE_KEY": pem_old})
    _upsert_env_vars(env, {"SNOWFLAKE_PRIVATE_KEY": pem_new})
    assert _read_env(env)["SNOWFLAKE_PRIVATE_KEY"] == pem_new


# ---------------------------------------------------------------------------
# _resolve_secrets (uses QueryEngine.secret_env_vars)
# ---------------------------------------------------------------------------


def test_resolve_secrets_snowflake_password() -> None:
    result = _resolve_secrets("snowflake", {"password": "s3cr3t"})
    assert result == {"SNOWFLAKE_PASSWORD": "s3cr3t"}


def test_resolve_secrets_snowflake_private_key() -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"
    result = _resolve_secrets("snowflake", {"private_key": pem})
    assert result == {"SNOWFLAKE_PRIVATE_KEY": pem}


def test_resolve_secrets_unknown_key_raises_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _resolve_secrets("snowflake", {"bad_key": "value"})
    assert exc_info.value.status_code == 400
    assert "bad_key" in exc_info.value.detail


def test_resolve_secrets_unknown_engine_unknown_key_raises_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _resolve_secrets("duckdb", {"password": "x"})
    assert exc_info.value.status_code == 400


def test_resolve_secrets_skips_masked_values() -> None:
    result = _resolve_secrets("snowflake", {"password": "•••••"})
    assert result == {}


# ---------------------------------------------------------------------------
# Integration-style tests via endpoint helpers
# ---------------------------------------------------------------------------


def _make_integration(name: str = "myconn", intg_type: str = "snowflake") -> MagicMock:
    intg = MagicMock()
    intg.name = name
    intg.type = intg_type
    intg.source = "ui"
    intg.config = orjson.dumps({"account": "myorg-myacct", "warehouse": "WH"}).decode()
    intg.updated_at = None
    return intg


# --- PUT with {config, secrets} (engine) ---


@pytest.mark.asyncio
async def test_put_config_and_secrets_writes_to_db_and_env(tmp_path: pathlib.Path) -> None:
    intg = _make_integration()
    session = AsyncMock()
    session.commit = AsyncMock()
    env_file = tmp_path / ".env"

    mock_cp_repo = AsyncMock()
    mock_cp_repo.get = AsyncMock(return_value=None)

    mock_intg_repo = AsyncMock()
    mock_intg_repo.get = AsyncMock(return_value=intg)

    body = UpdateConnectionRequest(
        config={"warehouse": "NEW_WH", "role": "ANALYST"},
        secrets={"password": "supersecret"},
    )

    with (
        patch("analytics_agent.api.settings.ContextPlatformRepo", return_value=mock_cp_repo),
        patch("analytics_agent.db.repository.IntegrationRepo", return_value=mock_intg_repo),
        patch("analytics_agent.engines.factory.register_engine"),
        patch("analytics_agent.api.settings._find_env_file", return_value=env_file),
        patch.dict("analytics_agent.api.settings.os.environ", {}, clear=False),
    ):
        result = await update_connection("myconn", body, session)

    assert result["success"] is True
    saved_cfg = orjson.loads(intg.config)
    assert saved_cfg["warehouse"] == "NEW_WH"
    assert saved_cfg["role"] == "ANALYST"
    env_vars = _read_env(env_file)
    assert env_vars["SNOWFLAKE_PASSWORD"] == "supersecret"


@pytest.mark.asyncio
async def test_put_config_only_no_env_file_touched(tmp_path: pathlib.Path) -> None:
    """A config-only save must NOT create/modify .env."""
    intg = _make_integration()
    session = AsyncMock()
    session.commit = AsyncMock()
    env_file = tmp_path / ".env"

    mock_cp_repo = AsyncMock()
    mock_cp_repo.get = AsyncMock(return_value=None)
    mock_intg_repo = AsyncMock()
    mock_intg_repo.get = AsyncMock(return_value=intg)

    body = UpdateConnectionRequest(config={"warehouse": "ONLY_CFG"}, secrets={})

    with (
        patch("analytics_agent.api.settings.ContextPlatformRepo", return_value=mock_cp_repo),
        patch("analytics_agent.db.repository.IntegrationRepo", return_value=mock_intg_repo),
        patch("analytics_agent.engines.factory.register_engine"),
        patch("analytics_agent.api.settings._find_env_file", return_value=env_file),
        patch.dict("analytics_agent.api.settings.os.environ", {}, clear=False),
    ):
        await update_connection("myconn", body, session)

    assert orjson.loads(intg.config)["warehouse"] == "ONLY_CFG"
    assert not env_file.exists()


# --- PUT for context platform uses body.config ---


@pytest.mark.asyncio
async def test_put_context_platform_uses_body_config(tmp_path: pathlib.Path) -> None:
    """DataHub (non-MCP) PUT: body.config keys merge into cp.config JSON."""
    cp = MagicMock()
    cp.type = "datahub"
    cp.config = orjson.dumps(
        {"type": "datahub", "name": "default", "url": "", "token": ""}
    ).decode()
    cp.updated_at = None

    session = AsyncMock()
    session.commit = AsyncMock()

    mock_cp_repo = AsyncMock()
    mock_cp_repo.get = AsyncMock(return_value=cp)

    body = UpdateConnectionRequest(
        config={"url": "https://dh.example.com/gms", "token": "newtok"},
        secrets={},
    )

    with (
        patch("analytics_agent.api.settings.ContextPlatformRepo", return_value=mock_cp_repo),
        patch.dict("analytics_agent.api.settings.os.environ", {}, clear=False),
    ):
        result = await update_connection("default", body, session)

    assert result["success"] is True
    saved = orjson.loads(cp.config)
    assert saved["url"] == "https://dh.example.com/gms"
    assert saved["token"] == "newtok"


# --- Unknown secret key → HTTP 400 ---


@pytest.mark.asyncio
async def test_put_unknown_secret_key_raises_400(tmp_path: pathlib.Path) -> None:
    intg = _make_integration()
    session = AsyncMock()
    session.commit = AsyncMock()

    mock_cp_repo = AsyncMock()
    mock_cp_repo.get = AsyncMock(return_value=None)
    mock_intg_repo = AsyncMock()
    mock_intg_repo.get = AsyncMock(return_value=intg)

    body = UpdateConnectionRequest(config={}, secrets={"totally_fake_key": "x"})

    with (
        patch("analytics_agent.api.settings.ContextPlatformRepo", return_value=mock_cp_repo),
        patch("analytics_agent.db.repository.IntegrationRepo", return_value=mock_intg_repo),
        pytest.raises(HTTPException) as exc_info,
    ):
        await update_connection("myconn", body, session)
    assert exc_info.value.status_code == 400
    assert "totally_fake_key" in exc_info.value.detail


# --- POST with {config, secrets} ---


@pytest.mark.asyncio
async def test_post_config_and_secrets(tmp_path: pathlib.Path) -> None:
    session = AsyncMock()
    session.commit = AsyncMock()
    env_file = tmp_path / ".env"

    persisted_config: dict = {}

    mock_cp_repo = AsyncMock()
    mock_cp_repo.get = AsyncMock(return_value=None)

    async def _fake_upsert(**kwargs: object) -> None:
        persisted_config.update(orjson.loads(kwargs["config"]))  # type: ignore[arg-type]

    mock_intg_repo = AsyncMock()
    mock_intg_repo.get = AsyncMock(return_value=None)
    mock_intg_repo.upsert = _fake_upsert

    body = CreateConnectionRequest(
        name="newconn",
        type="snowflake",
        config={"account": "myorg-myacct", "warehouse": "WH", "user": "BOB"},
        secrets={"password": "postpwd"},
    )

    with (
        patch("analytics_agent.db.repository.ContextPlatformRepo", return_value=mock_cp_repo),
        patch("analytics_agent.db.repository.IntegrationRepo", return_value=mock_intg_repo),
        patch("analytics_agent.engines.factory.register_engine"),
        patch("analytics_agent.api.settings._find_env_file", return_value=env_file),
        patch.dict("analytics_agent.api.settings.os.environ", {}, clear=False),
    ):
        result = await create_connection(body, session)

    assert result["success"] is True
    assert persisted_config.get("account") == "myorg-myacct"
    env_vars = _read_env(env_file)
    assert env_vars["SNOWFLAKE_PASSWORD"] == "postpwd"
