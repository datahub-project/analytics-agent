from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from analytics_agent.context.base import ContextPlatform

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


class NativeDataHubPlatform(ContextPlatform):
    """Direct DataHub connection via REST/GraphQL.

    Tools are provided by the datahub_agent_context package (hardcoded schemas).
    disabled_tools and include_mutations are set at construction from the DB.
    """

    def __init__(
        self,
        name: str,
        url: str,
        token: str,
        disabled_tools: set[str] | None = None,
        include_mutations: bool = False,
    ) -> None:
        self.name = name
        self._url = url
        self._token = token
        self.disabled_tools = disabled_tools or set()
        self.include_mutations = include_mutations
        self._tools_cache: list[BaseTool] | None = None

    async def get_tools(self) -> list[BaseTool]:
        if self._tools_cache is not None:
            return [t for t in self._tools_cache if t.name not in self.disabled_tools]

        import asyncio
        import functools

        from analytics_agent.context.datahub import build_datahub_tools_for_connection

        # Build once, cache forever on this platform object.
        # DataHub SDK uses synchronous urllib3 — run in thread pool so it
        # doesn't freeze the async event loop during the initial build.
        loop = asyncio.get_event_loop()
        tools = await loop.run_in_executor(
            None,
            functools.partial(
                build_datahub_tools_for_connection, self._url, self._token, self.include_mutations
            ),
        )
        self._tools_cache = tools
        result = [t for t in tools if t.name not in self.disabled_tools]
        logger.info("NativeDataHub '%s': %d/%d tools active", self.name, len(result), len(tools))
        return result
