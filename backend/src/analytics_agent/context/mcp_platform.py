from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from analytics_agent.context.base import ContextPlatform

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


class MCPContextPlatform(ContextPlatform):
    """Context platform backed by an MCP server.

    Tools are discovered dynamically via MCP tools/list — NOT hardcoded.
    The server decides what tools it exposes; we respect disabled_tools set
    at construction from the DB.

    Each tool invocation manages its own connection lifecycle via
    langchain-mcp-adapters (no persistent connection needed).
    """

    def __init__(
        self,
        name: str,
        transport: str,
        url: str = "",
        headers: dict[str, Any] | None = None,
        command: str = "",
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        disabled_tools: set[str] | None = None,
        include_mutations: bool = False,
    ) -> None:
        self.name = name
        self._transport = transport
        self._url = url
        self._headers = headers or {}
        self._command = command
        self._args = args or []
        self._env = env or {}
        self.disabled_tools = disabled_tools or set()
        self.include_mutations = include_mutations
        self._tools_cache: list[BaseTool] | None = None

    # Canonical stub tool list used when ANALYTICS_AGENT_MOCK_MCP_TOOLS=1.
    # Covers both read and write names so tests can verify the read/write split.
    _MOCK_TOOLS = [
        "search",
        "get_entities",
        "list_schema_fields",
        "search_documents",
        "get_lineage",
        "get_dataset_queries",
        "grep_documents",
        "add_tags",
        "remove_tags",
        "update_description",
        "set_domains",
    ]

    async def get_tools(self) -> list[BaseTool]:
        """Discover tools from the MCP server and apply the platform's own disabled set."""
        if self._tools_cache is not None:
            return [t for t in self._tools_cache if t.name not in self.disabled_tools]

        from analytics_agent.config import settings

        if settings.mock_mcp_tools:
            from langchain_core.tools import StructuredTool

            stubs = [
                StructuredTool.from_function(
                    func=lambda **_: "mock",
                    name=n,
                    description=f"Mock tool: {n}",
                )
                for n in self._MOCK_TOOLS
            ]
            self._tools_cache = list(stubs)
            logger.info("MCP '%s': returning %d mock tools", self.name, len(stubs))
            return [t for t in stubs if t.name not in self.disabled_tools]

        from langchain_mcp_adapters.client import MultiServerMCPClient

        conn: dict[str, Any]
        if self._transport in ("http", "streamable_http"):
            conn = {
                "transport": "http",
                "url": self._url,
                "headers": self._headers or None,
                "timeout": 15,
            }
        elif self._transport == "sse":
            conn = {
                "transport": "sse",
                "url": self._url,
                "headers": self._headers or None,
                "timeout": 15,
            }
        else:
            conn = {
                "transport": "stdio",
                "command": self._command,
                "args": self._args,
                "env": self._env or None,
            }

        client = MultiServerMCPClient({self.name: conn})  # type: ignore[dict-item]
        all_tools = await client.get_tools()

        from analytics_agent.context.mcp_ui import wrap_tools_with_ui_resources

        connection_key = f"ctx:{self.name}"
        all_tools = await wrap_tools_with_ui_resources(
            connection_key, client, self.name, all_tools
        )

        self._tools_cache = all_tools
        result = [t for t in all_tools if t.name not in self.disabled_tools]
        logger.info(
            "MCP '%s' (%s): %d/%d tools active, disabled=%s",
            self.name,
            self._transport,
            len(result),
            len(all_tools),
            sorted(self.disabled_tools) or "none",
        )
        return result
