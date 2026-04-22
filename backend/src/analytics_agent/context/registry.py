"""Factory that builds ContextPlatform instances from DB rows."""

from __future__ import annotations

import contextlib
import logging

import orjson

from analytics_agent.config import DataHubMCPConfig, DataHubPlatformConfig, parse_platform_config
from analytics_agent.context.base import ContextPlatform

logger = logging.getLogger(__name__)


def build_platform(
    plat, disabled_connections: set[str] | None = None, include_mutations: bool = False
) -> ContextPlatform | None:
    """Build a ContextPlatform from a DB row.

    Dispatches on the typed ContextPlatformConfig discriminator — no _mcp
    blob inspection needed.  Returns None for disabled or incomplete configs.
    """
    if disabled_connections and plat.name in disabled_connections:
        logger.info("Context platform '%s' is disabled — skipping", plat.name)
        return None

    raw: dict = {}
    with contextlib.suppress(Exception):
        raw = orjson.loads(plat.config)

    disabled_tools: set[str] = set(raw.get("_disabled_tools") or [])
    cfg = parse_platform_config(raw)

    if isinstance(cfg, DataHubMCPConfig):
        if cfg.transport in ("http", "sse", "streamable_http"):
            if not cfg.url:
                logger.warning("MCP platform '%s' has no URL — skipping", plat.name)
                return None
            from analytics_agent.context.mcp_platform import MCPContextPlatform

            return MCPContextPlatform(
                name=plat.name,
                transport=cfg.transport,
                url=cfg.url,
                headers=cfg.headers,
                disabled_tools=disabled_tools,
                include_mutations=include_mutations,
            )

        if cfg.transport == "stdio":
            if not cfg.command:
                logger.warning("MCP stdio platform '%s' has no command — skipping", plat.name)
                return None
            from analytics_agent.context.mcp_platform import MCPContextPlatform

            return MCPContextPlatform(
                name=plat.name,
                transport="stdio",
                command=cfg.command,
                args=cfg.args,
                env=cfg.env,
                disabled_tools=disabled_tools,
                include_mutations=include_mutations,
            )

        logger.warning("Unknown MCP transport '%s' for platform '%s'", cfg.transport, plat.name)
        return None

    if isinstance(cfg, DataHubPlatformConfig):
        if not cfg.url or not cfg.token:
            logger.warning("Native DataHub platform '%s' has no URL/token — skipping", plat.name)
            return None
        from analytics_agent.context.native_datahub import NativeDataHubPlatform

        return NativeDataHubPlatform(
            name=plat.name,
            url=cfg.url,
            token=cfg.token,
            disabled_tools=disabled_tools,
            include_mutations=include_mutations,
        )

    return None
