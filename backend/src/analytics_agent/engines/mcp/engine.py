"""MCP-backed query engine.

Tools are discovered dynamically via MCP tools/list — NOT hardcoded like
native SQL engines. The client and subprocess are kept alive across tool
calls by caching them on the engine instance after the first connection.

Usage in chat.py:
    engine_tools = await mcp_engine.get_tools_async()
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from analytics_agent.engines.base import QueryEngine

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


class MCPQueryEngine(QueryEngine):
    name = "mcp"

    def __init__(self, connection_cfg: dict[str, Any]) -> None:
        mcp_raw = connection_cfg.get("_mcp", "{}")
        self._mcp_cfg: dict = {}
        try:
            self._mcp_cfg = json.loads(mcp_raw) if isinstance(mcp_raw, str) else mcp_raw
        except Exception:
            pass
        self._client: Any = None
        self._tools: list[BaseTool] | None = None

    def _build_conn(self) -> dict[str, Any]:
        transport = self._mcp_cfg.get("transport", "sse")

        if transport in ("http", "streamable_http"):
            return {
                "transport": "http",
                "url": self._mcp_cfg.get("url", ""),
                "headers": self._mcp_cfg.get("headers") or None,
                "timeout": 15,
            }
        if transport == "sse":
            return {
                "transport": "sse",
                "url": self._mcp_cfg.get("url", ""),
                "headers": self._mcp_cfg.get("headers") or None,
                "timeout": 15,
            }
        # stdio — subprocess connector
        return {
            "transport": "stdio",
            "command": self._mcp_cfg.get("command", ""),
            "args": self._mcp_cfg.get("args") or [],
            "env": self._mcp_cfg.get("env") or None,
        }

    async def get_tools_async(self) -> list[BaseTool]:
        """Discover tools from the MCP server.

        On first call, launches the subprocess (stdio) or connects to the server
        (SSE/HTTP) and caches the client and tools. Subsequent calls return the
        cached tools without re-connecting, keeping the subprocess alive.
        """
        if self._tools is not None:
            return self._tools

        from langchain_mcp_adapters.client import MultiServerMCPClient

        conn = self._build_conn()
        client = MultiServerMCPClient({"engine": conn})  # type: ignore[dict-item]
        tools = await client.get_tools()
        logger.info("MCP engine connected — %d tools available", len(tools))

        # Keep a reference to prevent GC, which would close the subprocess on stdio transport.
        self._client = client
        self._tools = tools
        return tools

    def get_tools(self) -> list[BaseTool]:
        # Synchronous stub — callers must use get_tools_async() for MCP engines
        return []

    async def aclose(self) -> None:
        self._client = None
        self._tools = None
