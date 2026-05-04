from __future__ import annotations

import os
from dataclasses import dataclass, field

from analytics_agent.config import settings
from analytics_agent.engines.base import QueryEngine

_registry: dict[str, QueryEngine] = {}


@dataclass
class ConnectorSpec:
    """Describes how to launch a native connector as an MCP subprocess via uvx."""

    package: str
    env_map: dict[str, str] = field(default_factory=dict)
    # Subset of env_map whose values are credentials (kept in .env, not logged).
    secret_env_vars: dict[str, str] = field(default_factory=dict)
    # Keys that must ALL be present for a connection to be considered configured.
    required_keys: list[str] = field(default_factory=list)
    # Keys where ANY ONE being present counts as having credentials.
    credential_keys: list[str] = field(default_factory=list)

    def is_configured(self, conn_cfg: dict, sso_connected: bool = False) -> bool:
        """True when the connection has enough config to attempt a real query.

        Checks both the stored config dict and the corresponding env vars so
        yaml-sourced connections (which may use ${VAR} substitution) are handled
        the same way as UI-created ones.
        """

        def _has(key: str) -> bool:
            return bool(conn_cfg.get(key) or os.environ.get(self.env_map.get(key, ""), ""))

        if not all(_has(k) for k in self.required_keys):
            return False
        # SSO connections don't need a stored credential — auth is in the session.
        if sso_connected:
            return True
        return any(_has(k) for k in self.credential_keys)

    def _binary_name(self) -> str:
        """Return the CLI entry-point name (same as the package name by convention)."""
        return self.package

    def build_mcp_config(self, connection: dict) -> dict:
        """Build the MCPQueryEngine config dict for a stdio subprocess connector.

        Uses the installed binary (placed in PATH by `uv tool install`) as the
        command. Falls back to `uvx <package>` only if the binary is not found —
        uvx will then download and run the package from PyPI on demand.

        Starts with the full parent environment so the subprocess inherits PATH,
        HOME, etc., then overlays any values explicitly set in the connection config.
        """
        import shutil

        binary = self._binary_name()
        if shutil.which(binary):
            command, args = binary, []
        else:
            command, args = "uvx", [self.package]

        env = dict(os.environ)
        for conn_key, env_var in self.env_map.items():
            val = connection.get(conn_key)
            if val:
                env[env_var] = str(val)
        return {
            "transport": "stdio",
            "command": command,
            "args": args,
            "env": env,
        }


_CONNECTOR_MAP: dict[str, ConnectorSpec] = {
    "snowflake": ConnectorSpec(
        package="analytics-agent-connector-snowflake",
        env_map={
            "account": "SNOWFLAKE_ACCOUNT",
            "user": "SNOWFLAKE_USER",
            "warehouse": "SNOWFLAKE_WAREHOUSE",
            "database": "SNOWFLAKE_DATABASE",
            "schema": "SNOWFLAKE_SCHEMA",
            "role": "SNOWFLAKE_ROLE",
            "password": "SNOWFLAKE_PASSWORD",
            "private_key": "SNOWFLAKE_PRIVATE_KEY",
            "pat_token": "SNOWFLAKE_PAT_TOKEN",
        },
        secret_env_vars={
            "password": "SNOWFLAKE_PASSWORD",
            "private_key": "SNOWFLAKE_PRIVATE_KEY",
            "pat_token": "SNOWFLAKE_PAT_TOKEN",
        },
        required_keys=["account", "user"],
        credential_keys=["password", "private_key", "pat_token"],
    ),
    "bigquery": ConnectorSpec(
        package="analytics-agent-connector-bigquery",
        env_map={
            "project": "BIGQUERY_PROJECT",
            "dataset": "BIGQUERY_DATASET",
            "credentials_json": "BIGQUERY_CREDENTIALS_JSON",
            "credentials_base64": "BIGQUERY_CREDENTIALS_BASE64",
            "credentials_path": "BIGQUERY_CREDENTIALS_PATH",
        },
        secret_env_vars={
            "credentials_json": "BIGQUERY_CREDENTIALS_JSON",
        },
        required_keys=["project"],
        credential_keys=["credentials_json", "credentials_base64", "credentials_path"],
    ),
}


