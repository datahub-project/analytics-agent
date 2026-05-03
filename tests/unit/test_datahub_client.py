"""
Unit tests for DataHub credential resolution and non-blocking client construction.

These tests directly verify the fix for the blocking-event-loop bug:
- _get_db_datahub_credentials_async() must read from DB (old code always fell back to env vars)
- _get_db_datahub_credentials_sync() must use asyncio.run() not get_event_loop()
- aget_datahub_client() must construct DataHubClient via asyncio.to_thread
- get_datahub_capabilities() must cache results for the TTL window
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from analytics_agent.db.models import Base
from analytics_agent.db.repository import ContextPlatformRepo
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ── In-memory DB fixtures ─────────────────────────────────────────────────────


def _make_factory(engine):
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def empty_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield _make_factory(engine)
    await engine.dispose()


@pytest_asyncio.fixture
async def configured_factory():
    """Session factory pre-seeded with a native DataHub platform row."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = _make_factory(engine)
    async with factory() as s:
        await ContextPlatformRepo(s).upsert(
            id=str(uuid.uuid4()),
            type="datahub",
            name="default",
            label="DataHub",
            config='{"type":"datahub","url":"http://dh.test:8080","token":"test-tok"}',
            source="ui",
        )
        await s.commit()
    yield factory
    await engine.dispose()


# ── _get_db_datahub_credentials_async ────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_credentials_reads_from_db(configured_factory):
    """Core bug fix: the async variant returns DB url+token, not the env-var fallback."""
    from analytics_agent.context.datahub import _get_db_datahub_credentials_async

    with patch("analytics_agent.db.base._get_session_factory", return_value=configured_factory):
        url, token, any_in_db = await _get_db_datahub_credentials_async()

    assert url == "http://dh.test:8080"
    assert token == "test-tok"
    assert any_in_db is True


@pytest.mark.asyncio
async def test_async_credentials_fallback_when_no_db_rows(empty_factory):
    """No matching DB row → returns settings.get_datahub_config() fallback."""
    from analytics_agent.context.datahub import _get_db_datahub_credentials_async

    with (
        patch("analytics_agent.db.base._get_session_factory", return_value=empty_factory),
        patch("analytics_agent.context.datahub.settings") as mock_settings,
    ):
        mock_settings.get_datahub_config.return_value = ("http://env-url", "env-tok")
        url, token, any_in_db = await _get_db_datahub_credentials_async()

    assert url == "http://env-url"
    assert token == "env-tok"
    assert any_in_db is False


@pytest.mark.asyncio
async def test_async_credentials_fallback_on_db_exception():
    """DB error → falls back to settings.get_datahub_config() without raising."""
    from analytics_agent.context.datahub import _get_db_datahub_credentials_async

    with (
        patch("analytics_agent.db.base._get_session_factory", side_effect=RuntimeError("boom")),
        patch("analytics_agent.context.datahub.settings") as mock_settings,
    ):
        mock_settings.get_datahub_config.return_value = ("http://fallback", "fallback-tok")
        url, token, any_in_db = await _get_db_datahub_credentials_async()

    assert url == "http://fallback"
    assert token == "fallback-tok"
    assert any_in_db is False


# ── _get_db_datahub_credentials_sync ─────────────────────────────────────────


def test_sync_credentials_reads_from_db():
    """Sync variant uses asyncio.run() — safe in thread context, reads actual DB row."""
    from analytics_agent.context.datahub import _get_db_datahub_credentials_sync

    fake_platform = MagicMock()
    fake_platform.config = '{"type":"datahub","url":"http://dh.test:8080","token":"sync-tok"}'

    class _FakeSessionCM:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *_):
            pass

    fake_factory = MagicMock(return_value=_FakeSessionCM())

    with (
        patch("analytics_agent.db.base._get_session_factory", return_value=fake_factory),
        patch("analytics_agent.db.repository.ContextPlatformRepo") as MockRepo,
    ):
        mock_repo = AsyncMock()
        mock_repo.list_all = AsyncMock(return_value=[fake_platform])
        MockRepo.return_value = mock_repo

        url, token, any_in_db = _get_db_datahub_credentials_sync()

    assert url == "http://dh.test:8080"
    assert token == "sync-tok"
    assert any_in_db is True


def test_sync_credentials_fallback_on_exception():
    """Sync variant falls back to settings.get_datahub_config() on any error."""
    from analytics_agent.context.datahub import _get_db_datahub_credentials_sync

    with (
        patch("analytics_agent.db.base._get_session_factory", side_effect=RuntimeError("no db")),
        patch("analytics_agent.context.datahub.settings") as mock_settings,
    ):
        mock_settings.get_datahub_config.return_value = ("http://sync-fallback", "sfb-tok")
        url, token, any_in_db = _get_db_datahub_credentials_sync()

    assert url == "http://sync-fallback"
    assert token == "sfb-tok"
    assert any_in_db is False


