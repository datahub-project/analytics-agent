"""MCPResourceClient — reads ui:// resources from MCP servers.

Reuses the MultiServerMCPClient instances in the _mcp_clients registry so we
open a fresh session (per resources/read call) without duplicating connection
config or spinning up a second stdio process.

Disk cache layout::

    ./data/mcp-app-cache/<sha256(connection_key + uri)>.html
    ./data/mcp-app-cache/<sha256(connection_key + uri)>.meta.json

The .meta.json sidecar holds {etag, last_modified, fetched_at, content_hash}.
Cache policy:
  - Within TTL (default 1 h): serve from disk without contacting the server.
  - Past TTL: re-validate using resources/read; compare content_hash if the
    server doesn't return ETag/Last-Modified.
  - Server offline past TTL: return stale cache (HTTP 200) with
    is_stale=True; 404 only when both cache and live server are unavailable.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson

if TYPE_CHECKING:
    from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

# Process-local registry populated by mcp_ui.register_mcp_client().
# Maps connection_key -> (MultiServerMCPClient, server_name).
_mcp_clients: dict[str, tuple[Any, str]] = {}

# Default disk-cache TTL in seconds (1 hour).
_DEFAULT_TTL = 3600

_CACHE_DIR: Path | None = None


def _get_cache_dir() -> Path:
    global _CACHE_DIR  # noqa: PLW0603
    if _CACHE_DIR is None:
        from analytics_agent.config import settings

        db_path = Path(settings.database_url.split("///")[-1])
        data_dir = db_path.parent if db_path.parent.exists() else Path("data")
        _CACHE_DIR = data_dir / "mcp-app-cache"
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _cache_key(connection_key: str, uri: str) -> str:
    return hashlib.sha256(f"{connection_key}\x00{uri}".encode()).hexdigest()


def _html_path(key: str) -> Path:
    return _get_cache_dir() / f"{key}.html"


def _meta_path(key: str) -> Path:
    return _get_cache_dir() / f"{key}.meta.json"


def _read_cache(key: str) -> tuple[str | None, dict]:
    """Return (html, meta) from disk; html is None on miss."""
    html_file = _html_path(key)
    meta_file = _meta_path(key)
    if not html_file.exists() or not meta_file.exists():
        return None, {}
    try:
        html = html_file.read_text(encoding="utf-8")
        meta = orjson.loads(meta_file.read_bytes())
        return html, meta
    except Exception:
        return None, {}


def _write_cache(key: str, html: str, meta: dict) -> None:
    try:
        _html_path(key).write_text(html, encoding="utf-8")
        _meta_path(key).write_bytes(orjson.dumps(meta))
    except Exception:
        logger.warning("MCP app cache write failed for key=%s", key)


def _is_fresh(meta: dict, ttl: int) -> bool:
    fetched_at = meta.get("fetched_at", 0)
    return (time.time() - fetched_at) < ttl


class MCPResourceClient:
    """Reads ui:// resources from MCP servers with disk caching.

    Instantiate once per process; the underlying MultiServerMCPClient instances
    are shared via the _mcp_clients registry.
    """

    def __init__(self, ttl: int = _DEFAULT_TTL) -> None:
        self.ttl = ttl

    async def read_ui_resource(
        self,
        connection_key: str,
        uri: str,
        *,
        use_cache: bool = True,
    ) -> dict:
        """Fetch a ui:// resource.

        Returns a dict with keys: html, csp, permissions, etag, last_modified,
        is_stale (True when falling back to a stale cache entry).

        Raises RuntimeError if both cache and live server are unavailable.
        """
        key = _cache_key(connection_key, uri)
        cached_html, cached_meta = _read_cache(key)

        if use_cache and cached_html is not None and _is_fresh(cached_meta, self.ttl):
            logger.debug("MCP app cache hit (fresh) for uri=%s", uri)
            return {
                "html": cached_html,
                "csp": cached_meta.get("csp"),
                "permissions": cached_meta.get("permissions", []),
                "etag": cached_meta.get("etag"),
                "last_modified": cached_meta.get("last_modified"),
                "is_stale": False,
            }

        # Need to fetch / re-validate from the server.
        try:
            result = await self._fetch_from_server(connection_key, uri, cached_meta)
        except Exception as exc:
            if cached_html is not None:
                logger.warning(
                    "MCP server unavailable for uri=%s; serving stale cache: %s",
                    uri,
                    exc,
                )
                return {
                    "html": cached_html,
                    "csp": cached_meta.get("csp"),
                    "permissions": cached_meta.get("permissions", []),
                    "etag": cached_meta.get("etag"),
                    "last_modified": cached_meta.get("last_modified"),
                    "is_stale": True,
                }
            raise RuntimeError(
                f"MCP resource unavailable and no cache for uri={uri!r}: {exc}"
            ) from exc

        if result is None:
            # Server said "not modified" (304-style).
            assert cached_html is not None
            new_meta = {**cached_meta, "fetched_at": time.time()}
            _write_cache(key, cached_html, new_meta)
            return {
                "html": cached_html,
                "csp": cached_meta.get("csp"),
                "permissions": cached_meta.get("permissions", []),
                "etag": cached_meta.get("etag"),
                "last_modified": cached_meta.get("last_modified"),
                "is_stale": False,
            }

        html, new_meta = result
        _write_cache(key, html, new_meta)
        return {
            "html": html,
            "csp": new_meta.get("csp"),
            "permissions": new_meta.get("permissions", []),
            "etag": new_meta.get("etag"),
            "last_modified": new_meta.get("last_modified"),
            "is_stale": False,
        }

    async def _fetch_from_server(
        self,
        connection_key: str,
        uri: str,
        cached_meta: dict,
    ) -> tuple[str, dict] | None:
        """Fetch resource from the MCP server.

        Returns (html, new_meta) on success, None if content is unchanged.
        Raises on failure.
        """
        if connection_key not in _mcp_clients:
            raise RuntimeError(
                f"No MCP client registered for connection_key={connection_key!r}"
            )

        client, server_name = _mcp_clients[connection_key]

        from pydantic import AnyUrl

        async with client.session(server_name) as session:
            result = await session.read_resource(AnyUrl(uri))

        if not result.contents:
            raise RuntimeError(f"Empty resource response for uri={uri!r}")

        first = result.contents[0]
        if not hasattr(first, "text"):
            raise RuntimeError(
                f"Resource {uri!r} returned non-text content (type={type(first).__name__})"
            )
        html: str = first.text

        # Compare content hash for change detection when server doesn't send ETags.
        content_hash = hashlib.sha256(html.encode()).hexdigest()
        if cached_meta.get("content_hash") == content_hash:
            return None  # unchanged

        new_meta: dict = {
            "fetched_at": time.time(),
            "content_hash": content_hash,
            "etag": None,
            "last_modified": None,
            "csp": None,
            "permissions": [],
        }

        # Extract optional csp/permissions from resource metadata (if exposed).
        meta_obj = getattr(result, "meta", None) or {}
        if isinstance(meta_obj, dict):
            ui = meta_obj.get("ui") or {}
            new_meta["csp"] = ui.get("csp")
            new_meta["permissions"] = ui.get("permissions") or []

        return html, new_meta


# Module-level singleton shared across call sites.
resource_client = MCPResourceClient()
