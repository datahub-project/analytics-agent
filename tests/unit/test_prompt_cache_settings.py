"""
Tests for the prompt-caching feature added in PR #10:
  1. update_llm_settings persists enable_prompt_cache and mutates the singleton
  2. get_llm_settings reflects the singleton value
  3. _load_llm_config_from_db rehydrates both string ("false") and legacy bool (False) forms
  4. env var guard prevents DB from overriding ENABLE_PROMPT_CACHE when already set
  5. stream_graph_events USAGE event includes model and provider fields
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import orjson
import pytest
from analytics_agent.api.settings import (
    LlmSettingsResponse,
    UpdateLlmSettingsRequest,
    get_llm_settings,
    update_llm_settings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings_repo(stored_raw: str | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=stored_raw)
    repo.set = AsyncMock()
    return repo


def _mock_cfg(**kwargs) -> MagicMock:
    """Return a MagicMock pre-configured with sensible defaults for Settings."""
    m = MagicMock()
    m.llm_provider = "anthropic"
    m.llm_model = ""
    m.anthropic_api_key = ""
    m.aws_access_key_id = ""
    m.aws_secret_access_key = ""
    m.aws_region = ""
    m.enable_prompt_cache = True
    m.get_llm_model.return_value = ""
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# 1. update_llm_settings persists enable_prompt_cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_llm_settings_persists_prompt_cache_false() -> None:
    mock_repo = _make_settings_repo(stored_raw=None)
    session = AsyncMock()
    cfg = _mock_cfg()

    body = UpdateLlmSettingsRequest(provider="anthropic", enable_prompt_cache=False)

    with (
        patch("analytics_agent.api.settings.SettingsRepo", return_value=mock_repo),
        patch("analytics_agent.config.settings", cfg),
        patch.dict(os.environ, {}, clear=False),
    ):
        result = await update_llm_settings(body, session)
        env_value = os.environ.get("ENABLE_PROMPT_CACHE")

    assert result["success"] is True
    stored_json = orjson.loads(mock_repo.set.call_args[0][1])
    assert stored_json["enable_prompt_cache"] == "false"
    assert cfg.enable_prompt_cache is False
    assert env_value == "false"


@pytest.mark.asyncio
async def test_update_llm_settings_persists_prompt_cache_true() -> None:
    mock_repo = _make_settings_repo(stored_raw=None)
    session = AsyncMock()
    cfg = _mock_cfg(enable_prompt_cache=False)

    body = UpdateLlmSettingsRequest(provider="anthropic", enable_prompt_cache=True)

    with (
        patch("analytics_agent.api.settings.SettingsRepo", return_value=mock_repo),
        patch("analytics_agent.config.settings", cfg),
        patch.dict(os.environ, {}, clear=False),
    ):
        await update_llm_settings(body, session)
        env_value = os.environ.get("ENABLE_PROMPT_CACHE")

    stored_json = orjson.loads(mock_repo.set.call_args[0][1])
    assert stored_json["enable_prompt_cache"] == "true"
    assert cfg.enable_prompt_cache is True
    assert env_value == "true"


@pytest.mark.asyncio
async def test_update_llm_settings_merges_with_existing_config() -> None:
    """Existing DB fields are preserved when only enable_prompt_cache changes."""
    existing = orjson.dumps({"provider": "anthropic", "model": "claude-opus-4-5"}).decode()
    mock_repo = _make_settings_repo(stored_raw=existing)
    session = AsyncMock()
    cfg = _mock_cfg()

    body = UpdateLlmSettingsRequest(provider="anthropic", enable_prompt_cache=False)

    with (
        patch("analytics_agent.api.settings.SettingsRepo", return_value=mock_repo),
        patch("analytics_agent.config.settings", cfg),
        patch.dict(os.environ, {}, clear=False),
    ):
        await update_llm_settings(body, session)

    stored_json = orjson.loads(mock_repo.set.call_args[0][1])
    assert stored_json["model"] == "claude-opus-4-5"  # preserved
    assert stored_json["enable_prompt_cache"] == "false"  # updated


# ---------------------------------------------------------------------------
# 2. get_llm_settings reflects the singleton value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_llm_settings_returns_enable_prompt_cache_false() -> None:
    cfg = _mock_cfg(enable_prompt_cache=False)
    with patch("analytics_agent.config.settings", cfg):
        response: LlmSettingsResponse = await get_llm_settings()
    assert response.enable_prompt_cache is False


@pytest.mark.asyncio
async def test_get_llm_settings_returns_enable_prompt_cache_true() -> None:
    cfg = _mock_cfg(enable_prompt_cache=True)
    with patch("analytics_agent.config.settings", cfg):
        response: LlmSettingsResponse = await get_llm_settings()
    assert response.enable_prompt_cache is True


# ---------------------------------------------------------------------------
# 3 & 4. _load_llm_config_from_db rehydration
# ---------------------------------------------------------------------------


async def _run_load(cfg_data: dict) -> None:
    """Helper: run _load_llm_config_from_db with a mocked DB row.

    Does NOT wrap os.environ in patch.dict so env writes are observable by callers.
    Callers are responsible for cleaning up any env vars they set or that get written.
    """
    from analytics_agent.main import _load_llm_config_from_db

    raw_json = orjson.dumps(cfg_data).decode()
    mock_repo = _make_settings_repo(stored_raw=raw_json)

    # _get_session_factory() -> factory callable -> async context manager -> session
    mock_session = AsyncMock()
    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=session_ctx)

    with (
        patch("analytics_agent.db.base._get_session_factory", return_value=mock_factory),
        patch("analytics_agent.db.repository.SettingsRepo", return_value=mock_repo),
    ):
        await _load_llm_config_from_db()


@pytest.mark.asyncio
async def test_load_llm_config_rehydrates_prompt_cache_string_false() -> None:
    from analytics_agent.config import settings

    original = settings.enable_prompt_cache
    try:
        settings.enable_prompt_cache = True
        os.environ.pop("ENABLE_PROMPT_CACHE", None)
        await _run_load({"enable_prompt_cache": "false"})
        assert settings.enable_prompt_cache is False
        assert os.environ.get("ENABLE_PROMPT_CACHE") == "false"
    finally:
        settings.enable_prompt_cache = original
        os.environ.pop("ENABLE_PROMPT_CACHE", None)


@pytest.mark.asyncio
async def test_load_llm_config_rehydrates_prompt_cache_legacy_bool_false() -> None:
    """Legacy storage used Python bool False instead of the string "false"."""
    from analytics_agent.config import settings

    original = settings.enable_prompt_cache
    try:
        settings.enable_prompt_cache = True
        os.environ.pop("ENABLE_PROMPT_CACHE", None)
        await _run_load({"enable_prompt_cache": False})
        assert settings.enable_prompt_cache is False
        assert os.environ.get("ENABLE_PROMPT_CACHE") == "false"
    finally:
        settings.enable_prompt_cache = original
        os.environ.pop("ENABLE_PROMPT_CACHE", None)


@pytest.mark.asyncio
async def test_load_llm_config_rehydrates_prompt_cache_string_true() -> None:
    from analytics_agent.config import settings

    original = settings.enable_prompt_cache
    try:
        settings.enable_prompt_cache = False
        os.environ.pop("ENABLE_PROMPT_CACHE", None)
        await _run_load({"enable_prompt_cache": "true"})
        assert settings.enable_prompt_cache is True
        assert os.environ.get("ENABLE_PROMPT_CACHE") == "true"
    finally:
        settings.enable_prompt_cache = original
        os.environ.pop("ENABLE_PROMPT_CACHE", None)


@pytest.mark.asyncio
async def test_load_llm_config_env_var_guard_prevents_db_override() -> None:
    """When ENABLE_PROMPT_CACHE is already set in env, the DB value must not win."""
    from analytics_agent.config import settings

    original = settings.enable_prompt_cache
    try:
        settings.enable_prompt_cache = True
        os.environ["ENABLE_PROMPT_CACHE"] = "true"  # already set — DB must not override
        await _run_load({"enable_prompt_cache": "false"})
        assert settings.enable_prompt_cache is True
    finally:
        settings.enable_prompt_cache = original
        os.environ.pop("ENABLE_PROMPT_CACHE", None)


# ---------------------------------------------------------------------------
# 5. stream_graph_events USAGE event includes model and provider
# ---------------------------------------------------------------------------


async def _collect_events(ait: AsyncIterator[dict]) -> list[dict]:
    return [e async for e in ait]


@pytest.mark.asyncio
async def test_usage_event_includes_model_and_provider() -> None:
    from analytics_agent.agent.streaming import stream_graph_events

    mock_output = MagicMock()
    mock_output.usage_metadata = {
        "input_tokens": 100,
        "output_tokens": 40,
        "total_tokens": 140,
        "input_token_details": {"cache_read": 80, "cache_creation": 0},
    }
    mock_output.response_metadata = {"model_name": "claude-opus-4-5-20251101"}

    async def _fake_astream_events(*args, **kwargs):
        yield {
            "event": "on_chat_model_end",
            "data": {"output": mock_output},
            "name": "ChatAnthropic",
            "run_id": "run-abc",
            "metadata": {"langgraph_node": "agent"},
        }

    mock_graph = MagicMock()
    mock_graph.astream_events = _fake_astream_events
    cfg = _mock_cfg(llm_provider="anthropic")
    cfg.agent_recursion_limit = 10
    cfg.get_llm_model.return_value = "claude-opus-4-5-20251101"

    with patch("analytics_agent.config.settings", cfg):
        events = await _collect_events(
            stream_graph_events(mock_graph, "hello", "conv-1", "snowflake")
        )

    usage_events = [e for e in events if e["event"] == "USAGE"]
    assert len(usage_events) == 1
    payload = usage_events[0]["payload"]
    assert payload["model"] == "claude-opus-4-5-20251101"
    assert payload["provider"] == "anthropic"
    assert payload["cache_read_tokens"] == 80
    assert payload["input_tokens"] == 100
    assert payload["output_tokens"] == 40


@pytest.mark.asyncio
async def test_usage_event_falls_back_to_settings_model_when_metadata_absent() -> None:
    """When response_metadata has no model field, fall back to settings.get_llm_model()."""
    from analytics_agent.agent.streaming import stream_graph_events

    mock_output = MagicMock()
    mock_output.usage_metadata = {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "input_token_details": {},
    }
    mock_output.response_metadata = {}  # no model_name

    async def _fake_astream_events(*args, **kwargs):
        yield {
            "event": "on_chat_model_end",
            "data": {"output": mock_output},
            "name": "ChatAnthropic",
            "run_id": "run-xyz",
            "metadata": {"langgraph_node": "agent"},
        }

    mock_graph = MagicMock()
    mock_graph.astream_events = _fake_astream_events
    cfg = _mock_cfg(llm_provider="bedrock")
    cfg.agent_recursion_limit = 10
    cfg.get_llm_model.return_value = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    with patch("analytics_agent.config.settings", cfg):
        events = await _collect_events(stream_graph_events(mock_graph, "hi", "conv-2", "snowflake"))

    usage = next(e for e in events if e["event"] == "USAGE")
    assert usage["payload"]["model"] == "anthropic.claude-3-5-sonnet-20241022-v2:0"
    assert usage["payload"]["provider"] == "bedrock"