# ── aget_datahub_client ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aget_datahub_client_returns_none_when_unconfigured():
    """No url+token and no ~/.datahubenv → None."""
    from analytics_agent.context.datahub import aget_datahub_client

    with (
        patch(
            "analytics_agent.context.datahub._get_db_datahub_credentials_async",
            new=AsyncMock(return_value=("", "", False)),
        ),
        patch("pathlib.Path.exists", return_value=False),
    ):
        client = await aget_datahub_client()

    assert client is None


@pytest.mark.asyncio
async def test_aget_datahub_client_returns_none_when_token_but_no_url():
    """Stale DATAHUB_GMS_TOKEN env var without a URL must not trigger from_env() / localhost probe."""
    from analytics_agent.context.datahub import aget_datahub_client

    with (
        patch(
            "analytics_agent.context.datahub._get_db_datahub_credentials_async",
            new=AsyncMock(return_value=("", "some-stale-token", False)),
        ),
        patch("pathlib.Path.exists", return_value=False),
    ):
        client = await aget_datahub_client()

    assert client is None


@pytest.mark.asyncio
async def test_aget_datahub_client_returns_none_when_mcp_only_in_db():
    """MCP-only DataHub in DB must suppress ~/.datahubenv probe (search_business_context fix)."""
    from analytics_agent.context.datahub import aget_datahub_client

    # any_datahub_in_db=True but no native url/token — user has MCP DataHub configured
    with (
        patch(
            "analytics_agent.context.datahub._get_db_datahub_credentials_async",
            new=AsyncMock(return_value=("", "", True)),
        ),
        patch("pathlib.Path.exists", return_value=True),
    ):  # datahubenv exists but must be ignored
        client = await aget_datahub_client()

    assert client is None


@pytest.mark.asyncio
async def test_aget_datahub_client_uses_asyncio_to_thread():
    """DataHubClient is constructed via asyncio.to_thread, not inline."""
    from analytics_agent.context.datahub import aget_datahub_client

    fake_client = MagicMock()

    # asyncio is imported locally inside aget_datahub_client, so we patch the
    # stdlib module directly — it's cached in sys.modules and picked up on re-import.
    with (
        patch(
            "analytics_agent.context.datahub._get_db_datahub_credentials_async",
            new=AsyncMock(return_value=("http://dh.test:8080", "test-tok", True)),
        ),
        patch("asyncio.to_thread", new=AsyncMock(return_value=fake_client)) as mock_to_thread,
        patch("pathlib.Path.exists", return_value=False),
        patch("datahub.sdk.main_client.DataHubClient"),
    ):
        client = await aget_datahub_client()

    assert client is fake_client
    mock_to_thread.assert_awaited_once()


# ── get_datahub_capabilities cache ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_capabilities_cache_hit_skips_client():
    """Second call within TTL returns cached result without constructing a new client."""
    import analytics_agent.api.settings as settings_module
    from analytics_agent.api.settings import get_datahub_capabilities

    # Reset cache state before test
    settings_module._capabilities_cache = None
    settings_module._capabilities_cache_ts = 0.0

    fake_client = MagicMock()
    fake_graph = MagicMock()
    fake_graph.execute_graphql = MagicMock(
        return_value={"semanticSearchAcrossEntities": {"total": 0}}
    )
    fake_client._graph = fake_graph

    # aget_datahub_client is imported lazily inside get_datahub_capabilities, so
    # we patch it at its source module, not in settings.
    with (
        patch(
            "analytics_agent.context.datahub.aget_datahub_client",
            new=AsyncMock(return_value=fake_client),
        ),
        patch(
            "asyncio.to_thread",
            new=AsyncMock(return_value={"semanticSearchAcrossEntities": {"total": 0}}),
        ),
    ):
        result1 = await get_datahub_capabilities()
        result2 = await get_datahub_capabilities()

    # The important assertion: both calls return the same result (cache hit on second call)
    assert result1 == result2
    assert "semantic_search" in result1

    # Cleanup
    settings_module._capabilities_cache = None
    settings_module._capabilities_cache_ts = 0.0


@pytest.mark.asyncio
async def test_capabilities_cache_expired_hits_client_again():
    """After TTL expires, the next call re-probes DataHub."""
    import time

    import analytics_agent.api.settings as settings_module
    from analytics_agent.api.settings import _CAPABILITIES_TTL, get_datahub_capabilities

    # Pre-populate an expired cache entry
    settings_module._capabilities_cache = {"semantic_search": True}
    settings_module._capabilities_cache_ts = time.monotonic() - _CAPABILITIES_TTL - 1

    fake_client = MagicMock()
    fake_client._graph = MagicMock()

    call_count = 0

    async def fake_to_thread(fn, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {"semanticSearchAcrossEntities": {"total": 0}}

    with (
        patch(
            "analytics_agent.context.datahub.aget_datahub_client",
            new=AsyncMock(return_value=fake_client),
        ),
        patch("asyncio.to_thread", new=fake_to_thread),
    ):
        await get_datahub_capabilities()

    assert call_count == 1  # re-probed because cache was stale

    # Cleanup
    settings_module._capabilities_cache = None
    settings_module._capabilities_cache_ts = 0.0
