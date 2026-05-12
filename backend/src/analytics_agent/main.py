from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load .env into os.environ before anything else so load_engines_config()
# env-var substitution (os.environ.get) resolves correctly.
# Resolution order: ANALYTICS_AGENT_CONFIG_DIR/.env → project root .env → cwd .env
_config_dir = Path(
    os.environ.get("ANALYTICS_AGENT_CONFIG_DIR", "~/.datahub/analytics-agent")
).expanduser()
_env_candidates = [_config_dir / ".env", Path(__file__).parents[3] / ".env"]
_loaded_env = False
for _env_file in _env_candidates:
    if _env_file.exists():
        load_dotenv(_env_file, override=True)
        _loaded_env = True
        break
if not _loaded_env:
    load_dotenv(override=True)  # fall back to cwd .env search

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from analytics_agent.config import settings


async def register_engines_from_db() -> None:
    """Populate the in-memory engine factory from rows in the integrations table.

    This is a per-pod read-only operation. Yaml→DB seeding lives in
    ``analytics_agent.bootstrap.seed_integrations_from_yaml`` and runs as a
    Helm pre-install/pre-upgrade hook.
    """
    import orjson

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import IntegrationRepo
    from analytics_agent.engines.factory import register_engine

    logger = logging.getLogger(__name__)
    factory = _get_session_factory()
    async with factory() as session:
        all_integrations = await IntegrationRepo(session).list_all()

    for intg in all_integrations:
        try:
            conn_cfg = orjson.loads(intg.config)
            register_engine(intg.name, intg.type, conn_cfg)
        except Exception as e:
            logger.warning("Failed to register engine %s: %s", intg.name, e)


