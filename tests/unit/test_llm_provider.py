"""
Tests for the LLM provider registry introduced in config.py and agent/llm.py.

Covers:
- PROVIDER_DEFAULTS structure (all providers × all tiers)
- PROVIDER_KEY_ENV / PROVIDER_KEY_ATTR consistency
- Settings model-tier methods (get_llm_model etc.) + env-var overrides
- Settings.get_api_key() returns the right attribute per provider
- agent/llm._make_llm() dispatches to the correct factory
- agent/llm._make_llm() raises a clear error for unknown providers
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from analytics_agent.agent.llm import _FACTORIES, _make_llm
from analytics_agent.config import (
    PROVIDER_DEFAULTS,
    PROVIDER_KEY_ATTR,
    PROVIDER_KEY_ENV,
    Settings,
)

# ─── PROVIDER_DEFAULTS structure ─────────────────────────────────────────────

EXPECTED_PROVIDERS = {"anthropic", "openai", "google", "bedrock", "openai-compatible"}
# Providers that authenticate with a single API key (bedrock uses AWS creds instead).
EXPECTED_API_KEY_PROVIDERS = {"anthropic", "openai", "google", "openai-compatible"}
EXPECTED_TIERS = {"main", "chart", "quality", "delight"}
# Providers whose default model IDs are intentionally empty (user must supply the model).
PROVIDERS_WITH_EMPTY_DEFAULTS = {"openai-compatible"}


def test_provider_defaults_has_all_providers():
    assert set(PROVIDER_DEFAULTS) == EXPECTED_PROVIDERS


def test_provider_defaults_all_tiers_present():
    for provider, defaults in PROVIDER_DEFAULTS.items():
        missing = EXPECTED_TIERS - set(defaults)
        assert not missing, f"{provider} is missing tiers: {missing}"


def test_provider_defaults_no_empty_values():
    for provider, defaults in PROVIDER_DEFAULTS.items():
        if provider in PROVIDERS_WITH_EMPTY_DEFAULTS:
            continue  # these intentionally have empty defaults — user must supply the model
        for tier, model in defaults.items():
            assert model, f"{provider}[{tier}] is empty"


def test_provider_key_env_covers_all_providers():
    assert set(PROVIDER_KEY_ENV) == EXPECTED_API_KEY_PROVIDERS


def test_provider_key_attr_covers_all_providers():
    assert set(PROVIDER_KEY_ATTR) == EXPECTED_API_KEY_PROVIDERS


def test_provider_key_env_and_attr_consistent():
    """Every provider should appear in both lookup tables."""
    assert set(PROVIDER_KEY_ENV) == set(PROVIDER_KEY_ATTR)


# ─── Settings model-tier methods ─────────────────────────────────────────────


def _settings(provider: str, **overrides) -> Settings:
    return Settings(
        llm_provider=provider,
        database_url="sqlite+aiosqlite:///./test.db",
        **overrides,
    )


# openai-compatible is excluded: its PROVIDER_DEFAULTS are intentionally empty ("") because
# the user must supply a model. The _resolve_model fallback will return whatever
# is in openai_compatible_model/llm_model — which varies per environment. The
# openai-compatible fallback behaviour is covered by test_openai_compatible_* tests below.
_PROVIDERS_WITH_CURATED_DEFAULTS = EXPECTED_PROVIDERS - PROVIDERS_WITH_EMPTY_DEFAULTS


@pytest.mark.parametrize("provider", sorted(_PROVIDERS_WITH_CURATED_DEFAULTS))
def test_get_llm_model_returns_provider_default(provider):
    s = _settings(provider)
    assert s.get_llm_model() == PROVIDER_DEFAULTS[provider]["main"]


@pytest.mark.parametrize("provider", sorted(_PROVIDERS_WITH_CURATED_DEFAULTS))
def test_get_chart_llm_model_returns_provider_default(provider):
    s = _settings(provider)
    assert s.get_chart_llm_model() == PROVIDER_DEFAULTS[provider]["chart"]


@pytest.mark.parametrize("provider", sorted(_PROVIDERS_WITH_CURATED_DEFAULTS))
def test_get_quality_llm_model_returns_provider_default(provider):
    s = _settings(provider)
    assert s.get_quality_llm_model() == PROVIDER_DEFAULTS[provider]["quality"]


@pytest.mark.parametrize("provider", sorted(_PROVIDERS_WITH_CURATED_DEFAULTS))
def test_get_delight_llm_model_returns_provider_default(provider):
    s = _settings(provider)
    assert s.get_delight_llm_model() == PROVIDER_DEFAULTS[provider]["delight"]


def test_llm_model_env_override_takes_precedence():
    s = _settings("anthropic", llm_model="claude-opus-custom")
    assert s.get_llm_model() == "claude-opus-custom"


def test_chart_llm_model_env_override_takes_precedence():
    s = _settings("openai", chart_llm_model="gpt-4o-custom")
    assert s.get_chart_llm_model() == "gpt-4o-custom"


def test_quality_llm_model_env_override_takes_precedence():
    s = _settings("google", quality_llm_model="gemini-custom")
    assert s.get_quality_llm_model() == "gemini-custom"


def test_delight_llm_model_env_override_takes_precedence():
    s = _settings("anthropic", delight_llm_model="claude-haiku-custom")
    assert s.get_delight_llm_model() == "claude-haiku-custom"


def test_unknown_provider_falls_back_to_openai_defaults():
    """Graceful fallback — unknown provider should not raise, returns OpenAI defaults."""
    s = _settings("unknown-future-provider")
    assert s.get_llm_model() == PROVIDER_DEFAULTS["openai"]["main"]


# ─── Settings._resolve_model — openai-compatible provider fallback ───────────


def test_openai_compatible_non_main_tiers_fall_back_to_openai_compatible_model():
    """For 'openai-compatible', chart/quality/delight use openai_compatible_model when no tier override is set."""
    s = _settings("openai-compatible", openai_compatible_model="llama3.2:1b")
    assert s.get_chart_llm_model() == "llama3.2:1b"
    assert s.get_quality_llm_model() == "llama3.2:1b"
    assert s.get_delight_llm_model() == "llama3.2:1b"


def test_openai_compatible_non_main_tiers_prefer_llm_model_over_openai_compatible_model():
    """llm_model (the primary override) takes priority over openai_compatible_model for non-main tiers."""
    s = _settings("openai-compatible", llm_model="qwen2.5:7b", openai_compatible_model="llama3.2:1b")
    assert s.get_chart_llm_model() == "qwen2.5:7b"
    assert s.get_quality_llm_model() == "qwen2.5:7b"
    assert s.get_delight_llm_model() == "qwen2.5:7b"


def test_openai_compatible_tier_override_wins_over_all_fallbacks():
    """Per-tier override always beats the openai_compatible_model fallback."""
    s = _settings(
        "openai-compatible",
        chart_llm_model="chart-specific",
        quality_llm_model="quality-specific",
        delight_llm_model="delight-specific",
        openai_compatible_model="fallback",
    )
    assert s.get_chart_llm_model() == "chart-specific"
    assert s.get_quality_llm_model() == "quality-specific"
    assert s.get_delight_llm_model() == "delight-specific"


def test_openai_compatible_main_tier_falls_back_to_openai_compatible_model():
    """get_llm_model() uses openai_compatible_model when llm_model is unset for the openai-compatible provider."""
    s = _settings("openai-compatible", openai_compatible_model="llama3.2:1b")
    assert s.get_llm_model() == "llama3.2:1b"


def test_openai_compatible_empty_when_neither_model_set():
    """All tiers return '' for openai-compatible provider when no models are configured.

    Constructor kwargs take priority over env/.env in Pydantic BaseSettings, so
    passing empty strings here isolates the test from the user's local .env.
    """
    s = _settings("openai-compatible", llm_model="", openai_compatible_model="")
    assert s.get_llm_model() == ""
    assert s.get_chart_llm_model() == ""
    assert s.get_quality_llm_model() == ""
    assert s.get_delight_llm_model() == ""


# ─── Settings.get_api_key ─────────────────────────────────────────────────────


def test_get_api_key_anthropic():
    s = _settings("anthropic", anthropic_api_key="sk-ant-test")
    assert s.get_api_key() == "sk-ant-test"


def test_get_api_key_openai():
    s = _settings("openai", openai_api_key="sk-oai-test")
    assert s.get_api_key() == "sk-oai-test"


def test_get_api_key_google():
    s = _settings("google", google_api_key="AIza-test")
    assert s.get_api_key() == "AIza-test"


def test_get_api_key_empty_when_not_set():
    s = _settings("anthropic")
    assert s.get_api_key() == ""


def test_get_api_key_bedrock_returns_empty():
    """Bedrock authenticates via AWS credentials, not a single API key."""
    s = _settings("bedrock")
    assert s.get_api_key() == ""


def test_get_api_key_unknown_provider_returns_empty():
    s = _settings("mystery-provider")
    assert s.get_api_key() == ""


# ─── agent/llm._FACTORIES registry ───────────────────────────────────────────


def test_factories_cover_all_providers():
    assert set(_FACTORIES) == EXPECTED_PROVIDERS


@patch("analytics_agent.agent.llm.settings")
def test_make_llm_anthropic_calls_correct_factory(mock_settings):
    mock_settings.llm_provider = "anthropic"
    fake_llm = MagicMock()
    mock_factory = MagicMock(return_value=fake_llm)
    with patch.dict(_FACTORIES, {"anthropic": mock_factory}):
        result = _make_llm("claude-sonnet-4-6")
    mock_factory.assert_called_once_with("claude-sonnet-4-6", False)
    assert result is fake_llm


@patch("analytics_agent.agent.llm.settings")
def test_make_llm_openai_calls_correct_factory(mock_settings):
    mock_settings.llm_provider = "openai"
    fake_llm = MagicMock()
    mock_factory = MagicMock(return_value=fake_llm)
    with patch.dict(_FACTORIES, {"openai": mock_factory}):
        result = _make_llm("gpt-4o", streaming=True)
    mock_factory.assert_called_once_with("gpt-4o", True)
    assert result is fake_llm


@patch("analytics_agent.agent.llm.settings")
def test_make_llm_google_calls_correct_factory(mock_settings):
    mock_settings.llm_provider = "google"
    fake_llm = MagicMock()
    mock_factory = MagicMock(return_value=fake_llm)
    with patch.dict(_FACTORIES, {"google": mock_factory}):
        result = _make_llm("gemini-2.0-flash")
    mock_factory.assert_called_once_with("gemini-2.0-flash", False)
    assert result is fake_llm


@patch("analytics_agent.agent.llm.settings")
def test_make_llm_unknown_provider_raises(mock_settings):
    mock_settings.llm_provider = "mystery-provider"

    with pytest.raises(ValueError, match="Unknown LLM provider"):
        _make_llm("some-model")


@patch("analytics_agent.agent.llm.settings")
def test_make_llm_error_message_lists_valid_providers(mock_settings):
    mock_settings.llm_provider = "mystery"

    with pytest.raises(ValueError) as exc_info:
        _make_llm("some-model")

    msg = str(exc_info.value)
    for p in EXPECTED_PROVIDERS:
        assert p in msg
