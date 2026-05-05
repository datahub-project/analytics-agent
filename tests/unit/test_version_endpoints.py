"""
Tests for the /api/version and /api/releases endpoints, the _install_kind()
helper, and the `analytics-agent upgrade` CLI guard.

Key cases exercised:
- Airgapped / network-unreachable: endpoints return gracefully (no exception)
- Version comparison: older, equal, newer, malformed tags
- Cache: a second call within TTL skips the network
- _install_kind(): editable / uvx / pip detection
- upgrade CLI: editable and uvx installs get a clear error, not a broken pip run
"""

from __future__ import annotations

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_release(tag: str, body: str = "") -> dict:
    return {
        "tag_name": tag,
        "name": tag,
        "published_at": "2025-01-01T00:00:00Z",
        "body": body,
        "html_url": f"https://github.com/datahub-project/analytics-agent/releases/tag/{tag}",
        "prerelease": False,
        "draft": False,
    }


def _mock_httpx_response(releases: list[dict], status: int = 200):
    """Return an AsyncMock that mimics httpx.AsyncClient used as async context manager."""
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.json.return_value = releases

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ── _fetch_releases ────────────────────────────────────────────────────────────


async def test_fetch_releases_airgapped_returns_empty():
    """Network unreachable → graceful empty list, no exception."""
    import analytics_agent.api as api_mod
    import httpx

    # Clear any cached data from previous test runs
    api_mod._releases_cache.clear()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("unreachable"))
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = await api_mod._fetch_releases()
        assert result == []


async def test_fetch_releases_non_200_returns_empty():
    """Non-200 from GitHub (e.g. rate-limited) → empty list."""
    import analytics_agent.api as api_mod

    api_mod._releases_cache.clear()

    mock_client = _mock_httpx_response([], status=403)
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await api_mod._fetch_releases()
        assert result == []


async def test_fetch_releases_happy_path():
    """Valid GitHub response → correct data returned."""
    import analytics_agent.api as api_mod

    api_mod._releases_cache.clear()

    releases = [_make_release("v0.3.0"), _make_release("v0.2.2")]
    mock_client = _mock_httpx_response(releases)
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await api_mod._fetch_releases()
        assert len(result) == 2
        assert result[0]["tag_name"] == "v0.3.0"


async def test_fetch_releases_cache_prevents_second_call():
    """Within TTL, a second call must not make another HTTP request."""
    import analytics_agent.api as api_mod

    api_mod._releases_cache.clear()

    releases = [_make_release("v0.3.0")]
    mock_client = _mock_httpx_response(releases)
    with patch("httpx.AsyncClient", return_value=mock_client) as mock_cls:
        await api_mod._fetch_releases()
        await api_mod._fetch_releases()
        # AsyncClient should only have been constructed once
        assert mock_cls.call_count == 1


async def test_fetch_releases_cache_expires():
    """After TTL, the next call must hit the network again."""
    import analytics_agent.api as api_mod

    api_mod._releases_cache.clear()

    releases = [_make_release("v0.3.0")]
    mock_client = _mock_httpx_response(releases)
    with patch("httpx.AsyncClient", return_value=mock_client) as mock_cls:
        await api_mod._fetch_releases()
        # Wind back the cache timestamp past TTL
        api_mod._releases_cache["releases"]["ts"] -= api_mod._CACHE_TTL + 1
        await api_mod._fetch_releases()
        assert mock_cls.call_count == 2


# ── GET /api/version ──────────────────────────────────────────────────────────


async def test_version_endpoint_airgapped():
    """/api/version with no network: update_available=False, latest_version=None."""
    import analytics_agent.api as api_mod

    api_mod._releases_cache.clear()

    with (
        patch.object(api_mod, "_fetch_releases", new=AsyncMock(return_value=[])),
        patch("importlib.metadata.version", return_value="0.2.2"),
    ):
        result = await api_mod.get_version()

    assert result["current_version"] == "0.2.2"
    assert result["latest_version"] is None
    assert result["update_available"] is False