async def propagate_datahub_env() -> None:
    """Copy the first DataHub context platform's URL/token into ``os.environ``.

    Sync callers (agent tools, ``datahub.py``) read these env vars. This is a
    per-pod read-only operation; yaml→DB seeding for context platforms lives in
    ``analytics_agent.bootstrap.seed_context_platforms_from_yaml``.
    """
    import orjson

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import ContextPlatformRepo

    factory = _get_session_factory()
    async with factory() as session:
        all_platforms = await ContextPlatformRepo(session).list_all()

    for plat in all_platforms:
        if plat.type == "datahub":
            parsed = orjson.loads(plat.config)
            if parsed.get("url"):
                os.environ["DATAHUB_GMS_URL"] = parsed["url"]
            if parsed.get("token"):
                os.environ["DATAHUB_GMS_TOKEN"] = parsed["token"]
            break


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast if rows are encrypted but the master key is absent.
    # Must run BEFORE any DB read that would deserialize EncryptedJSON columns.
    await _check_encryption_key_consistency()

    # Per-pod read-only init. All DB-mutating bootstrap work (migrations,
    # yaml→DB seeds, first-run defaults) is now done by the analytics-agent
    # CLI, run as a Helm pre-install/pre-upgrade hook.
    await register_engines_from_db()
    await propagate_datahub_env()
    await _load_llm_config_from_db()

    # Telemetry — initialize after LLM config is loaded so settings.llm_provider
    # reflects any DB-stored override. The agent.started span is picked up by
    # MixpanelSpanProcessor (registered in setup_tracing) once enabled=True.

    from opentelemetry import trace as _otrace

    from analytics_agent.db.base import _get_session_factory as _sf
    from analytics_agent.db.repository import IntegrationRepo as _IR
    from analytics_agent.telemetry import init_telemetry

    _factory = _sf()
    await init_telemetry(_factory)

    async with _factory() as _sess:
        _integrations = await _IR(_sess).list_all()
    # Union DB-seeded engines with YAML-loaded engines so deployments that skip
    # bootstrap (config.yaml only, no Helm) still report their engine types.
    _engine_types = list(
        {i.type for i in _integrations} | {c.type for c in settings.load_engines_config()}
    )

    _tracer = _otrace.get_tracer("analytics_agent")
    with _tracer.start_as_current_span("agent.started") as _span:
        _span.set_attribute("llm.provider", settings.llm_provider)
        _span.set_attribute("engine_types", _engine_types)
        _span.set_attribute("engines.count", len(_engine_types))
        _span.set_attribute("prompt_cache.enabled", settings.enable_prompt_cache)

    # Background MCP tool discovery — non-blocking, per-platform retry.
    import asyncio as _asyncio

    _asyncio.create_task(_discover_mcp_tools_on_boot())

    yield

    from analytics_agent.engines.factory import close_all

    await close_all()


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

    # Bedrock AWS fields. Region is plaintext; keys are fernet-encrypted.
    # Env var always wins (explicit user override), same pattern as api_key.
    aws_region = cfg_data.get("aws_region", "")
    if aws_region and not os.environ.get("AWS_REGION"):
        settings.aws_region = aws_region
        os.environ["AWS_REGION"] = aws_region

    for db_key, env_var, attr in [
        ("aws_access_key_id", "AWS_ACCESS_KEY_ID", "aws_access_key_id"),
        ("aws_secret_access_key", "AWS_SECRET_ACCESS_KEY", "aws_secret_access_key"),
        ("aws_session_token", "AWS_SESSION_TOKEN", "aws_session_token"),
    ]:
        encrypted = cfg_data.get(db_key, "")
        if not encrypted or os.environ.get(env_var):
            continue
        try:
            from analytics_agent.api.settings import _fernet_decrypt

            value = _fernet_decrypt(encrypted)
        except Exception as exc:
            logging.getLogger(__name__).error("Failed to decrypt %s from DB: %s", db_key, exc)
            continue
        if value:
            os.environ[env_var] = value
            setattr(settings, attr, value)

    # OpenAI-compatible provider fields. URL and model are plaintext; headers are encrypted.
    base_url = cfg_data.get("base_url", "")
    if base_url and not os.environ.get("OPENAI_COMPATIBLE_BASE_URL"):
        settings.openai_compatible_base_url = base_url
        os.environ["OPENAI_COMPATIBLE_BASE_URL"] = base_url

    compat_model = cfg_data.get("openai_compatible_model", "")
    if compat_model and not os.environ.get("OPENAI_COMPATIBLE_MODEL"):
        settings.openai_compatible_model = compat_model
        os.environ["OPENAI_COMPATIBLE_MODEL"] = compat_model

    encrypted_headers = cfg_data.get("openai_compatible_headers", "")
    if encrypted_headers and not os.environ.get("OPENAI_COMPATIBLE_HEADERS"):
        try:
            from analytics_agent.api.settings import _fernet_decrypt

            headers = _fernet_decrypt(encrypted_headers)
        except Exception as exc:
            logging.getLogger(__name__).error(
                "Failed to decrypt openai_compatible_headers from DB: %s", exc
            )
            headers = ""
        if headers:
            os.environ["OPENAI_COMPATIBLE_HEADERS"] = headers
            settings.openai_compatible_headers = headers

    # Prompt caching toggle (bool stored as "true"/"false" string).
    if "enable_prompt_cache" in cfg_data and not os.environ.get("ENABLE_PROMPT_CACHE"):
        raw_flag = cfg_data["enable_prompt_cache"]
        # Tolerate both legacy bool storage and current string form.
        flag_on = raw_flag is True or (isinstance(raw_flag, str) and raw_flag.lower() == "true")
        settings.enable_prompt_cache = flag_on
        os.environ["ENABLE_PROMPT_CACHE"] = "true" if flag_on else "false"


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

    @app.get("/health", include_in_schema=False)
    async def _health() -> dict[str, str]:
        return {"status": "ok"}

    setup_tracing(app)

    # ── Serve built React SPA ──────────────────────────────────────────────
    # Only activates when frontend/dist/ exists (production / pnpm build).
    # Falls back gracefully: serves API-only if dist is absent (dev mode).
    _env_dist = os.getenv("FRONTEND_DIST", "")
    if _env_dist:
        _dist = Path(_env_dist)
    elif (Path(__file__).parent / "static").exists():
        _dist = Path(__file__).parent / "static"  # bundled in wheel
    else:
        _dist = Path(__file__).parents[3] / "frontend" / "dist"  # dev / repo

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
