from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from analytics_agent.config import settings

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from datahub.sdk.main_client import DataHubClient
    from langchain_core.tools import BaseTool


def _get_db_datahub_credentials() -> tuple[str, str]:
    """Synchronously read the first active native DataHub platform from DB."""
    import contextlib

    import orjson

    try:
        import asyncio

        from analytics_agent.db.base import _get_session_factory
        from analytics_agent.db.repository import ContextPlatformRepo

        async def _fetch():
            from analytics_agent.config import DataHubPlatformConfig, parse_platform_config

            factory = _get_session_factory()
            async with factory() as session:
                platforms = await ContextPlatformRepo(session).list_all()
                for plat in platforms:
                    raw: dict = {}
                    with contextlib.suppress(Exception):
                        raw = orjson.loads(plat.config)
                    cfg = parse_platform_config(raw)
                    if isinstance(cfg, DataHubPlatformConfig) and cfg.url and cfg.token:
                        return cfg.url, cfg.token
            return "", ""

        loop = asyncio.get_event_loop()
        if loop.is_running():
            # In async context — can't use run_until_complete; return env var fallback
            return settings.get_datahub_config()
        return loop.run_until_complete(_fetch())
    except Exception:
        return settings.get_datahub_config()


def get_datahub_client() -> DataHubClient | None:
    """Return a DataHubClient for the first active native DataHub platform.

    Reads from DB (user-configured via Settings UI) with fallback to env vars.
    """
    import pathlib

    url, token = _get_db_datahub_credentials()
    has_config = bool(url and token)
    has_datahubenv = pathlib.Path("~/.datahubenv").expanduser().exists()
    if not has_config and not has_datahubenv:
        return None

    try:
        from datahub.sdk.main_client import DataHubClient
    except ImportError:
        return None

    if has_config:
        return DataHubClient(server=url, token=token)
    return DataHubClient.from_env()


# Lightweight schema-fields query — avoids the 42KB entity_details.gql that
# exceeds DataHub's 15K grammar-token limit on instances with large schemas.
_SCHEMA_FIELDS_GQL = """
query GetSchemaFields($urn: String!) {
  dataset(urn: $urn) {
    schemaMetadata {
      fields {
        fieldPath
        type
        nativeDataType
        nullable
        description
        label
        tags {
          tags {
            tag { urn properties { name description } }
          }
        }
        glossaryTerms {
          terms {
            term { urn properties { name description } }
          }
        }
      }
    }
  }
}
"""


def _list_schema_fields_lightweight(
    urn: str,
    keywords: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """list_schema_fields using a targeted query that avoids the grammar-token limit."""
    from datahub_agent_context.context import get_graph
    from datahub_agent_context.mcp_tools.base import execute_graphql

    graph = get_graph()
    result = execute_graphql(
        graph, query=_SCHEMA_FIELDS_GQL, variables={"urn": urn}, operation_name="GetSchemaFields"
    )
    dataset = result.get("dataset") or {}
    all_fields: list[dict] = (dataset.get("schemaMetadata") or {}).get("fields") or []
    total = len(all_fields)

    if not all_fields:
        return {
            "urn": urn,
            "fields": [],
            "totalFields": 0,
            "returned": 0,
            "remainingCount": 0,
            "matchingCount": None,
            "offset": offset,
        }

    kws = [k.lower() for k in keywords] if keywords else None
    matching_count = None

    if kws:

        def _score(f: dict) -> int:
            texts = [f.get("fieldPath", ""), f.get("description", ""), f.get("label", "")]
            for tag in (f.get("tags") or {}).get("tags") or []:
                texts.append(((tag.get("tag") or {}).get("properties") or {}).get("name", ""))
            for term in (f.get("glossaryTerms") or {}).get("terms") or []:
                texts.append(((term.get("term") or {}).get("properties") or {}).get("name", ""))
            return sum(1 for kw in kws for t in texts if t and kw in t.lower())

        matching_count = sum(1 for f in all_fields if _score(f) > 0)
        all_fields = sorted(all_fields, key=lambda f: (-_score(f), f.get("fieldPath", "")))

    page = all_fields[offset : offset + limit]
    remaining = total - offset - len(page)
    return {
        "urn": urn,
        "fields": page,
        "totalFields": total,
        "returned": len(page),
        "remainingCount": max(remaining, 0),
        "matchingCount": matching_count,
        "offset": offset,
    }


def _patch_schema_fields_tool(tools: list[BaseTool]) -> list[BaseTool]:
    """Replace the built-in list_schema_fields with our lightweight version."""
    from langchain_core.tools import StructuredTool

    patched: list[BaseTool] = []
    for t in tools:
        if t.name == "list_schema_fields":
            replacement = StructuredTool.from_function(
                func=_list_schema_fields_lightweight,
                name="list_schema_fields",
                description=t.description,
            )
            patched.append(replacement)
            logger.debug("Replaced list_schema_fields with lightweight schema query")
        else:
            patched.append(t)
    return patched


def build_datahub_tools_for_connection(
    url: str, token: str, include_mutations: bool = False
) -> list[BaseTool]:
    """Build DataHub tools from explicit URL + token (native REST/GraphQL transport)."""
    try:
        from datahub.sdk.main_client import DataHubClient
        from datahub_agent_context.langchain_tools import build_langchain_tools
    except ImportError as e:
        logger.warning("DataHub tools unavailable: %s", e)
        return []

    try:
        client = DataHubClient(server=url, token=token)
        tools = build_langchain_tools(client, include_mutations=include_mutations)
        tools = _patch_schema_fields_tool(tools)
        logger.info("Loaded %d DataHub tools (native) from %s", len(tools), url)
        return tools
    except Exception as e:
        logger.warning("Failed to build DataHub tools for %s: %s", url, e)
        return []


def build_datahub_tools(include_mutations: bool = False) -> list[BaseTool]:
    """
    Build DataHub context tools as LangChain tools.

    Uses datahub_agent_context.langchain_tools.build_langchain_tools which wraps
    each tool to automatically set/reset the DataHubClient in contextvars before
    and after execution — no manual context management needed in the agent.

    Returns empty list if DataHub is not configured or the package is not installed.
    """
    import pathlib

    url, token = settings.get_datahub_config()
    has_config = bool(url and token)
    has_datahubenv = pathlib.Path("~/.datahubenv").expanduser().exists()
    if not has_config and not has_datahubenv:
        logger.warning(
            "DataHub tools disabled: add a datahub entry to context_platforms in config.yaml, "
            "or run `datahub init` to write ~/.datahubenv"
        )
        return []

    client = get_datahub_client()
    if client is None:
        return []

    try:
        from datahub_agent_context.langchain_tools import build_langchain_tools
    except ImportError as e:
        logger.warning(
            "DataHub tools disabled: could not import datahub packages (%s). "
            "Install with: uv sync (datahub-agent-context must be available via uv.sources)",
            e,
        )
        return []

    tools = build_langchain_tools(client, include_mutations=include_mutations)
    tools = _patch_schema_fields_tool(tools)
    logger.info("Loaded %d DataHub context tools", len(tools))
    return tools
