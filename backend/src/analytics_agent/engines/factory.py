from __future__ import annotations

from analytics_agent.config import settings
from analytics_agent.engines.base import QueryEngine

_registry: dict[str, QueryEngine] = {}

_TYPE_MAP_KEY = "snowflake"  # avoid circular import at module level


def _engine_cls(engine_type: str):
    from analytics_agent.engines.mcp.engine import MCPQueryEngine
    from analytics_agent.engines.snowflake.engine import SnowflakeQueryEngine
    from analytics_agent.engines.sqlalchemy.engine import SQLAlchemyQueryEngine

    return {
        "snowflake": SnowflakeQueryEngine,
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
        cls = _engine_cls(cfg.type)
        if cls:
            engines[cfg.effective_name] = cls(cfg.connection)
    return engines


def get_registry() -> dict[str, QueryEngine]:
    global _registry
    if not _registry:
        _registry = _load_engines()
    return _registry


def register_engine(name: str, engine_type: str, connection_cfg: dict) -> None:
    """Register (or replace) a named engine dynamically."""
    cls = _engine_cls(engine_type)
    if not cls:
        raise ValueError(f"Unknown engine type '{engine_type}'")
    get_registry()[name] = cls(connection_cfg)


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
