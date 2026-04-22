"""MCP-backed query engine.

Tools are discovered dynamically via MCP tools/list — NOT hardcoded like
native SQL engines. The engine acts as an async context manager; connect it
before calling get_tools(), then keep the context alive for agent execution.

Usage in chat.py:
    async with stack.enter_async_context(mcp_engine):
        engine_tools = mcp_engine.get_tools()
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
        self._client = None

    async def get_tools_async(self) -> list[BaseTool]:
        """Discover tools from the MCP server.

        Each call creates a fresh connection via langchain-mcp-adapters.
        The returned tool objects manage their own per-call connection lifecycle.
        """
        from langchain_mcp_adapters.client import MultiServerMCPClient

        transport = self._mcp_cfg.get("transport", "sse")
        conn: dict[str, Any]

        if transport in ("http", "streamable_http"):
            conn = {
                "transport": "http",
                "url": self._mcp_cfg.get("url", ""),
                "headers": self._mcp_cfg.get("headers") or None,
                "timeout": 15,
            }
        elif transport == "sse":
            conn = {
                "transport": "sse",
                "url": self._mcp_cfg.get("url", ""),
                "headers": self._mcp_cfg.get("headers") or None,
                "timeout": 15,
            }
        else:
            conn = {
                "transport": "stdio",
                "command": self._mcp_cfg.get("command", ""),
                "args": self._mcp_cfg.get("args") or [],
                "env": self._mcp_cfg.get("env") or None,
            }

        client = MultiServerMCPClient({"engine": conn})  # type: ignore[dict-item]
        tools = await client.get_tools()
        logger.info("MCP engine provided %d tools", len(tools))
        return tools

    def get_tools(self) -> list[BaseTool]:
        # Synchronous stub — callers should use get_tools_async() for MCP engines
        return []
