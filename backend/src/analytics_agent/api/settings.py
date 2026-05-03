from __future__ import annotations

import contextlib
import ipaddress
import os
import pathlib
import urllib.parse
from typing import Any, Literal

import orjson
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from analytics_agent.db.base import get_session
from analytics_agent.db.repository import ContextPlatformRepo, SettingsRepo

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _validate_mcp_url(url: str) -> None:
    """Raise HTTPException 400 if url targets a link-local (SSRF-risk) address."""
    if not url:
        return
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail=f"MCP URL scheme must be http or https, got: {parsed.scheme!r}",
        )
    host = parsed.hostname or ""
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_link_local:
            raise HTTPException(
                status_code=400,
                detail=f"MCP URL must not target link-local addresses (got {host})",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # not a bare IP (ValueError from DNS hostname) — allow


# Settings keys stored in DB
_KEY_PROMPT = "system_prompt"
_KEY_DISPLAY = "display"
_KEY_DISABLED_TOOLS = "disabled_tools"
_KEY_DISABLED_TOOLS_PER_CP = "disabled_tools_per_cp"  # {conn_name: [tool_names]}
_KEY_ENABLED_MUTATIONS = "enabled_mutation_tools"
_KEY_DISABLED_CONNECTIONS = "disabled_connections"
_KEY_DYNAMIC_CONNECTIONS = "dynamic_connections"

# Write-back skills are opt-in (disabled unless explicitly enabled)
_SKILL_TOOL_NAMES: set[str] = {
    "publish_analysis",
    "save_correction",
}
# Keep alias for backwards compat with existing code that references _MUTATION_TOOL_NAMES
_MUTATION_TOOL_NAMES = _SKILL_TOOL_NAMES


# --- Models ---


class ConnectionField(BaseModel):
    key: str
    label: str
    value: str
    sensitive: bool = False
    placeholder: str = ""
    # When non-empty, the frontend routes this field's value to
    # ``body.secrets[secret_key]`` instead of ``body.config[key]`` on save.
    # ``secret_key`` must appear in the engine's ``QueryEngine.secret_env_vars``.
    secret_key: str = ""


class ToolToggle(BaseModel):
    name: str
    label: str
    enabled: bool = True
    description: str = ""  # shown as hover tooltip in the UI


class OAuthStatus(BaseModel):
    available: bool = False  # OAuth app (client_id/secret) is configured
    connected: bool = False  # User has a valid token
    username: str = ""
    expires_at: str = ""
    expired: bool = False


class ConnectionStatus(BaseModel):
    name: str
    type: str
    label: str
    status: str  # "connected" | "error" | "unconfigured"
    error: str = ""
    fields: list[ConnectionField]
    tools: list[ToolToggle] = []
    oauth: OAuthStatus = OAuthStatus()
    source: str = "yaml"  # "yaml" | "ui"
    disabled: bool = False  # master toggle — connection fully off


class McpConfigRequest(BaseModel):
    transport: Literal["http", "sse", "stdio"] = "http"
    command: str = ""
    args: list[str] = []
    env: dict[str, str] = {}
    url: str = ""
    headers: dict[str, str] = {}


class CreateConnectionRequest(BaseModel):
    name: str
    type: str
    label: str = ""
    config: dict[str, str] = {}
    secrets: dict[str, str] | None = None
    category: str = "engine"  # "engine" | "context_platform"
    mcp_config: McpConfigRequest | None = None


class UpdateConnectionRequest(BaseModel):
    """Update payload for a connection.

    ``config`` values are merged into ``integrations.config`` (or the context
    platform's config JSON). ``secrets`` keys are translated through the
    engine's own ``QueryEngine.secret_env_vars`` allow-list and written to
    ``.env`` + ``os.environ``.
    """

    config: dict[str, str] = {}
    secrets: dict[str, str] = {}


class UpdateToolsRequest(BaseModel):
    disabled_tools: list[str]
    enabled_mutations: list[str] = []
    disabled_connections: list[str] = []
    disabled_tools_per_cp: dict[str, list[str]] = {}  # {conn_name: [tool_names]}


class DataHubCoverageResponse(BaseModel):
    covered: bool
    dataset_count: int
    platform: str | None = None


class DataHubCheckResult(BaseModel):
    name: str
    label: str
    success: bool
    message: str = ""


class DataHubTestResponse(BaseModel):
    success: bool
    checks: list[DataHubCheckResult] = []
    error: str = ""
    message: str = ""


class PromptContent(BaseModel):
    content: str
    is_custom: bool = False


class UpdatePromptRequest(BaseModel):
    content: str


class DisplaySettings(BaseModel):
    app_name: str = "Analytics Agent"
    logo_url: str = ""


class UpdateDisplayRequest(BaseModel):
    app_name: str = ""
    logo_url: str = ""


# --- Known tools per connection type ---

_DATAHUB_TOOLS = [
    {"name": "search_documents", "label": "Search documentation"},
    {"name": "grep_documents", "label": "Grep document content"},
    {"name": "search", "label": "Search datasets"},
    {"name": "get_entities", "label": "Get entity metadata"},
    {"name": "list_schema_fields", "label": "List schema fields"},
    {"name": "get_lineage", "label": "Data lineage"},
    {"name": "get_dataset_queries", "label": "Query history"},
    {"name": "publish_analysis", "label": "Publish analysis to DataHub"},
    {"name": "save_correction", "label": "Save correction to DataHub"},
]

_KNOWN_TOOLS: dict[str, list[dict]] = {
    "datahub": _DATAHUB_TOOLS,
    "datahub-mcp": _DATAHUB_TOOLS,  # same capabilities, different transport
    "bigquery": [
        {"name": "list_tables", "label": "List tables"},
        {"name": "get_schema", "label": "Table schema"},
        {"name": "preview_table", "label": "Preview data"},
        {"name": "execute_sql", "label": "Execute SQL"},
    ],
    "snowflake": [
        {"name": "list_tables", "label": "List tables"},
        {"name": "get_schema", "label": "Table schema"},
        {"name": "preview_table", "label": "Preview data"},
        {"name": "execute_sql", "label": "Execute SQL"},
    ],
    "mysql": [
        {"name": "list_tables", "label": "List tables"},
        {"name": "get_schema", "label": "Table schema"},
        {"name": "preview_table", "label": "Preview data"},
        {"name": "execute_sql", "label": "Execute SQL"},
    ],
    "sqlalchemy": [
        {"name": "list_tables", "label": "List tables"},
        {"name": "get_schema", "label": "Table schema"},
        {"name": "preview_table", "label": "Preview data"},
        {"name": "execute_sql", "label": "Execute SQL"},
    ],
    "chart": [
        {"name": "create_chart", "label": "Create visualizations"},
    ],
}


def _build_tool_toggles(
    connection_type: str,
    disabled: set[str],
    enabled_mutations: set[str] | None = None,
) -> list[ToolToggle]:
    result = []
    for t in _KNOWN_TOOLS.get(connection_type, []):
        name = t["name"]
        if name in _MUTATION_TOOL_NAMES:
            # Mutation tools are opt-in: only enabled when explicitly turned on
            is_enabled = enabled_mutations is not None and name in enabled_mutations
        else:
            is_enabled = name not in disabled
        result.append(ToolToggle(name=name, label=t["label"], enabled=is_enabled))
    return result


# --- Connection helpers ---


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "•" * (len(value) - 8) + value[-4:]


async def _get_datahub_connections(
    session: AsyncSession,
    disabled: set[str],
    enabled_mutations: set[str] | None = None,
) -> list[ConnectionStatus]:
    """Return a ConnectionStatus for each DataHub platform in the DB.

    Falls back to config.yaml / env vars / ~/.datahubenv when the DB has no rows.
    """
    from analytics_agent.config import settings

    repo = ContextPlatformRepo(session)
    platforms = await repo.list_all()

    if platforms:
        from analytics_agent.config import DataHubMCPConfig, parse_platform_config

        results = []
        for plat in platforms:
            raw: dict = {}
            with contextlib.suppress(Exception):
                raw = orjson.loads(plat.config)

            cfg = parse_platform_config(raw)
            per_conn_disabled: set[str] = set(raw.get("_disabled_tools") or [])

            if isinstance(cfg, DataHubMCPConfig):
                token = cfg.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                # stdio: configured when a command is set; http/sse: configured when url is set
                if cfg.transport == "stdio":
                    status = "connected" if cfg.command else "unconfigured"
                else:
                    status = "connected" if cfg.url else "unconfigured"
                if cfg.transport == "stdio":
                    # stdio connections are configured via command/args — no URL/token to show
                    fields = []
                else:
                    fields = [
                        ConnectionField(
                            key="url",
                            label="MCP server URL",
                            value=cfg.url,
                            placeholder="https://<tenant>.acryl.io/integrations/ai/mcp/",
                        ),
                        ConnectionField(
                            key="token",
                            label="Access token",
                            value=_mask(token),
                            sensitive=True,
                            placeholder="eyJhbGci...",
                        ),
                    ]
                if "_discovered_tools" in raw:
                    tool_toggles = [
                        ToolToggle(
                            name=t["name"],
                            label=t["name"],
                            description=t.get("description", "")[:200],
                            enabled=t["name"] not in per_conn_disabled,
                        )
                        for t in raw["_discovered_tools"]
                    ]
                else:
                    tool_toggles = []
            else:
                url = cfg.url
                token = cfg.token
                status = "unconfigured" if not (url and token) else "connected"
                fields = [
                    ConnectionField(
                        key="url",
                        label="GMS URL",
                        value=url,
                        placeholder="https://your-instance.acryl.io/gms",
                    ),
                    ConnectionField(
                        key="token",
                        label="Access Token",
                        value=_mask(token),
                        sensitive=True,
                        placeholder="eyJhbGci...",
                    ),
                ]
                all_tools = _KNOWN_TOOLS.get(plat.type, [])
                tool_toggles = [
                    ToolToggle(
                        name=t["name"],
                        label=t["label"],
                        enabled=(
                            t["name"] in (enabled_mutations or set())
                            if t["name"] in _MUTATION_TOOL_NAMES
                            else t["name"] not in per_conn_disabled
                        ),
                    )
                    for t in all_tools
                ]

            results.append(
                ConnectionStatus(
                    name=plat.name,
                    type=plat.type,
                    label=plat.label or "DataHub",
                    status=status,
                    source=plat.source,
                    fields=fields,
                    tools=tool_toggles,
                )
            )
        return results

    # No DB rows — fall back to config.yaml → env vars → ~/.datahubenv
    url, token = settings.get_datahub_config()
    url = url or ""
    token = token or ""
    if not url or not token:
        env_path = pathlib.Path("~/.datahubenv").expanduser()
        if env_path.exists():
            import yaml

            data = yaml.safe_load(env_path.read_text())
            gms = data.get("gms", {})
            url = url or gms.get("server", "")
            token = token or gms.get("token", "")

    status = "unconfigured" if not (url and token) else "connected"
    return [
        ConnectionStatus(
            name="default",
            type="datahub",
            label="DataHub",
            status=status,
            source="yaml",
            fields=[
                ConnectionField(
                    key="url",
                    label="GMS URL",
                    value=url,
                    placeholder="https://your-instance.acryl.io/gms",
                ),
                ConnectionField(
                    key="token",
                    label="Access Token",
                    value=_mask(token),
                    sensitive=True,
                    placeholder="eyJhbGci...",
                ),
            ],
            tools=_build_tool_toggles("datahub", disabled, enabled_mutations),
        )
    ]


def _get_engine_connections(disabled: set[str]) -> list[ConnectionStatus]:
    from analytics_agent.config import settings

    conns = []
    for cfg in settings.load_engines_config():
        engine_type = cfg.type
        name = cfg.effective_name
        connection = cfg.connection

        if engine_type == "bigquery":
            project = connection.get("project", "")
            dataset = connection.get("dataset", "")
            creds_json = os.environ.get("BIGQUERY_CREDENTIALS_JSON", "") or connection.get(
                "credentials_json", ""
            )
            creds_path = connection.get("credentials_path", "")
            creds_b64 = connection.get("credentials_base64", "")
            has_creds = bool(creds_json or creds_path or creds_b64)
            configured = bool(project and has_creds)
            conns.append(
                ConnectionStatus(
                    name=name,
                    type="bigquery",
                    label=f"BigQuery ({name})",
                    status="connected" if configured else "unconfigured",
                    fields=[
                        ConnectionField(
                            key="project",
                            label="GCP Project ID",
                            value=project,
                            placeholder="my-gcp-project",
                        ),
                        ConnectionField(
                            key="dataset",
                            label="Default Dataset",
                            value=dataset,
                            placeholder="my_dataset",
                        ),
                        ConnectionField(
                            key="credentials_json",
                            label="Service Account JSON",
                            value="(configured)" if has_creds else "",
                            sensitive=True,
                            secret_key="credentials_json",
                            placeholder='{"type":"service_account",...}',
                        ),
                    ],
                    tools=_build_tool_toggles("bigquery", disabled),
                )
            )
        elif engine_type == "snowflake":
            account = connection.get("account", "")
            user = connection.get("user", "")
            warehouse = connection.get("warehouse", "")
            database = connection.get("database", "")
            schema = connection.get("schema", "")
            password = os.environ.get("SNOWFLAKE_PASSWORD", "")
            private_key_pem = os.environ.get("SNOWFLAKE_PRIVATE_KEY", "").strip().strip('"')
            configured = bool(account and user and (password or private_key_pem))
            conns.append(
                ConnectionStatus(
                    name=name,
                    type="snowflake",
                    label=f"Snowflake ({name})",
                    status="connected" if configured else "unconfigured",
                    fields=[
                        ConnectionField(
                            key="account",
                            label="Account",
                            value=account,
                            placeholder="xy12345.us-east-1",
                        ),
                        ConnectionField(
                            key="user", label="User", value=user, placeholder="svc_user"
                        ),
                        ConnectionField(
                            key="warehouse",
                            label="Warehouse",
                            value=warehouse,
                            placeholder="COMPUTE_WH",
                        ),
                        ConnectionField(
                            key="database",
                            label="Database",
                            value=database,
                            placeholder="PROD",
                        ),
                        ConnectionField(
                            key="schema",
                            label="Schema",
                            value=schema,
                            placeholder="PUBLIC",
                        ),
                        ConnectionField(
                            key="password",
                            label="Password",
                            value=_mask(password),
                            sensitive=True,
                            secret_key="password",
                            placeholder="••••••••",
                        ),
                    ],
                    tools=_build_tool_toggles("snowflake", disabled),
                )
            )

    conns.append(
        ConnectionStatus(
            name="chart",
            type="chart",
            label="Visualization",
            status="connected",
            fields=[],
            tools=_build_tool_toggles("chart", disabled),
        )
    )
    return conns


async def _get_disabled_tools(repo: SettingsRepo) -> set[str]:
    raw = await repo.get(_KEY_DISABLED_TOOLS)
    if raw:
        try:
            return set(orjson.loads(raw))
        except Exception:
            pass
    return set()


async def _get_disabled_connections(repo: SettingsRepo) -> set[str]:
    raw = await repo.get(_KEY_DISABLED_CONNECTIONS)
    if raw:
        try:
            return set(orjson.loads(raw))
        except Exception:
            pass
    return set()


async def _get_enabled_mutations(repo: SettingsRepo) -> set[str]:
    raw = await repo.get(_KEY_ENABLED_MUTATIONS)
    if raw:
        try:
            return set(orjson.loads(raw))
        except Exception:
            pass
    return set()


# --- Connection endpoints ---


@router.get("/connections", response_model=list[ConnectionStatus])
async def list_connections(session: AsyncSession = Depends(get_session)):
    from analytics_agent.db.repository import CredentialRepo, IntegrationRepo

    settings_repo = SettingsRepo(session)
    integration_repo = IntegrationRepo(session)
    cred_repo = CredentialRepo(session)
    disabled = await _get_disabled_tools(settings_repo)
    enabled_mutations = await _get_enabled_mutations(settings_repo)
    disabled_connections = await _get_disabled_connections(settings_repo)

    # DataHub context platforms (from DB, seeded from config.yaml)
    connections: list[ConnectionStatus] = []
    cp_conns = await _get_datahub_connections(session, disabled, enabled_mutations)
    for cp in cp_conns:
        cp.disabled = cp.name in disabled_connections
    connections.extend(cp_conns)

    # Engine connections from integrations table
    integrations = await integration_repo.list_all()
    for intg in integrations:
        cred = await cred_repo.get(intg.name)

        # Determine connection status from env vars (same logic as before)
        conn_cfg = {}
        with contextlib.suppress(Exception):
            conn_cfg = orjson.loads(intg.config)

        is_sso_connected = cred is not None and cred.auth_type == "sso_externalbrowser"

        if intg.type == "snowflake":
            account = conn_cfg.get("account", "")
            user = conn_cfg.get("user", "")
            password = os.environ.get("SNOWFLAKE_PASSWORD", "")
            private_key = os.environ.get("SNOWFLAKE_PRIVATE_KEY", "").strip().strip('"')
            # SSO-only connections don't need a service user or password
            if is_sso_connected:
                has_creds = bool(account)
            else:
                has_creds = bool(account and user and (password or private_key))
            status_str = "connected" if has_creds else "unconfigured"
            fields = [
                ConnectionField(
                    key="account",
                    label="Snowflake URL / Account ID",
                    value=account,
                    placeholder="https://app.snowflake.com/org/account  or  acct-12345",
                ),
                ConnectionField(
                    key="user", label="Service User", value=user, placeholder="svc_user"
                ),
                ConnectionField(
                    key="warehouse",
                    label="Warehouse",
                    value=conn_cfg.get("warehouse", ""),
                    placeholder="COMPUTE_WH",
                ),
                ConnectionField(
                    key="database",
                    label="Database",
                    value=conn_cfg.get("database", ""),
                    placeholder="PROD",
                ),
                ConnectionField(
                    key="schema",
                    label="Schema",
                    value=conn_cfg.get("schema", ""),
                    placeholder="PUBLIC",
                ),
            ]
            if intg.source == "yaml":
                # Password field only for yaml connections (managed via env)
                fields.append(
                    ConnectionField(
                        key="password",
                        label="Password",
                        value=_mask(password),
                        sensitive=True,
                        secret_key="password",  # → body.secrets.password → SNOWFLAKE_PASSWORD
                        placeholder="••••••••",
                    )
                )
        elif intg.type == "bigquery":
            project = conn_cfg.get("project", "")
            dataset = conn_cfg.get("dataset", "")
            creds_json = os.environ.get("BIGQUERY_CREDENTIALS_JSON", "") or conn_cfg.get(
                "credentials_json", ""
            )
            creds_path = conn_cfg.get("credentials_path", "")
            creds_b64 = conn_cfg.get("credentials_base64", "")
            has_creds = bool(creds_json or creds_path or creds_b64)
            status_str = "connected" if (project and has_creds) else "unconfigured"
            fields = [
                ConnectionField(
                    key="project",
                    label="GCP Project ID",
                    value=project,
                    placeholder="my-gcp-project",
                ),
                ConnectionField(
                    key="dataset",
                    label="Default Dataset",
                    value=dataset,
                    placeholder="my_dataset",
                ),
                ConnectionField(
                    key="credentials_json",
                    label="Service Account JSON",
                    value="(configured)" if has_creds else "",
                    sensitive=True,
                    secret_key="credentials_json",
                    placeholder='{"type":"service_account",...}',
                ),
            ]
        elif intg.type in ("mysql", "sqlalchemy", "postgresql", "sqlite"):
            host = conn_cfg.get("host", "")
            database = conn_cfg.get("database", conn_cfg.get("db", ""))
            port = str(conn_cfg.get("port", ""))
            user = conn_cfg.get("user", conn_cfg.get("username", ""))
            has_url = bool(conn_cfg.get("url"))
            status_str = "connected" if (has_url or (host and database)) else "unconfigured"
            if has_url:
                fields = [
                    ConnectionField(
                        key="url",
                        label="Connection URL",
                        value="(configured)",
                        sensitive=True,
                        placeholder="dialect://user:pass@host/db",
                    )
                ]
            else:
                fields = [
                    f
                    for f in [
                        ConnectionField(
                            key="host", label="Host", value=host, placeholder="localhost"
                        )
                        if host
                        else None,
                        ConnectionField(key="port", label="Port", value=port, placeholder="3306")
                        if port
                        else None,
                        ConnectionField(
                            key="database", label="Database", value=database, placeholder="mydb"
                        )
                        if database
                        else None,
                        ConnectionField(
                            key="user", label="User", value=user, placeholder="username"
                        )
                        if user
                        else None,
                    ]
                    if f is not None
                ]
        else:
            status_str = "unconfigured"
            fields = []

        oauth_status = (
            OAuthStatus(
                available=True,  # SSO always available for engine connections
                connected=is_sso_connected,
                username=cred.username or "" if cred else "",
                expires_at="",
                expired=False,
            )
            if intg.type == "snowflake"
            else OAuthStatus()
        )

        connections.append(
            ConnectionStatus(
                name=intg.name,
                type=intg.type,
                label=intg.label,
                status=status_str,
                fields=fields,
                tools=_build_tool_toggles(intg.type, disabled),
                oauth=oauth_status,
                source=intg.source,
            )
        )

    # Chart tool (virtual)
    connections.append(
        ConnectionStatus(
            name="chart",
            type="chart",
            label="Visualization",
            status="connected",
            fields=[],
            tools=_build_tool_toggles("chart", disabled),
        )
    )

    return connections


_CONTEXT_PLATFORM_TYPES = {"datahub"}


@router.post("/connections", status_code=201)
async def create_connection(
    body: CreateConnectionRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    import uuid

    from analytics_agent.db.repository import IntegrationRepo
    from analytics_agent.engines.factory import register_engine

    # Validate name
    name = body.name.strip().lower().replace(" ", "-")
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(
            status_code=400, detail="Name must be alphanumeric (hyphens/underscores ok)"
        )

    _type_labels: dict[str, str] = {
        "datahub-mcp": "DataHub over MCP",
        "datahub": "DataHub",
    }
    label = body.label or f"{_type_labels.get(body.type, body.type.capitalize())} ({name})"

    # Build config — merge flat fields + serialized MCP config if present
    conn_cfg = dict(body.config)
    if body.mcp_config:
        from analytics_agent.config import DataHubMCPConfig

        transport = body.mcp_config.transport or "http"
        url = body.mcp_config.url or ""
        if transport in ("http", "sse", "streamable_http"):
            _validate_mcp_url(url)
        headers = dict(body.mcp_config.headers or {})
        # token from conn_cfg["token"] → Authorization header
        if conn_cfg.get("token"):
            headers["Authorization"] = f"Bearer {conn_cfg.pop('token')}"
        mcp_cfg = DataHubMCPConfig(
            type="datahub-mcp",
            transport=transport,
            url=url,
            headers=headers,
            command=body.mcp_config.command or "",
            args=list(body.mcp_config.args or []),
            env=dict(body.mcp_config.env or {}),
        )
        conn_cfg = mcp_cfg.model_dump()

    # Context platforms go to context_platforms table
    if body.type in _CONTEXT_PLATFORM_TYPES or body.category == "context_platform":
        cp_repo = ContextPlatformRepo(session)
        existing_cp = await cp_repo.get(name)
        if existing_cp:
            raise HTTPException(status_code=409, detail=f"Connection '{name}' already exists")
        await cp_repo.upsert(
            id=str(uuid.uuid4()),
            type=body.type,
            name=name,
            label=label,
            config=orjson.dumps(conn_cfg).decode(),
            source="ui",
        )
        # Propagate DataHub credentials to env for immediate effect
        if body.type == "datahub":
            if conn_cfg.get("url"):
                os.environ["DATAHUB_GMS_URL"] = conn_cfg["url"]
            if conn_cfg.get("token"):
                os.environ["DATAHUB_GMS_TOKEN"] = conn_cfg["token"]

        # MCP connections: discover tools in background so they appear on first load
        if body.mcp_config:
            import asyncio as _asyncio

            from analytics_agent.config import DataHubMCPConfig as _MCPCfg

            _typed = _MCPCfg.model_validate(conn_cfg)
            _conn_name = name

            async def _discover_on_save() -> None:
                import logging as _log

                _logger = _log.getLogger(__name__)
                try:
                    from analytics_agent.context.mcp_platform import MCPContextPlatform
                    from analytics_agent.db.base import _get_session_factory
                    from analytics_agent.db.repository import ContextPlatformRepo as _CPR

                    platform = MCPContextPlatform(
                        name=_conn_name,
                        transport=_typed.transport,
                        url=_typed.url,
                        headers=_typed.headers,
                        command=_typed.command,
                        args=_typed.args,
                        env=_typed.env,
                    )
                    _logger.info("Tool discovery started for '%s'", _conn_name)
                    tools = await _asyncio.wait_for(platform.get_tools(), timeout=15)
                    schemas = [
                        {"name": t.name, "description": t.description or t.name} for t in tools
                    ]
                    sf = _get_session_factory()
                    async with sf() as ws:
                        row = await _CPR(ws).get(_conn_name)
                        if row:
                            stored = orjson.loads(row.config)
                            stored["_discovered_tools"] = schemas
                            row.config = orjson.dumps(stored).decode()
                            await ws.commit()
                    _logger.info(
                        "Tool discovery complete for '%s': %d tools", _conn_name, len(tools)
                    )
                except Exception as _e:
                    _logger.warning("Tool discovery failed for '%s': %s", _conn_name, _e)

            _asyncio.create_task(_discover_on_save())

        return {"success": True, "name": name, "message": f"Connection '{name}' created."}

    # SQL engine connections go to integrations table
    repo = IntegrationRepo(session)
    existing = await repo.get(name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Connection '{name}' already exists")

    # Normalize Snowflake account URL → account identifier before saving
    if body.type == "snowflake" and conn_cfg.get("account"):
        import re as _re

        raw = conn_cfg["account"].strip()
        # app.snowflake.com/<org>/<account>
        m = _re.search(r"app\.snowflake\.com/([^/]+)/([^/#?]+)", raw, _re.IGNORECASE)
        if m:
            conn_cfg["account"] = f"{m.group(1)}-{m.group(2)}".lower()
        else:
            m = _re.match(r"https?://([^.]+)\.snowflakecomputing\.com", raw, _re.IGNORECASE)
            if m:
                conn_cfg["account"] = m.group(1)
            else:
                # Strip protocol/trailing path, keep the first segment
                cleaned = _re.sub(r"^https?://", "", raw, flags=_re.IGNORECASE)
                conn_cfg["account"] = cleaned.split(".")[0].split("/")[0]

    integration_id = str(uuid.uuid4())
    await repo.upsert(
        id=integration_id,
        name=name,
        type=body.type,
        label=label,
        config=orjson.dumps(conn_cfg).decode(),
        source="ui",
    )

    # If the caller supplied secrets, translate and persist them to .env now.
    if body.secrets:
        secret_env_vars = _resolve_secrets(body.type, body.secrets)
        if secret_env_vars:
            env_path = _find_env_file()
            _upsert_env_vars(env_path, secret_env_vars)
            for k, v in secret_env_vars.items():
                os.environ[k] = v

    register_engine(name, body.type, conn_cfg)
    return {"success": True, "name": name, "message": f"Connection '{name}' created."}


@router.patch("/connections/{name}/tools")
async def update_connection_tools(
    name: str, body: dict, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Save the per-connection disabled tool list into the platform's config JSON.

    This keeps disabled_tools state inside the platform object (OO) rather than
    in a global map. The platform reads it from DB at construction time.
    """
    disabled: list[str] = body.get("disabled_tools", [])

    # Check context platforms first
    cp_repo = ContextPlatformRepo(session)
    cp = await cp_repo.get(name)
    if cp:
        cfg: dict = {}
        with contextlib.suppress(Exception):
            cfg = orjson.loads(cp.config)
        cfg["_disabled_tools"] = disabled
        cp.config = orjson.dumps(cfg).decode()
        from analytics_agent.db.models import utcnow

        cp.updated_at = utcnow()
        await session.commit()
        return {"success": True, "message": f"Tool settings saved for '{name}'."}

    # Engines (future): store in integration config
    from analytics_agent.db.repository import IntegrationRepo

    repo = IntegrationRepo(session)
    intg = await repo.get(name)
    if intg:
        cfg = {}
        with contextlib.suppress(Exception):
            cfg = orjson.loads(intg.config)
        cfg["_disabled_tools"] = disabled
        intg.config = orjson.dumps(cfg).decode()
        await session.commit()
        return {"success": True, "message": f"Tool settings saved for '{name}'."}

    raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")


@router.patch("/connections/{name}/label")
async def rename_connection(
    name: str, body: dict, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    from analytics_agent.db.repository import IntegrationRepo

    repo = IntegrationRepo(session)
    intg = await repo.get(name)
    if not intg:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    new_label = body.get("label", "").strip()
    if not new_label:
        raise HTTPException(status_code=400, detail="label cannot be empty")
    intg.label = new_label
    from analytics_agent.db.models import utcnow

    intg.updated_at = utcnow()
    await session.commit()
    return {"success": True, "label": new_label}


@router.delete("/connections/{name}")
async def delete_connection(
    name: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    from analytics_agent.db.repository import IntegrationRepo
    from analytics_agent.engines.factory import unregister_engine

    # Check context platforms first
    cp_repo = ContextPlatformRepo(session)
    cp = await cp_repo.get(name)
    if cp:
        if cp.source == "yaml":
            raise HTTPException(
                status_code=400,
                detail="Config-file connections cannot be deleted from the UI. Remove from config.yaml instead.",
            )
        await cp_repo.delete(name)
        return {"success": True, "message": f"Connection '{name}' deleted."}

    # Fall through to engine integrations
    repo = IntegrationRepo(session)
    intg = await repo.get(name)
    if not intg:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    if intg.source == "yaml":
        raise HTTPException(
            status_code=400,
            detail="Config-file connections cannot be deleted from the UI. Remove from config.yaml instead.",
        )

    await repo.delete(name)
    unregister_engine(name)
    return {"success": True, "message": f"Connection '{name}' deleted."}


async def _test_context_platform(plat) -> DataHubTestResponse:
    """Test a ContextPlatform DB row — native DataHub or MCP variant."""
    from analytics_agent.config import DataHubMCPConfig, parse_platform_config

    raw: dict = {}
    with contextlib.suppress(Exception):
        raw = orjson.loads(plat.config)

    typed_cfg = parse_platform_config(raw)

    if isinstance(typed_cfg, DataHubMCPConfig):
        import asyncio

        import httpx

        # stdio transport: skip HTTP reachability check, go straight to tool discovery
        if typed_cfg.transport == "stdio":
            if not typed_cfg.command:
                return DataHubTestResponse(
                    success=False, error="No command configured for stdio MCP server."
                )
            try:
                from analytics_agent.context.mcp_platform import MCPContextPlatform

                platform = MCPContextPlatform(
                    name=plat.name,
                    transport=typed_cfg.transport,
                    url="",
                    headers={},
                    command=typed_cfg.command,
                    args=typed_cfg.args,
                    env=typed_cfg.env,
                )
                tools = await asyncio.wait_for(platform.get_tools(), timeout=30)
                tool_schemas = [
                    {"name": t.name, "description": t.description or t.name} for t in tools
                ]
                raw["_discovered_tools"] = tool_schemas

                async def _cache_stdio() -> None:
                    from analytics_agent.db.base import _get_session_factory
                    from analytics_agent.db.repository import ContextPlatformRepo as _CPR

                    sf = _get_session_factory()
                    async with sf() as ws:
                        row = await _CPR(ws).get(plat.name)
                        if row:
                            row.config = orjson.dumps(raw).decode()
                            await ws.commit()

                await _cache_stdio()  # write before response so refresh sees the tools
                return DataHubTestResponse(
                    success=True,
                    message=f"Connected via stdio — {len(tools)} tools discovered",
                    checks=[
                        DataHubCheckResult(
                            name="tools",
                            label="Tools discovered",
                            success=True,
                            message=", ".join(t.name for t in tools[:5])
                            + (f" (+{len(tools) - 5} more)" if len(tools) > 5 else ""),
                        )
                    ],
                )
            except TimeoutError:
                return DataHubTestResponse(
                    success=False,
                    error="stdio subprocess timed out (>30s) — is uvx/mcp-server-datahub installed?",
                )
            except Exception as e:
                return DataHubTestResponse(success=False, error=str(e)[:300])

        url = typed_cfg.url
        headers = typed_cfg.headers
        if not url:
            return DataHubTestResponse(success=False, error="No MCP server URL configured.")

        # Phase 1 — fast reachability check (HTTP GET, 5 s timeout)
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=True) as hc:
                resp = await hc.get(url, headers=headers)
            if resp.status_code >= 500:
                return DataHubTestResponse(
                    success=False,
                    error=f"MCP server returned HTTP {resp.status_code}",
                )
        except Exception as e:
            return DataHubTestResponse(success=False, error=f"MCP server unreachable: {e}")

        # Phase 2 — tool discovery (10 s timeout); non-fatal if it times out
        http_tools: list = []
        tool_error: str = ""
        try:
            from analytics_agent.context.mcp_platform import MCPContextPlatform

            platform = MCPContextPlatform(
                name=plat.name,
                transport=typed_cfg.transport,
                url=url,
                headers=headers,
                command=typed_cfg.command,
                args=typed_cfg.args,
                env=typed_cfg.env,
            )
            http_tools = await asyncio.wait_for(platform.get_tools(), timeout=10)
        except TimeoutError:
            tool_error = "Tool discovery timed out — server is reachable but slow to respond."
        except Exception as e:
            tool_error = f"Tool discovery failed: {e}"

        # Phase 3 — cache discovered schemas in background (don't block response)
        if http_tools:
            tool_schemas = [
                {"name": t.name, "description": t.description or t.name} for t in http_tools
            ]
            raw["_discovered_tools"] = tool_schemas

            async def _cache_tools() -> None:
                from analytics_agent.db.base import _get_session_factory
                from analytics_agent.db.repository import ContextPlatformRepo as _CPR

                sf = _get_session_factory()
                async with sf() as write_session:
                    row = await _CPR(write_session).get(plat.name)
                    if row:
                        row.config = orjson.dumps(raw).decode()
                        await write_session.commit()

            asyncio.create_task(_cache_tools())

        tool_names = ", ".join(t.name for t in http_tools[:5])
        suffix = f" (+ {len(http_tools) - 5} more)" if len(http_tools) > 5 else ""
        tool_msg = f"{tool_names}{suffix}" if http_tools else (tool_error or "No http_tools found")
        return DataHubTestResponse(
            success=True,
            message=f"Connected — {len(http_tools)} http_tools discovered"
            if http_tools
            else "Connected (tool discovery pending)",
            checks=[
                DataHubCheckResult(
                    name="reachability",
                    label="Server reachable",
                    success=True,
                    message=f"Connected to {url}",
                ),
                DataHubCheckResult(
                    name="tools",
                    label="Tools discovered",
                    success=bool(http_tools),
                    message=tool_msg,
                ),
            ],
        )

    # Native DataHub — test using stored url/token
    url = typed_cfg.url if hasattr(typed_cfg, "url") else ""
    token = typed_cfg.token if hasattr(typed_cfg, "token") else ""
    if not url or not token:
        return DataHubTestResponse(
            success=False,
            error="DataHub URL or token not configured.",
        )
    try:
        import asyncio

        from datahub.sdk.main_client import DataHubClient

        client = await asyncio.to_thread(DataHubClient, server=url, token=token)
        graph = client._graph  # type: ignore[attr-defined]
        r = await asyncio.to_thread(graph.execute_graphql, "{ me { corpUser { urn username } } }")
        username = (r.get("me") or {}).get("corpUser", {}).get("username", "unknown")
        return DataHubTestResponse(
            success=True,
            message=f"Connected as {username}",
            checks=[
                DataHubCheckResult(
                    name="get_me",
                    label="Identity",
                    success=True,
                    message=f"Signed in as {username}",
                )
            ],
        )
    except Exception as e:
        return DataHubTestResponse(success=False, error=str(e)[:200])


@router.post("/connections/{name}/test", response_model=DataHubTestResponse)
async def test_connection(
    name: str, session: AsyncSession = Depends(get_session)
) -> DataHubTestResponse:
    # Check context platforms first — handles both native datahub and MCP variants
    cp_repo = ContextPlatformRepo(session)
    cp = await cp_repo.get(name)
    if cp is not None:
        return await _test_context_platform(cp)

    # Legacy hardcoded path for the "default" datahub (env-var based, no DB row yet).
    # The virtual fallback connection is named "default"; also accept "datahub" for compat.
    if name in ("datahub", "default"):
        import asyncio

        from analytics_agent.context.datahub import aget_datahub_client

        client = await aget_datahub_client()
        if client is None:
            return DataHubTestResponse(
                success=False,
                error="DataHub not configured — set DATAHUB_GMS_URL and DATAHUB_GMS_TOKEN",
            )

        checks: list[DataHubCheckResult] = []

        try:
            graph = client._graph  # type: ignore[attr-defined]

            # 1. get_me — identity + auth check
            try:
                r = await asyncio.to_thread(
                    graph.execute_graphql, "{ me { corpUser { urn username } } }"
                )
                username = (r.get("me") or {}).get("corpUser", {}).get("username", "unknown")
                checks.append(
                    DataHubCheckResult(
                        name="get_me",
                        label="Identity",
                        success=True,
                        message=f"Signed in as {username}",
                    )
                )
            except Exception as e:
                checks.append(
                    DataHubCheckResult(
                        name="get_me",
                        label="Identity",
                        success=False,
                        message=str(e)[:120],
                    )
                )

            # 2. basic search — dataset index reachable
            try:
                r = await asyncio.to_thread(
                    graph.execute_graphql,
                    '{ searchAcrossEntities(input: {types: [DATASET], query: "*", count: 1}) { total } }',
                )
                total = (r.get("searchAcrossEntities") or {}).get("total", 0)
                checks.append(
                    DataHubCheckResult(
                        name="search",
                        label="Dataset search",
                        success=True,
                        message=f"{total:,} datasets indexed",
                    )
                )
            except Exception as e:
                checks.append(
                    DataHubCheckResult(
                        name="search",
                        label="Dataset search",
                        success=False,
                        message=str(e)[:120],
                    )
                )

            # 3. landscape — facet aggregations (platforms + domains)
            _LANDSCAPE_QUERY = """
                {
                  searchAcrossEntities(input: {
                    types: [DATASET], query: "*", count: 0
                  }) {
                    total
                    facets { field aggregations { value count } }
                  }
                }
                """
            try:
                r = await asyncio.to_thread(graph.execute_graphql, _LANDSCAPE_QUERY)
                result = r.get("searchAcrossEntities") or {}
                facets = result.get("facets") or []
                pf = next((f for f in facets if f["field"] == "platform"), None)
                df = next((f for f in facets if f["field"] == "domains"), None)
                platforms = len((pf or {}).get("aggregations", []))
                domains = len((df or {}).get("aggregations", []))
                checks.append(
                    DataHubCheckResult(
                        name="landscape",
                        label="Landscape",
                        success=True,
                        message=f"{platforms} platform{'s' if platforms != 1 else ''} · {domains} domain{'s' if domains != 1 else ''}",
                    )
                )
            except Exception as e:
                checks.append(
                    DataHubCheckResult(
                        name="landscape",
                        label="Landscape",
                        success=False,
                        message=str(e)[:120],
                    )
                )

        except Exception as e:
            return DataHubTestResponse(success=False, error=str(e), checks=checks)

        return DataHubTestResponse(success=all(c.success for c in checks), checks=checks)

    try:
        from analytics_agent.engines.factory import get_engine

        engine = get_engine(name)
        tools = engine.get_tools()
        execute_sql = next((t for t in tools if t.name == "execute_sql"), None)
        if execute_sql:
            result = execute_sql.invoke(
                {
                    "sql": "SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema != 'INFORMATION_SCHEMA'"
                }
            )
            parsed = orjson.loads(result) if isinstance(result, str) else result
            if "error" not in parsed and parsed.get("rows"):
                count = parsed["rows"][0].get("N", parsed["rows"][0].get("n", "?"))
                return DataHubTestResponse(
                    success=True, message=f"Connected — {count} tables accessible"
                )
        list_tables = next((t for t in tools if t.name == "list_tables"), None)
        if list_tables:
            result = list_tables.invoke({"schema": ""})
            tables = orjson.loads(result) if isinstance(result, str) else result
            return DataHubTestResponse(
                success=True, message=f"Connected — {len(tables)} tables visible"
            )
        return DataHubTestResponse(success=True, message="Engine connected")
    except Exception as e:
        return DataHubTestResponse(success=False, error=str(e))


_capabilities_cache: dict | None = None
_capabilities_cache_ts: float = 0.0
_CAPABILITIES_TTL = 300  # 5 minutes


@router.get("/datahub/capabilities")
async def get_datahub_capabilities() -> dict:
    """Probe the connected DataHub instance for optional feature availability."""
    import asyncio
    import time

    global _capabilities_cache, _capabilities_cache_ts

    now = time.monotonic()
    if _capabilities_cache is not None and now - _capabilities_cache_ts < _CAPABILITIES_TTL:
        return _capabilities_cache

    from analytics_agent.context.datahub import aget_datahub_client

    client = await aget_datahub_client()
    if client is None:
        return {"semantic_search": False, "error": "DataHub not configured"}

    semantic_search = False
    try:
        graph = client._graph  # type: ignore[attr-defined]
        result = await asyncio.to_thread(
            graph.execute_graphql,
            (
                "{ semanticSearchAcrossEntities("
                ' input: { query: "*", count: 0, types: [DOCUMENT] }'
                ") { total } }"
            ),
        )
        # If the query runs without a schema error, the feature exists
        semantic_search = "semanticSearchAcrossEntities" in result
    except Exception as e:
        err = str(e)
        # FieldUndefined / InvalidSyntax / ValidationError all mean the field doesn't exist
        semantic_search = not any(
            k in err
            for k in ("FieldUndefined", "InvalidSyntax", "ValidationError", "Unknown field")
        )

    _capabilities_cache = {"semantic_search": semantic_search}
    _capabilities_cache_ts = now
    return _capabilities_cache


@router.get("/connections/{name}/datahub-coverage", response_model=DataHubCoverageResponse)
async def get_datahub_coverage(name: str) -> DataHubCoverageResponse:
    """Return how many datasets DataHub has indexed for this engine connection's platform."""
    import asyncio

    from analytics_agent.context.datahub import aget_datahub_client
    from analytics_agent.engines.factory import get_engine

    client = await aget_datahub_client()
    if client is None:
        return DataHubCoverageResponse(covered=False, dataset_count=0)

    # Determine the DataHub platform from the engine
    _PLATFORM_MAP = {
        "snowflake": "snowflake",
        "redshift": "redshift",
        "mysql": "mysql",
        "postgres": "postgres",
        "postgresql": "postgres",
    }
    try:
        engine = get_engine(name)
        # SQLAlchemyQueryEngine exposes datahub_platform derived from dialect
        platform = (
            getattr(engine, "datahub_platform", None) or type(engine).__module__.split(".")[3]
        )
    except Exception:
        platform = name
    dh_platform = _PLATFORM_MAP.get(platform, platform)

    platform_urn = f"urn:li:dataPlatform:{dh_platform}"
    graph = client._graph  # type: ignore[attr-defined]

    # Primary: GraphQL search with platform URN filter — total comes from the API
    try:
        gql_result = await asyncio.to_thread(
            graph.execute_graphql,
            (
                '{ search(input: {type: DATASET, query: "*", start: 0, count: 0,'
                f' filters: [{{field: "platform", value: "{platform_urn}"}}]'
                "}) { total } }"
            ),
        )
        total = gql_result.get("search", {}).get("total", 0)
        if total > 0:
            return DataHubCoverageResponse(covered=True, dataset_count=total, platform=dh_platform)
    except Exception:
        pass

    # Fallback: text search by platform name, count unique URNs containing the platform URN.
    # Handles DataHub versions where the platform filter silently returns 0.
    try:
        gql_result = await asyncio.to_thread(
            graph.execute_graphql,
            (
                f'{{ search(input: {{type: DATASET, query: "{dh_platform}",'
                " start: 0, count: 50}) { total searchResults { entity { urn } } } }"
            ),
        )
        search_data = gql_result.get("search", {})
        matching_urns = [
            sr["entity"]["urn"]
            for sr in search_data.get("searchResults", [])
            if platform_urn in sr.get("entity", {}).get("urn", "")
        ]
        if matching_urns:
            return DataHubCoverageResponse(
                covered=True, dataset_count=len(matching_urns), platform=dh_platform
            )
    except Exception:
        pass

    return DataHubCoverageResponse(covered=False, dataset_count=0, platform=dh_platform)


@router.put("/connections/{name}")
async def update_connection(
    name: str,
    body: UpdateConnectionRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # Context platform (DataHub, etc.) — persist to DB
    cp_repo = ContextPlatformRepo(session)
    cp = await cp_repo.get(name)
    if cp:
        from analytics_agent.config import DataHubMCPConfig, parse_platform_config

        raw: dict = {}
        with contextlib.suppress(Exception):
            raw = orjson.loads(cp.config)

        typed_cp = parse_platform_config(raw)

        if isinstance(typed_cp, DataHubMCPConfig):
            for key, value in body.config.items():
                if not value or "•" in value:
                    continue
                if key == "url":
                    typed_cp.url = value
                elif key == "token":
                    typed_cp.headers["Authorization"] = f"Bearer {value}"
            if typed_cp.transport in ("http", "sse", "streamable_http"):
                _validate_mcp_url(typed_cp.url)
            new_cfg: dict = typed_cp.model_dump()
        else:
            new_cfg = dict(raw)
            for key, value in body.config.items():
                if not value or "•" in value:
                    continue
                new_cfg[key] = value

        # Preserve metadata keys
        for meta in ("_disabled_tools", "_discovered_tools"):
            if meta in raw:
                new_cfg[meta] = raw[meta]

        existing_cfg = new_cfg
        cp.config = orjson.dumps(existing_cfg).decode()
        from analytics_agent.db.models import utcnow

        cp.updated_at = utcnow()
        await session.commit()
        # Propagate to env so agent picks it up immediately (no restart needed)
        if cp.type == "datahub":
            if existing_cfg.get("url"):
                os.environ["DATAHUB_GMS_URL"] = existing_cfg["url"]
            if existing_cfg.get("token"):
                os.environ["DATAHUB_GMS_TOKEN"] = existing_cfg["token"]
        return {"success": True, "message": "Connection settings saved."}

    # Engine connection: body.config → integrations.config (DB),
    # body.secrets → translated via the engine's secret_env_vars allow-list
    # → .env + os.environ.  Hot-reload the engine with the merged config after
    # saving.
    from analytics_agent.db.models import utcnow
    from analytics_agent.db.repository import IntegrationRepo
    from analytics_agent.engines.factory import register_engine

    intg_repo = IntegrationRepo(session)
    intg = await intg_repo.get(name)
    if intg is None:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    intg_cfg: dict = {}
    with contextlib.suppress(Exception):
        intg_cfg = orjson.loads(intg.config)

    env_fields: dict[str, str] = {}
    config_fields: dict[str, str] = {}

    # body.config → merged into integrations.config (DB)
    # body.secrets → translated through the engine's secret_env_vars → .env
    for key, value in body.config.items():
        if value is None or value == "" or "•" in value:
            continue
        config_fields[key] = value
    env_fields = _resolve_secrets(intg.type, body.secrets)

    # Normalize Snowflake account URL → account identifier (same rules as POST)
    if intg.type == "snowflake" and config_fields.get("account"):
        config_fields["account"] = _normalize_snowflake_account(config_fields["account"])

    changed = False
    if config_fields:
        new_cfg = {**intg_cfg, **config_fields}
        intg.config = orjson.dumps(new_cfg).decode()
        # Flip source so _seed_integrations doesn't clobber this edit on next startup.
        if intg.source == "yaml":
            intg.source = "ui"
        intg.updated_at = utcnow()
        changed = True

    if env_fields:
        env_path = _find_env_file()
        _upsert_env_vars(env_path, env_fields)
        for k, v in env_fields.items():
            os.environ[k] = v
        changed = True

    if changed:
        await session.commit()

    # Hot-reload the engine with the merged config so the change takes effect
    # without a server restart.
    reload_warning = ""
    try:
        latest_cfg = orjson.loads(intg.config)
        register_engine(intg.name, intg.type, latest_cfg)
    except Exception as exc:  # noqa: BLE001 — surface the reason to the UI
        reload_warning = f" Saved, but engine reload failed ({exc}); restart the server to apply."

    return {
        "success": True,
        "message": f"Connection settings saved.{reload_warning}",
    }


def _resolve_secrets(intg_type: str, secrets: dict[str, str]) -> dict[str, str]:
    """Translate friendly secret keys → env-var names via the engine class.

    Each ``QueryEngine`` subclass declares its own ``secret_env_vars`` allow-list
    (see ``analytics_agent.engines.base``). This keeps the API layer ignorant of any
    particular engine's credential fields.  Raises ``HTTPException(400)`` for
    any secret key the engine does not recognise.
    """
    from analytics_agent.engines.factory import _engine_cls

    engine_cls = _engine_cls(intg_type)
    mapping: dict[str, str] = getattr(engine_cls, "secret_env_vars", {}) if engine_cls else {}

    unknown = [k for k in secrets if k not in mapping]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown secret key(s) for {intg_type!r}: {unknown}. "
            f"Valid keys: {list(mapping)}",
        )

    env_vars: dict[str, str] = {}
    for k, v in secrets.items():
        if v is not None and "•" not in v:
            env_vars[mapping[k]] = v
    return env_vars


def _normalize_snowflake_account(raw: str) -> str:
    """Accept a Snowflake account URL or bare account identifier and return the id.

    Kept in sync with the POST /connections normalization so edits can't introduce a
    format the engine won't recognize.
    """
    import re as _re

    raw = raw.strip()
    m = _re.search(r"app\.snowflake\.com/([^/]+)/([^/#?]+)", raw, _re.IGNORECASE)
    if m:
        return f"{m.group(1)}-{m.group(2)}".lower()
    m = _re.match(r"https?://([^.]+)\.snowflakecomputing\.com", raw, _re.IGNORECASE)
    if m:
        return m.group(1)
    cleaned = _re.sub(r"^https?://", "", raw, flags=_re.IGNORECASE)
    return cleaned.split(".")[0].split("/")[0]


def _upsert_env_vars(path: pathlib.Path, fields: dict[str, str]) -> None:
    """Replace or append ``KEY="VALUE"`` lines in .env.

    Values are **always** double-quoted so that PEM blocks, passwords with
    special characters (#, $, spaces, backslashes) and bare words all
    round-trip correctly through both python-dotenv and ``set -a; source
    .env``.  Embedded backslashes are doubled and embedded double-quotes are
    backslash-escaped before wrapping.
    """
    import re

    if not path.exists():
        path.write_text("")
    content = path.read_text()

    def _format(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    for key, value in fields.items():
        # Match either KEY="...multiline..." or KEY=bare-value (single line).
        # DOTALL lets .*? span newlines inside the quoted form.
        pattern = re.compile(
            rf'^{re.escape(key)}=(?:"(?:\\.|[^"\\])*"|[^\n]*)$',
            re.MULTILINE | re.DOTALL,
        )
        new_line = f"{key}={_format(value)}"
        if pattern.search(content):

            def _replace(_m: re.Match[str], replacement: str = new_line) -> str:
                return replacement

            content = pattern.sub(_replace, content)
        else:
            content = content.rstrip("\n") + f"\n{new_line}\n"
    path.write_text(content)


def _find_env_file() -> pathlib.Path:
    """Locate .env relative to the repo root, not a hardcoded absolute path.

    Resolution order:
    1. ANALYTICS_AGENT_ENV_FILE env var (explicit override)
    2. Repo root derived from this file's location (backend/src/analytics_agent/api/settings.py
       → parents[4] is the repo root)
    3. engines_config parent (config.yaml sibling) — cwd-based heuristic
    4. Bare ".env" fallback (cwd)
    """
    env_file_override = os.environ.get("ANALYTICS_AGENT_ENV_FILE", "")
    if env_file_override:
        return pathlib.Path(env_file_override)

    # parents[0]=api, [1]=analytics_agent, [2]=src, [3]=backend, [4]=repo root
    repo_root_candidate = pathlib.Path(__file__).resolve().parents[4] / ".env"
    if repo_root_candidate.exists():
        return repo_root_candidate

    from analytics_agent.config import settings as _settings

    # engines_config is typically "./config.yaml" — resolve relative to cwd
    candidate = pathlib.Path(_settings.engines_config).parent / ".env"
    if candidate.exists():
        return candidate
    return pathlib.Path(".env")


# --- Tool toggle endpoint ---


@router.put("/tools")
async def update_tools(
    body: UpdateToolsRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    repo = SettingsRepo(session)
    await repo.set(_KEY_DISABLED_TOOLS, orjson.dumps(body.disabled_tools).decode())
    safe_mutations = [t for t in body.enabled_mutations if t in _SKILL_TOOL_NAMES]
    await repo.set(_KEY_ENABLED_MUTATIONS, orjson.dumps(safe_mutations).decode())
    await repo.set(_KEY_DISABLED_CONNECTIONS, orjson.dumps(body.disabled_connections).decode())
    return {"success": True, "message": "Tool settings saved."}


# --- Prompt endpoints ---


@router.get("/prompt", response_model=PromptContent)
async def get_prompt(session: AsyncSession = Depends(get_session)) -> PromptContent:
    from analytics_agent.prompts.system import get_prompt_template

    repo = SettingsRepo(session)
    custom = await repo.get(_KEY_PROMPT)
    if custom:
        return PromptContent(content=custom, is_custom=True)
    return PromptContent(content=get_prompt_template(), is_custom=False)


@router.put("/prompt")
async def update_prompt(
    body: UpdatePromptRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    repo = SettingsRepo(session)
    await repo.set(_KEY_PROMPT, body.content)
    return {"success": True, "message": "Custom prompt saved."}


@router.delete("/prompt")
async def reset_prompt(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    repo = SettingsRepo(session)
    await repo.delete(_KEY_PROMPT)
    return {"success": True, "message": "Prompt reset to default."}


# --- LLM settings endpoints ---

_KEY_LLM_CONFIG = "llm_config"


def _fernet_encrypt(value: str) -> str:
    """Encrypt a string with the configured OAUTH_MASTER_KEY; returns plaintext if key absent."""
    from analytics_agent.config import settings as cfg

    key = cfg.oauth_master_key.strip()
    if not key:
        return value
    from cryptography.fernet import Fernet

    return Fernet(key.encode()).encrypt(value.encode()).decode()


def _fernet_decrypt(value: str) -> str:
    """Decrypt a Fernet token if it looks like ciphertext; returns value as-is otherwise."""
    if not value.startswith("gAAAAA"):
        return value  # plaintext (no key was set when it was stored)
    from analytics_agent.config import settings as cfg

    key = cfg.oauth_master_key.strip()
    if not key:
        raise ValueError(
            "LLM api_key is encrypted in the DB but OAUTH_MASTER_KEY is not set. "
            "Restore the original key."
        )
    from cryptography.fernet import Fernet

    return Fernet(key.encode()).decrypt(value.encode()).decode()


class LlmSettingsResponse(BaseModel):
    provider: str = "anthropic"
    model: str = ""
    has_key: bool = False
    # Bedrock only — signals that explicit AWS keys are stored. Callers use this
    # to decide whether to show a masked-placeholder in the settings UI.
    has_aws_keys: bool = False
    aws_region: str = ""
    enable_prompt_cache: bool = True


class UpdateLlmSettingsRequest(BaseModel):
    provider: str = "anthropic"
    api_key: str = ""
    model: str = ""
    # Bedrock-only fields. Leave blank to use the default AWS credential chain.
    aws_region: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""
    # Prompt caching for system prompt + tool definitions (Anthropic + Bedrock).
    enable_prompt_cache: bool = True


@router.get("/llm", response_model=LlmSettingsResponse)
async def get_llm_settings() -> LlmSettingsResponse:
    """Return current LLM config.

    The startup hook (_load_llm_config_from_db in main.py) copies any DB-stored
    key into the settings singleton, so reading the singleton is authoritative.
    """
    from analytics_agent.config import PROVIDER_KEY_ATTR
    from analytics_agent.config import settings as cfg

    provider = cfg.llm_provider
    key_attr = PROVIDER_KEY_ATTR.get(provider, "")
    has_aws_keys = bool(cfg.aws_access_key_id and cfg.aws_secret_access_key)
    if provider == "bedrock":
        # Bedrock has no single "API key". It's considered configured if the
        # provider is explicitly selected — auth falls back to the AWS credential
        # chain (env vars, ~/.aws/credentials, IAM role) at call time.
        has_key = True
    else:
        has_key = bool(getattr(cfg, key_attr, "")) if key_attr else False
    return LlmSettingsResponse(
        provider=provider,
        model=cfg.get_llm_model(),
        has_key=has_key,
        has_aws_keys=has_aws_keys,
        aws_region=cfg.aws_region,
        enable_prompt_cache=cfg.enable_prompt_cache,
    )


class TestLlmKeyRequest(BaseModel):
    provider: str = "anthropic"
    api_key: str = ""
    model: str = ""
    # Bedrock-only — leave blank to use the default AWS credential chain.
    aws_region: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""


class TestLlmKeyResponse(BaseModel):
    ok: bool
    message: str = ""


@router.post("/llm/test", response_model=TestLlmKeyResponse)
async def test_llm_key(body: TestLlmKeyRequest) -> TestLlmKeyResponse:
    """Validate an API key by making a minimal 1-token call to the provider.

    Does NOT save anything — purely a connectivity check.
    """
    import asyncio

    from pydantic import SecretStr

    def _run() -> None:
        from analytics_agent.config import PROVIDER_DEFAULTS

        defaults = PROVIDER_DEFAULTS.get(body.provider, PROVIDER_DEFAULTS["openai"])
        model = body.model or defaults["chart"]  # use cheap/fast tier for the test

        from langchain_core.language_models.chat_models import BaseChatModel

        llm: BaseChatModel
        if body.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            llm = ChatAnthropic(model_name=model, api_key=SecretStr(body.api_key), max_tokens=1)  # type: ignore[call-arg]
        elif body.provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            llm = ChatGoogleGenerativeAI(  # type: ignore[assignment]
                model=model, google_api_key=SecretStr(body.api_key), max_output_tokens=1
            )
        elif body.provider == "bedrock":
            from langchain_aws import ChatBedrockConverse

            # Fall back to whatever is already in settings/env when the request
            # omits a field — lets the user verify "existing" creds without
            # retyping them.
            from analytics_agent.config import settings as _cfg

            bk_kwargs: dict = {
                "model": model,
                "region_name": body.aws_region or _cfg.aws_region or "us-west-2",
                "max_tokens": 1,
            }
            akid = body.aws_access_key_id or _cfg.aws_access_key_id
            asak = body.aws_secret_access_key or _cfg.aws_secret_access_key
            tok = body.aws_session_token or _cfg.aws_session_token
            if akid and asak:
                bk_kwargs["aws_access_key_id"] = SecretStr(akid)
                bk_kwargs["aws_secret_access_key"] = SecretStr(asak)
                if tok:
                    bk_kwargs["aws_session_token"] = SecretStr(tok)
            llm = ChatBedrockConverse(**bk_kwargs)
        else:
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(  # type: ignore[assignment]
                model=model,
                max_tokens=1,
                temperature=0,
                api_key=SecretStr(body.api_key),  # type: ignore[call-arg]
            )
        llm.invoke("hi")

    try:
        await asyncio.to_thread(_run)
        return TestLlmKeyResponse(ok=True, message="Key verified")
    except Exception as exc:
        raw = str(exc)
        if (
            "401" in raw
            or "authentication" in raw.lower()
            or "invalid" in raw.lower()
            and "key" in raw.lower()
        ):
            msg = "Invalid API key — check it and try again"
        elif "403" in raw:
            msg = "This key doesn't have the required permissions"
        elif "429" in raw or "rate" in raw.lower():
            msg = "Rate limit hit — key looks valid, try again"
        elif "connect" in raw.lower() or "network" in raw.lower():
            msg = "Couldn't reach the provider — check your connection"
        else:
            msg = raw[:120].strip()
        return TestLlmKeyResponse(ok=False, message=msg)


@router.put("/llm")
async def update_llm_settings(
    body: UpdateLlmSettingsRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Persist LLM config to the settings table (not .env).

    Storing in DB means the app works with zero env vars — the startup hook
    loads this row back into the singleton on every restart.
    """
    from analytics_agent.config import settings as cfg

    repo = SettingsRepo(session)

    # Merge with any existing stored record so fields not in this request are preserved.
    existing: dict[str, str] = {}
    raw = await repo.get(_KEY_LLM_CONFIG)
    if raw:
        try:
            existing = orjson.loads(raw)
        except Exception:
            pass

    new_cfg: dict[str, str] = {**existing, "provider": body.provider}
    if body.model:
        new_cfg["model"] = body.model
    if body.api_key:
        new_cfg["api_key"] = _fernet_encrypt(body.api_key)
    # Bedrock AWS fields. Region stored plaintext (non-secret); keys encrypted.
    if body.aws_region:
        new_cfg["aws_region"] = body.aws_region
    if body.aws_access_key_id:
        new_cfg["aws_access_key_id"] = _fernet_encrypt(body.aws_access_key_id)
    if body.aws_secret_access_key:
        new_cfg["aws_secret_access_key"] = _fernet_encrypt(body.aws_secret_access_key)
    if body.aws_session_token:
        new_cfg["aws_session_token"] = _fernet_encrypt(body.aws_session_token)
    # Bool — always persisted (no truthy gate; the user may want to set it false).
    new_cfg["enable_prompt_cache"] = "true" if body.enable_prompt_cache else "false"

    await repo.set(_KEY_LLM_CONFIG, orjson.dumps(new_cfg).decode())

    # Update os.environ + singleton so llm.py picks up changes immediately
    # (no restart required after the wizard completes).
    from analytics_agent.config import PROVIDER_KEY_ATTR, PROVIDER_KEY_ENV

    os.environ["LLM_PROVIDER"] = body.provider
    cfg.llm_provider = body.provider
    if body.model:
        os.environ["LLM_MODEL"] = body.model
        cfg.llm_model = body.model
    if body.api_key:
        env_var = PROVIDER_KEY_ENV.get(body.provider)
        attr = PROVIDER_KEY_ATTR.get(body.provider)
        if env_var:
            os.environ[env_var] = body.api_key
        if attr:
            setattr(cfg, attr, body.api_key)
    # Bedrock fields flow into both env and singleton so langchain-aws picks them up.
    if body.aws_region:
        os.environ["AWS_REGION"] = body.aws_region
        cfg.aws_region = body.aws_region
    if body.aws_access_key_id:
        os.environ["AWS_ACCESS_KEY_ID"] = body.aws_access_key_id
        cfg.aws_access_key_id = body.aws_access_key_id
    if body.aws_secret_access_key:
        os.environ["AWS_SECRET_ACCESS_KEY"] = body.aws_secret_access_key
        cfg.aws_secret_access_key = body.aws_secret_access_key
    if body.aws_session_token:
        os.environ["AWS_SESSION_TOKEN"] = body.aws_session_token
        cfg.aws_session_token = body.aws_session_token
    cfg.enable_prompt_cache = body.enable_prompt_cache
    os.environ["ENABLE_PROMPT_CACHE"] = "true" if body.enable_prompt_cache else "false"

    return {"success": True, "message": "LLM settings saved."}


# --- Display settings endpoints ---


@router.get("/display", response_model=DisplaySettings)
async def get_display(session: AsyncSession = Depends(get_session)) -> DisplaySettings:
    repo = SettingsRepo(session)
    raw = await repo.get(_KEY_DISPLAY)
    if raw:
        try:
            data = orjson.loads(raw)
            return DisplaySettings(
                app_name=data.get("app_name", "Analytics Agent"), logo_url=data.get("logo_url", "")
            )
        except Exception:
            pass
    return DisplaySettings()


@router.put("/display")
async def update_display(
    body: UpdateDisplayRequest, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    repo = SettingsRepo(session)
    await repo.set(
        _KEY_DISPLAY, orjson.dumps({"app_name": body.app_name, "logo_url": body.logo_url}).decode()
    )
    return {"success": True, "message": "Display settings saved."}
