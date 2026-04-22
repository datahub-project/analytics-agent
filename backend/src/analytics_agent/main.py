from __future__ import annotations

import contextlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load .env into os.environ before anything else so load_engines_config()
# env-var substitution (os.environ.get) resolves correctly.
# Try project root first, then fall back to cwd search.
_env_file = Path(__file__).parents[3] / ".env"
load_dotenv(_env_file if _env_file.exists() else None, override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from analytics_agent.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run Alembic migrations at startup (sync — Alembic is not async)
    _run_migrations()

    # Seed integrations from config.yaml and load all into engine registry
    await _seed_integrations()

    # Seed context platforms (DataHub, etc.) from config.yaml into DB
    await _seed_context_platforms()

    # Fail fast if rows are encrypted but the master key is absent
    await _check_encryption_key_consistency()

    # Apply first-run defaults (skipped if already configured)
    await _seed_default_settings()

    # Load LLM credentials stored via the onboarding wizard into the singleton.
    # This is what makes the app work with zero env vars.
    await _load_llm_config_from_db()

    # Kick off tool discovery for any MCP connections that haven't been discovered yet.
    # Runs in the background so it doesn't delay startup.
    import asyncio as _asyncio

    _asyncio.create_task(_discover_mcp_tools_on_boot())

    yield

    # Cleanup engine connections
    from analytics_agent.engines.factory import close_all

    await close_all()


async def _seed_integrations() -> None:
    """
    Upsert config.yaml engines into the integrations table, then load all
    integrations (yaml + ui-created) into the engine factory registry.
    Also migrates any legacy oauth_token:* entries from settings table.
    """
    import uuid

    import orjson

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import CredentialRepo, IntegrationRepo, SettingsRepo
    from analytics_agent.engines.factory import register_engine

    factory = _get_session_factory()
    async with factory() as session:
        integration_repo = IntegrationRepo(session)
        cred_repo = CredentialRepo(session)
        settings_repo = SettingsRepo(session)

        # 1. Upsert config.yaml engines and remove orphans (yaml-source entries no longer in config).
        # If the user has edited a yaml-seeded row via the Settings UI the row's source is flipped
        # to "ui" (see api/settings.py::update_connection); we skip those so the user's edits
        # survive restarts.
        config_engine_names = {cfg.effective_name for cfg in settings.load_engines_config()}
        for cfg in settings.load_engines_config():
            engine_type = cfg.type
            engine_name = cfg.effective_name
            connection = cfg.connection
            label = f"{engine_type.capitalize()} ({engine_name})"
            existing = await integration_repo.get(engine_name)
            if existing is not None and existing.source == "ui":
                logging.getLogger(__name__).info(
                    "Skipping yaml seed for '%s' — user-managed via Settings UI", engine_name
                )
                continue
            await integration_repo.upsert(
                id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"yaml:{engine_name}")),
                name=engine_name,
                type=engine_type,
                label=label,
                config=orjson.dumps(connection).decode(),
                source="yaml",
            )
        # Delete yaml-source integrations that are no longer in config.yaml
        for intg in await integration_repo.list_all():
            if intg.source == "yaml" and intg.name not in config_engine_names:
                logging.getLogger(__name__).info(
                    "Removing stale yaml integration '%s' (no longer in config.yaml)", intg.name
                )
                await integration_repo.delete(intg.name)

        # 2. Migrate legacy oauth_token:* from settings table
        all_integrations = await integration_repo.list_all()
        for intg in all_integrations:
            old_key = f"snowflake_oauth:{intg.name}"
            raw = await settings_repo.get(old_key)
            if raw and intg.credential is None:
                try:
                    data = orjson.loads(raw)
                    method = data.get("method", "")
                    user = data.get("username") or data.get("user", "")
                    if method == "externalbrowser" and user:
                        await cred_repo.upsert(
                            id=str(uuid.uuid4()),
                            integration_name=intg.name,
                            auth_type="sso_externalbrowser",
                            username=user,
                        )
                        await settings_repo.delete(old_key)
                except Exception:
                    pass

        # 3. Register all integrations in engine factory
        all_integrations = await integration_repo.list_all()
        for intg in all_integrations:
            try:
                conn_cfg = orjson.loads(intg.config)
                register_engine(intg.name, intg.type, conn_cfg)
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "Failed to register engine %s: %s", intg.name, e
                )