async def test_version_endpoint_up_to_date():
    import analytics_agent.api as api_mod

    api_mod._releases_cache.clear()

    releases = [_make_release("v0.2.2")]
    with (
        patch.object(api_mod, "_fetch_releases", new=AsyncMock(return_value=releases)),
        patch("importlib.metadata.version", return_value="0.2.2"),
    ):
        result = await api_mod.get_version()

    assert result["update_available"] is False
    assert result["latest_version"] == "0.2.2"


async def test_version_endpoint_update_available():
    import analytics_agent.api as api_mod

    api_mod._releases_cache.clear()

    releases = [_make_release("v0.3.0")]
    with (
        patch.object(api_mod, "_fetch_releases", new=AsyncMock(return_value=releases)),
        patch("importlib.metadata.version", return_value="0.2.2"),
    ):
        result = await api_mod.get_version()

    assert result["update_available"] is True
    assert result["current_version"] == "0.2.2"
    assert result["latest_version"] == "0.3.0"


async def test_version_endpoint_installed_is_newer():
    """Dev/pre-release builds may exceed the latest public tag."""
    import analytics_agent.api as api_mod

    api_mod._releases_cache.clear()

    releases = [_make_release("v0.2.2")]
    with (
        patch.object(api_mod, "_fetch_releases", new=AsyncMock(return_value=releases)),
        patch("importlib.metadata.version", return_value="0.3.0.dev1"),
    ):
        result = await api_mod.get_version()

    assert result["update_available"] is False


async def test_version_endpoint_malformed_tag_no_crash():
    """GitHub returns a tag that can't be parsed as a version → no exception."""
    import analytics_agent.api as api_mod

    api_mod._releases_cache.clear()

    releases = [_make_release("not-a-semver-tag")]
    with (
        patch.object(api_mod, "_fetch_releases", new=AsyncMock(return_value=releases)),
        patch("importlib.metadata.version", return_value="0.2.2"),
    ):
        result = await api_mod.get_version()

    # packaging.version will raise; fallback is string comparison
    assert "update_available" in result


async def test_version_endpoint_package_not_installed():
    """importlib.metadata fails (e.g. running outside any install) → current='unknown'."""
    import analytics_agent.api as api_mod

    api_mod._releases_cache.clear()

    with (
        patch.object(api_mod, "_fetch_releases", new=AsyncMock(return_value=[])),
        patch("importlib.metadata.version", side_effect=Exception("not found")),
    ):
        result = await api_mod.get_version()

    assert result["current_version"] == "unknown"
    assert result["update_available"] is False


# ── GET /api/releases ─────────────────────────────────────────────────────────


async def test_releases_endpoint_filters_drafts():
    import analytics_agent.api as api_mod

    api_mod._releases_cache.clear()

    published = _make_release("v0.3.0")
    draft = {**_make_release("v0.3.1-draft"), "draft": True}

    with patch.object(api_mod, "_fetch_releases", new=AsyncMock(return_value=[published, draft])):
        result = await api_mod.get_releases()

    assert len(result) == 1
    assert result[0]["tag_name"] == "v0.3.0"


async def test_releases_endpoint_airgapped_returns_empty_list():
    import analytics_agent.api as api_mod

    api_mod._releases_cache.clear()

    with patch.object(api_mod, "_fetch_releases", new=AsyncMock(return_value=[])):
        result = await api_mod.get_releases()

    assert result == []


# ── _install_kind() ───────────────────────────────────────────────────────────


def test_install_kind_editable(tmp_path):
    """direct_url.json with editable=true → 'editable'."""
    from analytics_agent.cli import _install_kind

    direct_url = json.dumps({"url": f"file://{tmp_path}", "dir_info": {"editable": True}})
    mock_dist = MagicMock()
    mock_dist.read_text.return_value = direct_url

    with patch("importlib.metadata.distribution", return_value=mock_dist):
        assert _install_kind() == "editable"


