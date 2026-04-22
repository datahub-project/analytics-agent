from __future__ import annotations

import base64
import logging
import os
from typing import Any

import orjson
from langchain_core.tools import BaseTool, tool

from analytics_agent.engines.base import QueryEngine

logger = logging.getLogger(__name__)


def _decode_pem_env(value: str) -> str:
    """Accept SNOWFLAKE_PRIVATE_KEY as either raw PEM or base64-encoded PEM.

    Base64 encoding keeps the .env file single-line and shareable across tools
    that can't handle multiline values (just dotenv-load, Docker env_file, etc.).
    """
    v = value.strip().strip('"')
    if not v:
        return ""
    try:
        decoded = base64.b64decode(v).decode()
        if "-----BEGIN" in decoded:
            return decoded
    except Exception:
        pass
    # Raw PEM — normalise escaped newlines written by some tools
    return v.replace("\\n", "\n")


# Module-level cache: (account, user) → live connection
# Shared across all request-scoped engine clones so the browser only opens once.
_sso_connection_cache: dict[tuple[str, str], Any] = {}


def store_sso_connection(account: str, user: str, conn: Any) -> None:
    """Called from the browser-sso endpoint to pre-populate the cache."""
    _sso_connection_cache[(account.upper(), user.upper())] = conn