async def _seed_context_platforms() -> None:
    """Upsert config.yaml context_platforms into the DB, then propagate DataHub config to env."""
    import uuid

    import orjson

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import ContextPlatformRepo

    factory = _get_session_factory()
    async with factory() as session:
        repo = ContextPlatformRepo(session)

        config_platform_names = {cfg.name for cfg in settings.load_context_platforms_config()}
        for cfg in settings.load_context_platforms_config():
            existing = await repo.get(cfg.name)
            if existing:
                # For yaml-sourced platforms, sync label and env vars (but preserve
                # user-edited credentials and _discovered_tools metadata).
                changed = False
                new_label = cfg.label or cfg.type.capitalize()
                if existing.label != new_label:
                    existing.label = new_label
                    changed = True
                if existing.source == "yaml":
                    # Re-apply env dict from config.yaml so new vars (e.g. TOOLS_IS_MUTATION_ENABLED)
                    # take effect without requiring a manual DB delete.
                    stored: dict = {}
                    with contextlib.suppress(Exception):
                        stored = orjson.loads(existing.config)
                    yaml_cfg_dict = cfg.model_dump()
                    new_env = yaml_cfg_dict.get("env", {})
                    if new_env and stored.get("env") != new_env:
                        stored["env"] = new_env
                        # Preserve cached tools
                        existing.config = orjson.dumps(stored).decode()
                        changed = True
                if changed:
                    await session.commit()
            else:
                # First-time creation: seed from config.yaml
                await repo.upsert(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"yaml:{cfg.name}")),
                    type=cfg.type,
                    name=cfg.name,
                    label=cfg.label or cfg.type.capitalize(),
                    config=orjson.dumps(cfg.model_dump()).decode(),
                    source="yaml",
                )
        # Remove yaml-source platforms no longer in config.yaml
        for plat in await repo.list_all():
            if plat.source == "yaml" and plat.name not in config_platform_names:
                logging.getLogger(__name__).info(
                    "Removing stale yaml context platform '%s'", plat.name
                )
                await repo.delete(plat.name)

        # Propagate the first DataHub platform to os.environ so sync callers
        # (agent tools, datahub.py) continue working without DB access.
        all_platforms = await repo.list_all()
        for plat in all_platforms:
            if plat.type == "datahub":
                parsed = orjson.loads(plat.config)
                if parsed.get("url"):
                    os.environ["DATAHUB_GMS_URL"] = parsed["url"]
                if parsed.get("token"):
                    os.environ["DATAHUB_GMS_TOKEN"] = parsed["token"]
                break


async def _check_encryption_key_consistency() -> None:
    """Fail fast if context_platforms rows are encrypted but OAUTH_MASTER_KEY is absent.

    Uses raw SQL to read the config column as literal text, bypassing the
    EncryptedJSON TypeDecorator (which would itself raise — but possibly inside
    an async greenlet where the traceback gets swallowed).
    """
    if settings.oauth_master_key.strip():
        return  # key is present — nothing to verify here

    from sqlalchemy import text

    from analytics_agent.db.base import _get_session_factory

    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(text("SELECT config FROM context_platforms"))
        rows = result.fetchall()

    encrypted_count = sum(1 for (cfg,) in rows if cfg and cfg.startswith("gAAAAA"))
    if encrypted_count:
        _logger = logging.getLogger(__name__)
        msg = (
            f"STARTUP ABORTED: {encrypted_count} context_platform row(s) have encrypted config "
            "but OAUTH_MASTER_KEY is not set. "
            "Restore the original key in your .env file and restart the server."
        )
        _logger.error(msg)
        raise RuntimeError(msg)


