"""DB-mutating bootstrap functions.

Pure async helpers, no FastAPI coupling. Each is independently callable, idempotent,
and intended to be invoked from the analytics-agent CLI (typically via a Helm
pre-install/pre-upgrade hook). All write logic that used to live inside the
FastAPI lifespan now lives here.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from analytics_agent.config import settings


def run_migrations() -> None:
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
    import pymysql

    match = re.search(r"/([^/?]+)(\?|$)", settings.database_url)
    if not match:
        return
    schema = match.group(1)

    url_no_schema = re.sub(r"mysql\+aiomysql://", "", settings.database_url)
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
                f"CREATE SCHEMA IF NOT EXISTS `{schema}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
        conn.close()
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Could not ensure MySQL schema '%s': %s", schema, exc
        )


async def seed_integrations_from_yaml() -> None:
    """Upsert config.yaml engines into the integrations table.

    Skips rows whose ``source == "ui"`` (the user has edited them via Settings UI).
    Removes yaml-source rows no longer in config. Migrates any legacy
    ``snowflake_oauth:*`` entries from the settings table to credentials.
    Does NOT register engines in the in-memory factory — that is done at pod
    boot by ``main.register_engines_from_db()``.
    """
    import uuid

    import orjson

    from analytics_agent.db.base import _get_session_factory
    from analytics_agent.db.repository import (
        CredentialRepo,
        IntegrationRepo,
        SettingsRepo,
    )

    logger = logging.getLogger(__name__)
    factory = _get_session_factory()
    async with factory() as session:
        integration_repo = IntegrationRepo(session)
        cred_repo = CredentialRepo(session)
        settings_repo = SettingsRepo(session)

        config_engine_names = {
            cfg.effective_name for cfg in settings.load_engines_config()
        }
        for cfg in settings.load_engines_config():
            engine_type = cfg.type
            engine_name = cfg.effective_name
            connection = cfg.connection
            label = f"{engine_type.capitalize()} ({engine_name})"
            existing = await integration_repo.get(engine_name)
            if existing is not None and existing.source == "ui":
                logger.info(
                    "Skipping yaml seed for '%s' — user-managed via Settings UI",
                    engine_name,
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

        for intg in await integration_repo.list_all():
            if intg.source == "yaml" and intg.name not in config_engine_names:
                logger.info(
                    "Removing stale yaml integration '%s' (no longer in config.yaml)",
                    intg.name,
                )
                await integration_repo.delete(intg.name)

        # Legacy oauth_token migration
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
