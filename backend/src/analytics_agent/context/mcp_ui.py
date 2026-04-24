"""MCP UI helpers — client registry + tool wrapping.

Two responsibilities:
1. _mcp_clients registry: populated when a platform/engine is built; provides
   the MultiServerMCPClient reference that MCPResourceClient uses for
   resources/read calls.
2. wrap_tools_with_ui_resources(): called from both MCPContextPlatform.get_tools()
   and MCPQueryEngine.get_tools_async().  For every tool that advertises a
   _meta.ui.resourceUri, it:
     a. Kicks off an asyncio.create_task() prefetch of the resource into the disk
        cache so the cache is warm by the time the agent calls the tool.
     b. Replaces the tool with a wrapper that, after the underlying MCP tool/call
        returns, stuffs {tool_result, connection_key, tool_name, tool_input,
        resource_uri, csp, permissions} into _pending_apps and returns the short
        marker MCP_APP_READY:<app_id>.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

import orjson

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


_DEFAULT_UI_AGENT_INSTRUCTIONS = (
    "An interactive UI card has been rendered inline in the chat for the user to "
    "act on. Do not restate the options, do not call any other tools, and do not "
    "answer the user's question yet. Stop and wait for the user's next message."
)


def _extract_agent_instructions(content_blocks: list[dict]) -> str | None:
    """Return the `_agent_instructions` string from any JSON-bearing text block.

    MCP servers that render UI can embed `_agent_instructions` in their tool
    output so the host model knows to stop and wait for user interaction. Our
    wrapper previously swallowed the entire payload by returning only a marker,
    which meant the LLM never saw this directive and would happily call more
    tools. Surface it back into the tool's return value so it lands in the
    ToolMessage the agent reads.
    """
    for block in content_blocks:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text", "")
        if not isinstance(text, str) or "_agent_instructions" not in text:
            continue
        try:
            data = orjson.loads(text)
        except Exception:
            continue
        if isinstance(data, dict):
            instructions = data.get("_agent_instructions")
            if isinstance(instructions, str) and instructions.strip():
                return instructions.strip()
    return None


def register_mcp_client(
    connection_key: str,
    client: Any,
    server_name: str,
) -> None:
    """Register a MultiServerMCPClient in the shared registry (mcp_resources._mcp_clients)."""
    from analytics_agent.context.mcp_resources import _mcp_clients

    _mcp_clients[connection_key] = (client, server_name)
    logger.debug("Registered MCP client for connection_key=%s", connection_key)


def _get_ui_meta(tool: BaseTool) -> dict:
    """Extract _meta.ui from a LangChain tool's metadata (may be empty)."""
    meta = (tool.metadata or {}).get("_meta") or {}
    if isinstance(meta, dict):
        return meta.get("ui") or {}
    return {}


async def _prefetch_resource(connection_key: str, uri: str) -> None:
    """Best-effort prefetch of a ui:// resource into the disk cache."""
    try:
        from analytics_agent.context.mcp_resources import resource_client

        await resource_client.read_ui_resource(connection_key, uri, use_cache=False)
        logger.debug("Prefetched MCP ui resource: connection=%s uri=%s", connection_key, uri)
    except Exception as exc:
        logger.warning(
            "MCP ui resource prefetch failed (connection=%s uri=%s): %s",
            connection_key,
            uri,
            exc,
        )


def _make_content_blocks(raw: Any) -> list[dict]:
    """Coerce an ainvoke() return value into standard MCP content blocks.

    The MCP Apps spec requires `ui/notifications/tool-result` params to be a
    CallToolResult (`{content: [{type, text, ...}, ...]}`). Preserve structured
    content so the iframe app can parse it; wrap plain strings as a single
    text block.
    """
    if isinstance(raw, list):
        blocks: list[dict] = []
        for block in raw:
            if isinstance(block, dict):
                blocks.append(block)
            elif isinstance(block, str):
                blocks.append({"type": "text", "text": block})
        return blocks
    if isinstance(raw, str):
        return [{"type": "text", "text": raw}]
    return [{"type": "text", "text": str(raw)}]


def _wrap_tool(
    original: BaseTool,
    connection_key: str,
    server_name: str,
    resource_uri: str,
    csp: str | None,
    permissions: list[str],
    allowed_tools: list[str],
) -> BaseTool:
    """Return a new StructuredTool that calls original then stuffs _pending_apps."""
    from langchain_core.tools import StructuredTool

    from analytics_agent.agent.mcp_app_tool import PendingApp, _pending_apps

    tool_name = original.name

    async def _wrapper(**kwargs: Any) -> str:
        raw = await original.ainvoke(kwargs)
        content_blocks = _make_content_blocks(raw)

        app_id = str(uuid.uuid4())
        _pending_apps[app_id] = PendingApp(
            app_id=app_id,
            connection_key=connection_key,
            server_name=server_name,
            tool_name=tool_name,
            tool_input=dict(kwargs),
            tool_result=content_blocks,
            resource_uri=resource_uri,
            csp=csp,
            permissions=list(permissions),
            allowed_tools=list(allowed_tools),
        )
        # Preserve the server-provided `_agent_instructions` (or fall back to a
        # sensible default) so the LLM actually receives a directive to stop
        # and wait for the user. streaming.py still parses the leading
        # `MCP_APP_READY:<app_id>` marker on the first line.
        instructions = (
            _extract_agent_instructions(content_blocks)
            or _DEFAULT_UI_AGENT_INSTRUCTIONS
        )
        return f"MCP_APP_READY:{app_id} ({tool_name})\n{instructions}"

    return StructuredTool(
        name=original.name,
        description=original.description,
        args_schema=original.args_schema,
        coroutine=_wrapper,
        metadata=original.metadata,
    )


async def wrap_tools_with_ui_resources(
    connection_key: str,
    client: Any,
    server_name: str,
    tools: list[BaseTool],
) -> list[BaseTool]:
    """Register the client and wrap any UI-bearing tools.

    For each tool whose MCP descriptor carries _meta.ui.resourceUri:
      - Kick off an asyncio.create_task() prefetch into the disk cache.
      - Replace the tool with a wrapper that emits MCP_APP_READY:<app_id>.

    Tools without a resourceUri are returned unchanged.
    """
    register_mcp_client(connection_key, client, server_name)

    # Collect all tool names on this connection for the Phase 2 allow-list.
    all_tool_names = [t.name for t in tools]

    result: list[BaseTool] = []
    for tool in tools:
        ui_meta = _get_ui_meta(tool)
        resource_uri: str | None = ui_meta.get("resourceUri")
        if not resource_uri:
            result.append(tool)
            continue

        csp: str | None = ui_meta.get("csp")
        permissions: list[str] = ui_meta.get("permissions") or []

        # Fire-and-forget prefetch so the cache is warm before the agent calls the tool.
        asyncio.create_task(
            _prefetch_resource(connection_key, resource_uri),
            name=f"mcp-prefetch-{connection_key}-{tool.name}",
        )

        wrapped = _wrap_tool(
            tool, connection_key, server_name, resource_uri, csp, permissions, all_tool_names
        )
        result.append(wrapped)
        logger.info(
            "MCP tool '%s' wrapped with UI resource: %s", tool.name, resource_uri
        )

    return result