async def _seed_default_settings() -> None:
    """Write first-run defaults to the settings table (no-op if already set)."""
    import orjson

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import SettingsRepo

    factory = _get_session_factory()
    async with factory() as session:
        repo = SettingsRepo(session)
        if await repo.get("enabled_mutation_tools") is None:
            await repo.set(
                "enabled_mutation_tools",
                orjson.dumps(["publish_analysis", "save_correction"]).decode(),
            )


async def _discover_mcp_tools_on_boot() -> None:
    """Background task: discover tools for any MCP context platforms that don't have them yet.

    Runs once at startup so the Connections page shows populated tools the first time
    the user visits — no manual "click Test" step required.
    """
    import asyncio
    import logging as _log

    import orjson

    from analytics_agent.config import DataHubMCPConfig, parse_platform_config
    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import ContextPlatformRepo

    logger = _log.getLogger(__name__)
    factory = _get_session_factory()

    async with factory() as session:
        platforms = await ContextPlatformRepo(session).list_all()

    for plat in platforms:
        raw: dict = {}
        try:
            raw = orjson.loads(plat.config)
        except Exception:
            continue

        if raw.get("_discovered_tools"):
            continue  # already have tools

        cfg = parse_platform_config(raw)
        if not isinstance(cfg, DataHubMCPConfig):
            continue  # not an MCP platform

        if cfg.transport == "stdio" and not cfg.command:
            continue
        if cfg.transport in ("http", "sse") and not cfg.url:
            continue

        logger.info(
            "Boot tool discovery: starting for '%s' (transport=%s)", plat.name, cfg.transport
        )

        try:
            from analytics_agent.context.mcp_platform import MCPContextPlatform

            platform = MCPContextPlatform(
                name=plat.name,
                transport=cfg.transport,
                url=cfg.url,
                headers=cfg.headers,
                command=cfg.command,
                args=cfg.args,
                env=cfg.env,
            )
            tools = await asyncio.wait_for(platform.get_tools(), timeout=60)
            schemas = [{"name": t.name, "description": t.description or t.name} for t in tools]

            async with factory() as write_session:
                row = await ContextPlatformRepo(write_session).get(plat.name)
                if row:
                    stored = orjson.loads(row.config)
                    stored["_discovered_tools"] = schemas
                    row.config = orjson.dumps(stored).decode()
                    await write_session.commit()

            logger.info("Boot tool discovery: '%s' — %d tools cached", plat.name, len(tools))

        except TimeoutError:
            logger.warning("Boot tool discovery: '%s' timed out (60s)", plat.name)
        except Exception as exc:
            logger.warning("Boot tool discovery: '%s' failed — %s", plat.name, exc)


async def _load_llm_config_from_db() -> None:
    """Populate the settings singleton from DB-stored LLM config.

    Env vars always win — we only fill gaps here so that an install with no
    .env file at all can be configured entirely through the onboarding wizard.
    """
    import orjson

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import SettingsRepo

    factory = _get_session_factory()
    async with factory() as session:
        repo = SettingsRepo(session)
        raw = await repo.get("llm_config")
        if not raw:
            return
        try:
            cfg_data: dict = orjson.loads(raw)
        except Exception:
            return

    # For each field: only apply the DB value when the corresponding env var
    # is absent (empty string after load_dotenv).  Explicit env vars always win.
    provider = cfg_data.get("provider", "")
    if provider and not os.environ.get("LLM_PROVIDER"):
        settings.llm_provider = provider
        os.environ["LLM_PROVIDER"] = provider

    effective_provider = os.environ.get("LLM_PROVIDER") or settings.llm_provider
    stored_key = cfg_data.get("api_key", "")
    if stored_key:
        try:
            from analytics_agent.api.settings import _fernet_decrypt

            api_key = _fernet_decrypt(stored_key)
        except Exception as exc:
            logging.getLogger(__name__).error("Failed to decrypt LLM api_key from DB: %s", exc)
            api_key = ""

        if api_key:
            from analytics_agent.config import PROVIDER_KEY_ATTR, PROVIDER_KEY_ENV

            env_var = PROVIDER_KEY_ENV.get(effective_provider)
            attr = PROVIDER_KEY_ATTR.get(effective_provider)
            if env_var and attr and not os.environ.get(env_var):
                os.environ[env_var] = api_key
                setattr(settings, attr, api_key)

    model = cfg_data.get("model", "")
    if model and not os.environ.get("LLM_MODEL"):
        settings.llm_model = model
        os.environ["LLM_MODEL"] = model