def test_install_kind_non_editable_directory(tmp_path):
    """direct_url.json present but editable=false → 'pip' (not editable)."""
    from analytics_agent.cli import _install_kind

    direct_url = json.dumps({"url": f"file://{tmp_path}", "dir_info": {"editable": False}})
    mock_dist = MagicMock()
    mock_dist.read_text.return_value = direct_url

    with (
        patch("importlib.metadata.distribution", return_value=mock_dist),
        patch.object(sys, "executable", "/home/user/.venv/bin/python"),
    ):
        assert _install_kind() == "pip"


def test_install_kind_uvx():
    """sys.executable under uv tools path → 'uvx'."""
    from analytics_agent.cli import _install_kind

    mock_dist = MagicMock()
    mock_dist.read_text.return_value = None  # no direct_url.json

    with patch("importlib.metadata.distribution", return_value=mock_dist):
        uvx_exe = "/home/user/.local/share/uv/tools/datahub-analytics-agent/bin/python"
        with patch.object(sys, "executable", uvx_exe):
            assert _install_kind() == "uvx"


def test_install_kind_normal_pip():
    """Regular venv install with no direct_url.json → 'pip'."""
    from analytics_agent.cli import _install_kind

    mock_dist = MagicMock()
    mock_dist.read_text.return_value = None

    with (
        patch("importlib.metadata.distribution", return_value=mock_dist),
        patch.object(sys, "executable", "/home/user/.venv/bin/python"),
    ):
        assert _install_kind() == "pip"


# ── analytics-agent upgrade — install-kind guards ─────────────────────────────


def test_upgrade_rejects_editable_install():
    from analytics_agent.cli import cli

    with patch("analytics_agent.cli._install_kind", return_value="editable"):
        result = CliRunner().invoke(cli, ["upgrade", "--yes"])

    assert result.exit_code != 0
    assert "git pull" in result.output


def test_upgrade_rejects_uvx_install():
    from analytics_agent.cli import cli

    with patch("analytics_agent.cli._install_kind", return_value="uvx"):
        result = CliRunner().invoke(cli, ["upgrade", "--yes"])

    assert result.exit_code != 0
    assert "uv tool upgrade" in result.output


def test_upgrade_rejects_uvx_with_version():
    """--to flag must appear in the suggested uv command."""
    from analytics_agent.cli import cli

    with patch("analytics_agent.cli._install_kind", return_value="uvx"):
        result = CliRunner().invoke(cli, ["upgrade", "--to", "0.2.1", "--yes"])

    assert result.exit_code != 0
    assert "0.2.1" in result.output


def test_upgrade_pip_install_proceeds(monkeypatch):
    """Normal pip install: subprocess.run is called with the right arguments."""

    from analytics_agent.cli import cli

    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with (
        patch("analytics_agent.cli._install_kind", return_value="pip"),
        patch("analytics_agent.cli.subprocess.run", side_effect=fake_run),
        patch("importlib.metadata.version", return_value="0.2.2"),
        patch("analytics_agent.quickstart.read_pid", return_value=None),
    ):
        result = CliRunner().invoke(cli, ["upgrade", "--yes"])

    assert result.exit_code == 0
    assert any("datahub-analytics-agent" in " ".join(cmd) for cmd in calls)


def test_upgrade_pip_install_specific_version(monkeypatch):
    """--to 0.2.1 must pass datahub-analytics-agent==0.2.1 to pip."""
    from analytics_agent.cli import cli

    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with (
        patch("analytics_agent.cli._install_kind", return_value="pip"),
        patch("analytics_agent.cli.subprocess.run", side_effect=fake_run),
        patch("importlib.metadata.version", return_value="0.2.2"),
        patch("analytics_agent.quickstart.read_pid", return_value=None),
    ):
        result = CliRunner().invoke(cli, ["upgrade", "--to", "0.2.1", "--yes"])

    assert result.exit_code == 0
    assert any("datahub-analytics-agent==0.2.1" in " ".join(cmd) for cmd in calls)
