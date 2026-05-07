"""Snowflake MCP connector server for Analytics Agent.

Runs as a subprocess launched by the analytics-agent core via:
    uvx analytics-agent-connector-snowflake

Reads all config from environment variables. Exposes 4 tools:
  execute_sql, list_tables, get_schema, preview_table
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

import orjson
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

SQL_ROW_LIMIT = int(os.environ.get("SQL_ROW_LIMIT", "500"))

mcp = FastMCP("snowflake-connector")

# ── Connection ────────────────────────────────────────────────────────────────

_conn: Any = None


def _decode_pem_env(value: str) -> str:
    v = value.strip().strip('"')
    if not v:
        return ""
    try:
        decoded = base64.b64decode(v).decode()
        if "-----BEGIN" in decoded:
            return decoded
    except Exception:
        pass
    return v.replace("\\n", "\n")


def _get_connection():
    global _conn
    if _conn is None or _conn.is_closed():
        import snowflake.connector

        account = os.environ.get("SNOWFLAKE_ACCOUNT", "")
        if not account:
            raise RuntimeError("SNOWFLAKE_ACCOUNT is not configured.")

        connect_kwargs: dict[str, Any] = {
            "account": account,
            "user": os.environ.get("SNOWFLAKE_USER", ""),
            "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", ""),
            "database": os.environ.get("SNOWFLAKE_DATABASE", ""),
            "schema": os.environ.get("SNOWFLAKE_SCHEMA", ""),
            "login_timeout": 15,
            "network_timeout": 15,
        }
        if os.environ.get("SNOWFLAKE_ROLE"):
            connect_kwargs["role"] = os.environ["SNOWFLAKE_ROLE"]

        pat_token = os.environ.get("SNOWFLAKE_PAT_TOKEN", "")
        private_key_pem = _decode_pem_env(os.environ.get("SNOWFLAKE_PRIVATE_KEY", ""))
        password = os.environ.get("SNOWFLAKE_PASSWORD", "")

        if pat_token:
            connect_kwargs["authenticator"] = "programmatic_access_token"
            connect_kwargs["token"] = pat_token
        elif private_key_pem:
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
        elif password:
            connect_kwargs["password"] = password
        else:
            raise RuntimeError(
                "Snowflake credentials not configured. "
                "Set SNOWFLAKE_PASSWORD, SNOWFLAKE_PRIVATE_KEY, or SNOWFLAKE_PAT_TOKEN."
            )

        _conn = snowflake.connector.connect(**connect_kwargs)
    return _conn


# ── Type coercion ─────────────────────────────────────────────────────────────

def _coerce(v: Any) -> Any:
    import datetime
    from decimal import Decimal

    if isinstance(v, Decimal):
        return float(v) if v % 1 else int(v)
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.hex()
    return v


# ── SQL helpers ───────────────────────────────────────────────────────────────

def _apply_limit(sql: str, limit: int) -> str:
    effective = sql.strip().rstrip(";")
    if effective.lstrip().upper().startswith("SELECT") and "LIMIT" not in effective.upper():
        return f"{effective} LIMIT {limit}"
    return effective


def _run_query(sql: str, limit: int | None = None) -> dict:
    effective_limit = limit or SQL_ROW_LIMIT
    try:
        conn = _get_connection()
    except Exception as e:
        return {"error": str(e), "columns": [], "rows": [], "truncated": False}

    effective_sql = _apply_limit(sql, effective_limit)
    cursor = conn.cursor()
    try:
        cursor.execute(effective_sql)
        columns = [col[0] for col in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        truncated = len(rows) >= effective_limit
        coerced = [
            {c: _coerce(v) for c, v in zip(columns, row, strict=False)} for row in rows
        ]
        return {"columns": columns, "rows": coerced, "truncated": truncated}
    except Exception as e:
        return {"error": str(e), "columns": [], "rows": [], "truncated": False}
    finally:
        cursor.close()


# ── MCP tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def execute_sql(sql: str) -> str:
    """Execute a SQL query against the connected Snowflake warehouse. Returns JSON with columns and rows."""
    return orjson.dumps(_run_query(sql, SQL_ROW_LIMIT)).decode()


@mcp.tool()
def list_tables(schema: str | None = None) -> str:
    """List tables available in the Snowflake database. Optionally filter by schema name."""
    schema = schema or ""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        try:
            if schema:
                cursor.execute(f"SHOW TABLES IN SCHEMA {schema}")
            else:
                cursor.execute("SHOW TABLES")
            rows = cursor.fetchall()
            tables = [{"name": row[1], "schema": row[3], "database": row[2]} for row in rows]
            return orjson.dumps(tables).decode()
        finally:
            cursor.close()
    except Exception as e:
        return orjson.dumps({"error": str(e)}).decode()


@mcp.tool()
def get_schema(table: str) -> str:
    """Get the column schema for a Snowflake table. Use fully qualified name (db.schema.table) if needed."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"DESCRIBE TABLE {table}")
            rows = cursor.fetchall()
            columns = [{"name": row[0], "type": row[1], "nullable": row[3] == "Y"} for row in rows]
            return orjson.dumps(columns).decode()
        finally:
            cursor.close()
    except Exception as e:
        return orjson.dumps({"error": str(e)}).decode()


@mcp.tool()
def preview_table(table: str, limit: int = 10) -> str:
    """Preview the first N rows of a Snowflake table."""
    return orjson.dumps(_run_query(f"SELECT * FROM {table}", limit=limit)).decode()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
