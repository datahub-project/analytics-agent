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