def _run_migrations() -> None:
    """Run Alembic migrations synchronously (Alembic is a sync tool)."""
    from alembic import command
    from alembic.config import Config

    if "sqlite" in settings.database_url:
        db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    elif "mysql" in settings.database_url:
        _ensure_mysql_schema()

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")


def _ensure_mysql_schema() -> None:
    """Create the analytics_agent MySQL schema if it doesn't exist."""
    import re

    import pymysql

    # Extract schema name from URL: mysql+aiomysql://user:pass@host:port/schema
    match = re.search(r"/([^/?]+)(\?|$)", settings.database_url)
    if not match:
        return
    schema = match.group(1)

    # Build connection params without the schema (connect to server root)
    url_no_schema = re.sub(r"/[^/?]+(\?|$)", "/\1", settings.database_url)
    url_no_schema = re.sub(r"mysql\+aiomysql://", "", settings.database_url)
    # Parse user:pass@host:port
    creds_match = re.match(r"([^:]+):([^@]+)@([^:/]+):?(\d+)?", url_no_schema)
    if not creds_match:
        return
    user, password, host, port = creds_match.groups()

    try:
        conn = pymysql.connect(
            host=host,
            port=int(port or 3306),
            user=user,
            password=password,
            connect_timeout=5,
        )
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE SCHEMA IF NOT EXISTS `{schema}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
        conn.close()
    except Exception as exc:
        logging.getLogger(__name__).warning("Could not ensure MySQL schema '%s': %s", schema, exc)


def create_app() -> FastAPI:
    import os

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    # Configure structured logging that works with uvicorn's log capture.
    # basicConfig is a no-op if handlers already exist (uvicorn configures first),
    # so we explicitly configure the analytics_agent package logger.
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=log_level, format="%(levelname)s [%(name)s] %(message)s")
    analytics_agent_logger = logging.getLogger("analytics_agent")
    analytics_agent_logger.setLevel(log_level)
    if not analytics_agent_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
        analytics_agent_logger.addHandler(handler)
        analytics_agent_logger.propagate = (
            False  # prevent double-logging through uvicorn's root handler
        )
    logger = logging.getLogger(__name__)

    app = FastAPI(
        title="DataHub Talk to Data",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from analytics_agent.api import api_router
    from analytics_agent.tracing import setup_tracing

    app.include_router(api_router)

    setup_tracing(app)

    # ── Serve built React SPA ──────────────────────────────────────────────
    # Only activates when frontend/dist/ exists (production / pnpm build).
    # Falls back gracefully: serves API-only if dist is absent (dev mode).
    _env_dist = os.getenv("FRONTEND_DIST", "")
    _dist = Path(_env_dist) if _env_dist else Path(__file__).parents[3] / "frontend" / "dist"

    if _dist.exists():
        logger.info("Serving frontend from %s", _dist)

        # Vite hashes asset filenames → safe to serve indefinitely
        app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="spa-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def _spa_fallback(full_path: str) -> FileResponse:
            """Return index.html for all non-API routes (SPA client-side routing)."""
            return FileResponse(_dist / "index.html", media_type="text/html")
    else:
        logger.info("Frontend dist not found at %s — running in API-only mode", _dist)

    return app


app = create_app()
