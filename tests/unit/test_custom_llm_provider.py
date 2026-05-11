"""
Tests for the custom OpenAI-compatible LLM provider (LiteLLM, vLLM, Ollama, etc.).

Uses URL + model + ``Authorization`` header (same wire shape as the former
openai-compatible flow). Spins up a minimal in-process HTTP server that speaks
the OpenAI chat completions API, then exercises:

    settings API (test + save) → LLM factory (_make_custom)
    → ChatOpenAI(base_url=…) → [mock proxy] → parsed AIMessage

No external services required — runs in the standard CI unit-test job.

To run against a real Ollama instance instead of the built-in mock, export:
    OPENAI_COMPAT_TEST_URL=http://localhost:11434/v1
    OPENAI_COMPAT_TEST_MODEL=llama3.2:1b
and run:
    uv run pytest tests/unit/test_custom_llm_provider.py -v -s
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import pytest

_AUTH_HEADERS_JSON = json.dumps({"Authorization": "Bearer test-key"})

# ---------------------------------------------------------------------------
# In-process mock proxy
# ---------------------------------------------------------------------------

_CHAT_RESPONSE = {
    "id": "chatcmpl-mock",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "mock-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "hello from mock proxy"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


class _OpenAICompatHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible chat completions endpoint."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)  # drain body — we don't validate it
        body = json.dumps(_CHAT_RESPONSE).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        pass  # suppress per-request noise in test output


@pytest.fixture(scope="module")
def mock_proxy_url() -> str:  # type: ignore[return]
    """Start a mock OpenAI-compatible server on a free port.

    If OPENAI_COMPAT_TEST_URL is set, that URL is yielded instead so the same
    tests run against a real proxy (e.g. Ollama) with zero code changes.

    Yields the base URL callers should pass as ``custom_url`` (e.g.
    ``http://127.0.0.1:PORT/v1``).
    """
    external = os.environ.get("OPENAI_COMPAT_TEST_URL", "").strip()
    if external:
        yield external
        return

    server = HTTPServer(("127.0.0.1", 0), _OpenAICompatHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/v1"
    server.shutdown()


@pytest.fixture(scope="module")
def proxy_model(mock_proxy_url: str) -> str:
    """Model name to use: real model when testing against Ollama, else 'mock-model'."""
    if os.environ.get("OPENAI_COMPAT_TEST_URL"):
        return os.environ.get("OPENAI_COMPAT_TEST_MODEL", "llama3.2:1b")
    return "mock-model"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _patch_custom_llm(url: str, model: str):
    """Temporarily point the settings singleton at the mock proxy."""
    from analytics_agent.config import settings

    saved = (
        settings.llm_provider,
        settings.custom_llm_url,
        settings.custom_llm_model,
        settings.custom_llm_headers,
        settings.llm_model,
    )
    settings.llm_provider = "custom"
    settings.custom_llm_url = url
    settings.custom_llm_model = model
    settings.custom_llm_headers = _AUTH_HEADERS_JSON
    settings.llm_model = model
    try:
        yield settings
    finally:
        (
            settings.llm_provider,
            settings.custom_llm_url,
            settings.custom_llm_model,
            settings.custom_llm_headers,
            settings.llm_model,
        ) = saved


# ---------------------------------------------------------------------------
# 1. Factory — ChatOpenAI is constructed with the right kwargs
# ---------------------------------------------------------------------------


def test_factory_passes_base_url_and_model(mock_proxy_url: str, proxy_model: str) -> None:
    """_make_custom must forward base_url and model to ChatOpenAI."""
    from analytics_agent.config import settings

    settings.custom_llm_url = mock_proxy_url
    settings.custom_llm_headers = _AUTH_HEADERS_JSON

    with patch("langchain_openai.ChatOpenAI") as MockChat:
        MockChat.return_value = MockChat  # keep the mock callable
        from analytics_agent.agent.llm import _make_custom

        _make_custom(proxy_model, streaming=False)

    kwargs = MockChat.call_args.kwargs
    assert kwargs["base_url"] == mock_proxy_url.rstrip("/")
    assert kwargs["model"] == proxy_model
    assert kwargs["temperature"] == 0


def test_factory_raises_without_url() -> None:
    """_make_custom must raise clearly when custom URL is not configured."""
    from analytics_agent.config import settings

    saved_url = settings.custom_llm_url
    saved_headers = settings.custom_llm_headers
    settings.custom_llm_url = ""
    settings.custom_llm_headers = ""
    try:
        from analytics_agent.agent.llm import _make_custom

        with pytest.raises(ValueError, match="custom_llm_url"):
            _make_custom("some-model", streaming=False)
    finally:
        settings.custom_llm_url = saved_url
        settings.custom_llm_headers = saved_headers


# ---------------------------------------------------------------------------
# 2. End-to-end: real HTTP call through the mock proxy
# ---------------------------------------------------------------------------


def test_invoke_returns_response_from_proxy(mock_proxy_url: str, proxy_model: str) -> None:
    """ChatOpenAI built by the factory must complete a real HTTP round-trip
    through the (mock or real) proxy and return a non-empty AIMessage."""
    from analytics_agent.agent.llm import _make_custom
    from analytics_agent.config import settings

    settings.custom_llm_url = mock_proxy_url
    settings.custom_llm_headers = _AUTH_HEADERS_JSON

    llm = _make_custom(proxy_model, streaming=False)
    response = llm.invoke("say hello in one word")

    assert response.content, "Expected a non-empty response from the proxy"


def test_get_llm_uses_custom_when_provider_is_set(mock_proxy_url: str, proxy_model: str) -> None:
    """The public get_llm() accessor must route through the custom backend when
    llm_provider='custom' and llm_model is set."""
    from analytics_agent.agent.llm import get_llm
    from analytics_agent.config import settings

    saved_model = settings.llm_model
    settings.llm_model = proxy_model

    with _patch_custom_llm(mock_proxy_url, proxy_model):
        llm = get_llm(streaming=False)
        response = llm.invoke("ping")

    settings.llm_model = saved_model
    assert response.content


# ---------------------------------------------------------------------------
# 3. Settings API: /api/settings/llm/test endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_endpoint_ok_with_proxy(mock_proxy_url: str, proxy_model: str) -> None:
    """POST /api/settings/llm/test with a reachable proxy must return ok=True."""
    from analytics_agent.api.settings import TestLlmKeyRequest, test_llm_key

    result = await test_llm_key(
        TestLlmKeyRequest(
            provider="custom",
            custom_url=mock_proxy_url,
            custom_model=proxy_model,
            custom_headers=_AUTH_HEADERS_JSON,
        )
    )
    assert result.ok is True, f"Expected ok=True, got: {result.message}"


@pytest.mark.asyncio
async def test_test_endpoint_fails_when_custom_url_missing() -> None:
    """POST /api/settings/llm/test without custom_url must return ok=False."""
    from analytics_agent.api.settings import TestLlmKeyRequest, test_llm_key

    result = await test_llm_key(
        TestLlmKeyRequest(
            provider="custom",
            custom_url="",
            custom_model="any-model",
            custom_headers=_AUTH_HEADERS_JSON,
        )
    )
    assert result.ok is False


@pytest.mark.asyncio
async def test_test_endpoint_fails_when_proxy_unreachable() -> None:
    """POST /api/settings/llm/test pointing at a dead port must return ok=False."""
    from analytics_agent.api.settings import TestLlmKeyRequest, test_llm_key

    result = await test_llm_key(
        TestLlmKeyRequest(
            provider="custom",
            custom_url="http://127.0.0.1:19999/v1",  # nothing listening here
            custom_model="any-model",
            custom_headers=_AUTH_HEADERS_JSON,
        )
    )
    assert result.ok is False


# ---------------------------------------------------------------------------
# 4. Settings persistence: custom_url survives a save → get round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_custom_url_reflected_in_get(mock_proxy_url: str, proxy_model: str) -> None:
    """PUT /api/settings/llm with custom_url must update the in-memory singleton
    so that GET /api/settings/llm returns the same URL immediately."""
    from unittest.mock import AsyncMock

    from analytics_agent.api.settings import (
        UpdateLlmSettingsRequest,
        get_llm_settings,
        update_llm_settings,
    )
    from analytics_agent.config import settings

    saved = (
        settings.llm_provider,
        settings.llm_model,
        settings.custom_llm_url,
        settings.custom_llm_model,
        settings.custom_llm_headers,
    )

    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_repo.get.return_value = None  # no pre-existing config

    with (
        patch("analytics_agent.api.settings.SettingsRepo", return_value=mock_repo),
        patch.dict(os.environ, {}, clear=False),
    ):
        await update_llm_settings(
            UpdateLlmSettingsRequest(
                provider="custom",
                model=proxy_model,
                custom_url=mock_proxy_url,
                custom_model=proxy_model,
                custom_headers=_AUTH_HEADERS_JSON,
            ),
            mock_session,
        )

        response = await get_llm_settings()

    (
        settings.llm_provider,
        settings.llm_model,
        settings.custom_llm_url,
        settings.custom_llm_model,
        settings.custom_llm_headers,
    ) = saved

    assert response.provider == "custom"
    assert response.custom_url == mock_proxy_url
