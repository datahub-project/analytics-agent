"""Unit tests for analytics_agent.telemetry.

Covers opt-out behavior, client_id resolution, the attribute allowlist
(PII guard), and that no Mixpanel calls are made when disabled.
No network access — Mixpanel is always mocked or disabled.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fresh_client():
    """Return a new TelemetryClient (not the module singleton)."""
    from analytics_agent.telemetry import TelemetryClient

    return TelemetryClient()


# ── Opt-out: CI environment ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ci_env_var_disables_telemetry(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("DATAHUB_TELEMETRY_ENABLED", "true")

    client = _fresh_client()
    await client.initialize(None)

    assert not client.enabled


@pytest.mark.asyncio
async def test_generic_ci_var_disables_telemetry(monkeypatch):
    monkeypatch.setenv("CI", "true")

    client = _fresh_client()
    await client.initialize(None)

    assert not client.enabled


# ── Opt-out: DATAHUB_TELEMETRY_ENABLED env var ────────────────────────────────

@pytest.mark.asyncio
async def test_env_var_false_disables_telemetry(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    client = _fresh_client()
    with patch.object(client, "_is_ci", return_value=False):
        with patch("analytics_agent.config.settings") as mock_settings:
            mock_settings.datahub_telemetry_enabled = False
            await client.initialize(None)

    assert not client.enabled


# ── Opt-out: ~/.datahub/telemetry-config.json ────────────────────────────────

@pytest.mark.asyncio
async def test_cli_config_opt_out_respected(monkeypatch, tmp_path):
    cfg_file = tmp_path / "telemetry-config.json"
    cfg_file.write_text(json.dumps({"client_id": "abc-123", "enabled": False}))

    monkeypatch.setattr("analytics_agent.telemetry._CLI_CONFIG_FILE", cfg_file)

    client = _fresh_client()
    with patch.object(client, "_is_ci", return_value=False):
        with patch("analytics_agent.config.settings") as mock_settings:
            mock_settings.datahub_telemetry_enabled = True
            await client.initialize(None)

    assert not client.enabled


# ── Client ID: reuse from CLI config ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_cli_client_id_is_reused(monkeypatch, tmp_path):
    expected_id = "deadbeef-0000-0000-0000-000000000001"
    cfg_file = tmp_path / "telemetry-config.json"
    cfg_file.write_text(json.dumps({"client_id": expected_id, "enabled": True}))

    monkeypatch.setattr("analytics_agent.telemetry._CLI_CONFIG_FILE", cfg_file)

    client = _fresh_client()
    with patch.object(client, "_is_ci", return_value=False):
        with patch("analytics_agent.config.settings") as mock_settings:
            mock_settings.datahub_telemetry_enabled = True
            with patch("mixpanel.Mixpanel"), patch("mixpanel.Consumer"):
                await client.initialize(None)

    assert client.client_id == expected_id
    assert client.enabled


# ── Client ID: DB fallback when no CLI config ────────────────────────────────

@pytest.mark.asyncio
async def test_db_fallback_stores_and_returns_client_id(monkeypatch, tmp_path):
    # Point CLI config to a non-existent path so fallback triggers
    monkeypatch.setattr(
        "analytics_agent.telemetry._CLI_CONFIG_FILE", tmp_path / "nonexistent.json"
    )

    stored: dict[str, str] = {}

    mock_repo = MagicMock()
    mock_repo.get = AsyncMock(side_effect=lambda key: stored.get(key))

    async def mock_set(key, value):
        stored[key] = value

    mock_repo.set = mock_set

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_session)

    client = _fresh_client()
    with patch.object(client, "_is_ci", return_value=False):
        with patch("analytics_agent.config.settings") as mock_settings:
            mock_settings.datahub_telemetry_enabled = True
            # SettingsRepo is imported lazily inside _resolve_db_client_id;
            # patch at the source module so the local import picks it up.
            with patch(
                "analytics_agent.db.repository.SettingsRepo", return_value=mock_repo
            ):
                with patch("mixpanel.Mixpanel"), patch("mixpanel.Consumer"):
                    await client.initialize(mock_factory)

    assert client.enabled
    assert "telemetry_client_id" in stored
    uuid.UUID(stored["telemetry_client_id"])  # must be a valid UUID
    assert client.client_id == stored["telemetry_client_id"]


# ── MixpanelSpanProcessor: attribute allowlist (PII guard) ───────────────────

def test_span_processor_drops_unknown_spans():
    """Spans not in KNOWN_SPAN_NAMES must never reach track_sync."""
    from analytics_agent.telemetry import MixpanelSpanProcessor, TelemetryClient

    client = TelemetryClient()
    client.enabled = True
    processor = MixpanelSpanProcessor(client)

    mock_span = MagicMock()
    mock_span.name = "http.request"
    mock_span.attributes = {"http.method": "GET", "http.url": "/api/chat"}

    with patch.object(client, "track_sync") as mock_track:
        processor.on_end(mock_span)
        processor._executor.shutdown(wait=True)
        mock_track.assert_not_called()


def test_span_processor_strips_non_allowlisted_attributes():
    """Only attributes in _ATTRIBUTE_ALLOWLIST survive for each span type."""
    from analytics_agent.telemetry import MixpanelSpanProcessor, TelemetryClient

    client = TelemetryClient()
    client.enabled = True
    processor = MixpanelSpanProcessor(client)

    mock_span = MagicMock()
    mock_span.name = "query.completed"
    mock_span.attributes = {
        "engine.type": "snowflake",
        "row.count": 42,
        "sql": "SELECT * FROM users",        # banned
        "schema": "production",              # banned
        "conversation_id": "conv-abc-123",   # banned
    }

    captured: list[tuple] = []

    with patch.object(client, "track_sync", side_effect=lambda n, p: captured.append((n, p))):
        processor.on_end(mock_span)
        processor._executor.shutdown(wait=True)

    assert len(captured) == 1
    event_name, props = captured[0]
    assert event_name == "query.completed"
    assert props == {"engine.type": "snowflake", "row.count": 42}
    assert "sql" not in props
    assert "schema" not in props
    assert "conversation_id" not in props


def test_span_processor_no_calls_when_disabled():
    """No track_sync calls when client.enabled is False."""
    from analytics_agent.telemetry import MixpanelSpanProcessor, TelemetryClient

    client = TelemetryClient()
    client.enabled = False
    processor = MixpanelSpanProcessor(client)

    mock_span = MagicMock()
    mock_span.name = "query.completed"
    mock_span.attributes = {"engine.type": "snowflake", "row.count": 5}

    with patch.object(client, "track_sync") as mock_track:
        processor.on_end(mock_span)
        processor._executor.shutdown(wait=True)
        mock_track.assert_not_called()


def test_pii_guard_all_event_types():
    """No PII/query fields can appear in any event payload regardless of span name."""
    from concurrent.futures import ThreadPoolExecutor

    from analytics_agent.telemetry import (
        KNOWN_SPAN_NAMES,
        MixpanelSpanProcessor,
        TelemetryClient,
    )

    BANNED_KEYS = {
        "sql", "query", "schema", "database", "user", "username",
        "conversation_id", "message_id", "text", "prompt", "error",
    }

    client = TelemetryClient()
    client.enabled = True
    processor = MixpanelSpanProcessor(client)

    for span_name in KNOWN_SPAN_NAMES:
        mock_span = MagicMock()
        mock_span.name = span_name
        mock_span.attributes = {k: "SENSITIVE" for k in BANNED_KEYS}
        mock_span.attributes["engine.type"] = "snowflake"

        captured: list[dict] = []
        with patch.object(client, "track_sync", side_effect=lambda _n, p: captured.append(p)):
            processor.on_end(mock_span)
            processor._executor.shutdown(wait=True)

        processor._executor = ThreadPoolExecutor(max_workers=1)

        for props in captured:
            for key in props:
                assert key.lower() not in BANNED_KEYS, (
                    f"PII/banned field '{key}' found in {span_name} payload: {props}"
                )


# ── _read_cli_config: handles malformed file gracefully ──────────────────────

def test_read_cli_config_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "analytics_agent.telemetry._CLI_CONFIG_FILE", tmp_path / "missing.json"
    )
    client = _fresh_client()
    client_id, enabled = client._read_cli_config()
    assert client_id is None
    assert enabled is None


def test_read_cli_config_malformed_json(tmp_path, monkeypatch):
    bad = tmp_path / "telemetry-config.json"
    bad.write_text("not valid json{{")
    monkeypatch.setattr("analytics_agent.telemetry._CLI_CONFIG_FILE", bad)

    client = _fresh_client()
    client_id, enabled = client._read_cli_config()
    assert client_id is None
    assert enabled is None