class SnowflakeQueryEngine(QueryEngine):
    name = "snowflake"

    secret_env_vars = {
        "password": "SNOWFLAKE_PASSWORD",
        "private_key": "SNOWFLAKE_PRIVATE_KEY",
    }

    def __init__(
        self,
        connection_cfg: dict[str, Any],
        oauth_token: str | None = None,
        sso_user: str | None = None,
        session_token: str | None = None,
        pat_token: str | None = None,
        pat_user: str | None = None,
    ) -> None:
        self._cfg = connection_cfg
        self._conn: Any = None
        self._oauth_token = oauth_token
        self._sso_user = sso_user
        self._session_token = session_token
        self._pat_token = pat_token
        self._pat_user = pat_user
        self._private_key_pem: str | None = None  # set by with_private_key()

    def with_oauth_token(self, oauth_token: str) -> SnowflakeQueryEngine:
        return SnowflakeQueryEngine(self._cfg, oauth_token=oauth_token)

    def with_sso_user(
        self, sso_user: str, session_token: str | None = None
    ) -> SnowflakeQueryEngine:
        return SnowflakeQueryEngine(self._cfg, sso_user=sso_user, session_token=session_token)

    def with_pat_token(self, pat_token: str, pat_user: str | None = None) -> SnowflakeQueryEngine:
        return SnowflakeQueryEngine(self._cfg, pat_token=pat_token, pat_user=pat_user)

    def with_private_key(self, pem: str, user: str | None = None) -> SnowflakeQueryEngine:
        clone = SnowflakeQueryEngine(self._cfg)
        clone._private_key_pem = pem
        if user:
            clone._cfg = {**self._cfg, "user": user}
        return clone

    def _get_connection(self):
        if self._conn is None or self._conn.is_closed():
            import snowflake.connector

            account = self._cfg.get("account", "")
            if not account:
                raise RuntimeError("SNOWFLAKE_ACCOUNT is not configured.")

            connect_kwargs: dict[str, Any] = {
                "account": account,
                "user": self._cfg.get("user", ""),
                "warehouse": self._cfg.get("warehouse", ""),
                "database": self._cfg.get("database", ""),
                "schema": self._cfg.get("schema", ""),
                "login_timeout": 15,
                "network_timeout": 15,
            }
            if self._cfg.get("role"):
                connect_kwargs["role"] = self._cfg["role"]

            if self._pat_token:
                if self._pat_user:
                    connect_kwargs["user"] = self._pat_user
                logger.info(
                    "[Snowflake auth] method=PAT account=%s user=%s",
                    account,
                    connect_kwargs.get("user", ""),
                )
                connect_kwargs["authenticator"] = "programmatic_access_token"
                connect_kwargs["token"] = self._pat_token
            elif self._sso_user:
                # 1. Try in-memory cached connection (fastest, no network)
                cache_key = (account.upper(), self._sso_user.upper())
                cached = _sso_connection_cache.get(cache_key)
                if cached and not cached.is_closed():
                    logger.info(
                        "[Snowflake auth] method=SSO_CACHE_HIT account=%s user=%s",
                        account,
                        self._sso_user,
                    )
                    self._conn = cached
                    return self._conn
                # 2. Cache miss — try externalbrowser
                logger.info(
                    "[Snowflake auth] method=EXTERNALBROWSER account=%s user=%s (cache miss)",
                    account,
                    self._sso_user,
                )
                connect_kwargs["authenticator"] = "externalbrowser"
                connect_kwargs["user"] = self._sso_user
                connect_kwargs["login_timeout"] = 12
            elif self._oauth_token:
                # OAuth app flow: use short-lived bearer token
                connect_kwargs["authenticator"] = "oauth"
                connect_kwargs["token"] = self._oauth_token
            else:
                # Password / private key path.
                # Prefer credentials stored in DB (via with_private_key/resolver.py).
                # Only fall back to env vars for yaml/legacy connections.
                private_key_pem = self._private_key_pem or ""
                if not private_key_pem:
                    private_key_pem = _decode_pem_env(os.environ.get("SNOWFLAKE_PRIVATE_KEY", ""))
                password = "" if private_key_pem else os.environ.get("SNOWFLAKE_PASSWORD", "")
                if not connect_kwargs.get("user"):
                    raise RuntimeError(
                        "Snowflake user not configured for this connection. "
                        "Sign in via SSO in Settings → Connections → Authentication, "
                        "or add a Service User to the connection config."
                    )
                if not (password or private_key_pem):
                    raise RuntimeError(
                        "Snowflake credentials not configured. "
                        "Sign in via SSO in Settings → Connections → Authentication, "
                        "or set SNOWFLAKE_PASSWORD / SNOWFLAKE_PRIVATE_KEY in .env."
                    )
                if private_key_pem:
                    from cryptography.hazmat.backends import default_backend
                    from cryptography.hazmat.primitives.serialization import (
                        Encoding,
                        NoEncryption,
                        PrivateFormat,
                        load_pem_private_key,
                    )

                    p_key = load_pem_private_key(
                        private_key_pem.encode(), password=None, backend=default_backend()
                    )
                    connect_kwargs["private_key"] = p_key.private_bytes(
                        Encoding.DER, PrivateFormat.PKCS8, NoEncryption()
                    )
                else:
                    connect_kwargs["password"] = password

            try:
                self._conn = snowflake.connector.connect(**connect_kwargs)
                logger.info(
                    "[Snowflake auth] connected — account=%s user=%s method=%s",
                    account,
                    connect_kwargs.get("user", ""),
                    connect_kwargs.get("authenticator", "snowflake"),
                )
            except Exception as exc:
                logger.error(
                    "[Snowflake auth] FAILED — account=%s user=%s method=%s error=%s",
                    account,
                    connect_kwargs.get("user", ""),
                    connect_kwargs.get("authenticator", "snowflake"),
                    exc,
                )
                raise
            if self._sso_user:
                _sso_connection_cache[(account, self._sso_user)] = self._conn
        return self._conn

    @staticmethod
    def _coerce_value(v: Any) -> Any:
        """Convert Snowflake-specific types to JSON-native Python types."""
        import datetime
        from decimal import Decimal

        if isinstance(v, Decimal):
            return float(v) if v % 1 else int(v)
        if isinstance(v, (datetime.datetime, datetime.date)):
            return v.isoformat()
        if isinstance(v, bytes):
            return v.hex()
        return v

    def _run_query(self, sql: str, limit: int | None = None) -> dict:
        from analytics_agent.config import settings

        try:
            conn = self._get_connection()
        except Exception as e:
            return {"error": str(e), "columns": [], "rows": [], "truncated": False}

        effective_sql = sql.strip().rstrip(";")
        if limit is not None and "LIMIT" not in effective_sql.upper():
            effective_sql = f"{effective_sql} LIMIT {limit}"
        cursor = conn.cursor()
        try:
            cursor.execute(effective_sql)
            columns = [col[0] for col in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            truncated = len(rows) >= (limit or settings.sql_row_limit)
            coerced = [
                {c: self._coerce_value(v) for c, v in zip(columns, row, strict=False)}
                for row in rows
            ]
            return {"columns": columns, "rows": coerced, "truncated": truncated}
        except Exception as e:
            return {"error": str(e), "columns": [], "rows": [], "truncated": False}
        finally:
            cursor.close()

    def get_tools(self) -> list[BaseTool]:
        engine = self

        @tool
        def execute_sql(sql: str) -> str:
            """Execute a SQL query against the connected Snowflake warehouse. Returns JSON with columns and rows."""
            from analytics_agent.config import settings

            result = engine._run_query(sql, limit=settings.sql_row_limit)
            return orjson.dumps(result).decode()

        @tool
        def list_tables(schema: str = "") -> str:
            """List tables available in the Snowflake database. Optionally filter by schema name."""
            try:
                conn = engine._get_connection()
                cursor = conn.cursor()
                try:
                    if schema:
                        cursor.execute(f"SHOW TABLES IN SCHEMA {schema}")
                    else:
                        cursor.execute("SHOW TABLES")
                    rows = cursor.fetchall()
                    tables = [
                        {"name": row[1], "schema": row[3], "database": row[2]} for row in rows
                    ]
                    return orjson.dumps(tables).decode()
                finally:
                    cursor.close()
            except Exception as e:
                return orjson.dumps({"error": str(e)}).decode()

        @tool
        def get_schema(table: str) -> str:
            """Get the column schema for a Snowflake table. Use fully qualified name (db.schema.table) if needed."""
            try:
                conn = engine._get_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute(f"DESCRIBE TABLE {table}")
                    rows = cursor.fetchall()
                    columns = [
                        {"name": row[0], "type": row[1], "nullable": row[3] == "Y"} for row in rows
                    ]
                    return orjson.dumps(columns).decode()
                finally:
                    cursor.close()
            except Exception as e:
                return orjson.dumps({"error": str(e)}).decode()

        @tool
        def preview_table(table: str, limit: int = 10) -> str:
            """Preview the first N rows of a Snowflake table."""
            result = engine._run_query(f"SELECT * FROM {table}", limit=limit)
            return orjson.dumps(result).decode()

        return [execute_sql, list_tables, get_schema, preview_table]

    async def aclose(self) -> None:
        if self._conn and not self._conn.is_closed():
            self._conn.close()