def get_secret_env_vars(engine_type: str) -> dict[str, str]:
    """Return the secret_env_vars mapping for an engine type.

    Used by api/settings.py to validate and translate body.secrets.
    Returns an empty dict for unknown types (graceful degradation).
    """
    from analytics_agent.engines.sqlalchemy.engine import SQLAlchemyQueryEngine

    spec = _CONNECTOR_MAP.get(engine_type)
    if spec:
        return spec.secret_env_vars

    # For SQLAlchemy-based engines, delegate to the class attribute.
    cls = {
        "mysql": SQLAlchemyQueryEngine,
        "sqlite": SQLAlchemyQueryEngine,
        "postgresql": SQLAlchemyQueryEngine,
        "sqlalchemy": SQLAlchemyQueryEngine,
    }.get(engine_type)
    return getattr(cls, "secret_env_vars", {}) if cls else {}


def _engine_cls(engine_type: str):
    from analytics_agent.engines.mcp.engine import MCPQueryEngine
    from analytics_agent.engines.sqlalchemy.engine import SQLAlchemyQueryEngine

    if engine_type in _CONNECTOR_MAP:
        spec = _CONNECTOR_MAP[engine_type]

        def _make_connector(connection_cfg: dict) -> MCPQueryEngine:
            return MCPQueryEngine({"_mcp": spec.build_mcp_config(connection_cfg)})

        return _make_connector

    return {
        "mysql": SQLAlchemyQueryEngine,
        "sqlite": SQLAlchemyQueryEngine,
        "postgresql": SQLAlchemyQueryEngine,
        "sqlalchemy": SQLAlchemyQueryEngine,
        "mcp": MCPQueryEngine,
        "mcp-stdio": MCPQueryEngine,
        "mcp-sse": MCPQueryEngine,
    }.get(engine_type)


def _load_engines() -> dict[str, QueryEngine]:
    engines: dict[str, QueryEngine] = {}
    for cfg in settings.load_engines_config():
        factory_fn = _engine_cls(cfg.type)
        if factory_fn:
            engines[cfg.effective_name] = factory_fn(cfg.connection)
    return engines


def get_registry() -> dict[str, QueryEngine]:
    global _registry
    if not _registry:
        _registry = _load_engines()
    return _registry


def register_engine(name: str, engine_type: str, connection_cfg: dict) -> None:
    """Register (or replace) a named engine dynamically."""
    factory_fn = _engine_cls(engine_type)
    if not factory_fn:
        raise ValueError(f"Unknown engine type '{engine_type}'")
    get_registry()[name] = factory_fn(connection_cfg)


def unregister_engine(name: str) -> None:
    """Remove a dynamically registered engine."""
    get_registry().pop(name, None)


def get_engine(name: str) -> QueryEngine:
    registry = get_registry()
    if name not in registry:
        raise ValueError(f"Engine '{name}' not found. Available: {list(registry.keys())}")
    return registry[name]


def get_engine_for_request(
    name: str,
    oauth_token: str | None = None,
    sso_user: str | None = None,
    pat_token: str | None = None,
    pat_user: str | None = None,
) -> QueryEngine:
    registry = get_registry()
    if name not in registry:
        raise ValueError(f"Engine '{name}' not found. Available: {list(registry.keys())}")

    engine = registry[name]

    if sso_user and hasattr(engine, "with_sso_user"):
        return engine.with_sso_user(sso_user)

    if pat_token and hasattr(engine, "with_pat_token"):
        return engine.with_pat_token(pat_token, pat_user=pat_user)

    if oauth_token and hasattr(engine, "with_oauth_token"):
        return engine.with_oauth_token(oauth_token)

    return engine


def list_engines() -> list[dict]:
    return [{"name": name, "type": eng.name} for name, eng in get_registry().items()]


async def close_all() -> None:
    for engine in get_registry().values():
        await engine.aclose()
