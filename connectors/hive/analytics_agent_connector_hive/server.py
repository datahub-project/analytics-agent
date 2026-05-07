"""Hive MCP connector for Analytics Agent.

Runs as a subprocess launched by the analytics-agent core via:
    uvx analytics-agent-connector-hive

Reads all config from environment variables. Exposes 4 tools:
  execute_sql, list_tables, get_schema, preview_table

Supported auth modes (HIVE_AUTH):
  NONE     — no authentication (default)
  NOSASL   — binary transport, no SASL wrapping
  LDAP     — username + password over SASL PLAIN
  PLAIN    — same as LDAP
  KERBEROS — Kerberos/GSSAPI (requires kerberos system library)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import orjson
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

SQL_ROW_LIMIT = int(os.environ.get("SQL_ROW_LIMIT", "500"))

mcp = FastMCP("hive-connector")

# ── Connection ─────────────────────────────────────────────────────────────────

_conn: Any = None


def _get_connection():
    global _conn
    if _conn is None:
        from pyhive import hive

        host = os.environ.get("HIVE_HOST", "")
        if not host:
            raise RuntimeError("HIVE_HOST is not configured.")

        kwargs: dict[str, Any] = {
            "host": host,
            "port": int(os.environ.get("HIVE_PORT", "10000")),
            "database": os.environ.get("HIVE_DATABASE", "default"),
            "auth": os.environ.get("HIVE_AUTH", "NONE").upper(),
        }

        user = os.environ.get("HIVE_USER", "")
        password = os.environ.get("HIVE_PASSWORD", "")

        if user:
            kwargs["username"] = user
        if password:
            kwargs["password"] = password

        kerberos_service = os.environ.get("HIVE_KERBEROS_SERVICE_NAME", "hive")
        if kwargs["auth"] == "KERBEROS":
            kwargs["kerberos_service_name"] = kerberos_service

        _conn = hive.Connection(**kwargs)
    return _conn


# ── SQL helpers ────────────────────────────────────────────────────────────────

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
    try:
        cursor = conn.cursor()
        cursor.execute(effective_sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        truncated = len(rows) >= effective_limit
        coerced = [
            {c: _coerce(v) for c, v in zip(columns, row, strict=False)} for row in rows
        ]
        return {"columns": columns, "rows": coerced, "truncated": truncated}
    except Exception as e:
        return {"error": str(e), "columns": [], "rows": [], "truncated": False}


# ── MCP tools ──────────────────────────────────────────────────────────────────

@mcp.tool()
def execute_sql(sql: str) -> str:
    """Execute a SQL query against the connected Hive/Kyuubi/Spark warehouse. Returns JSON with columns and rows."""
    return orjson.dumps(_run_query(sql, SQL_ROW_LIMIT)).decode()


@mcp.tool()
def list_tables(schema: str | None = None) -> str:
    """List tables in the Hive database. Optionally filter by schema (database) name."""
    schema = schema or ""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        if schema:
            cursor.execute(f"SHOW TABLES IN {schema}")
        else:
            cursor.execute("SHOW TABLES")
        rows = cursor.fetchall()
        # pyhive SHOW TABLES returns (database, tableName, isTemporary) in some versions
        # and just (tableName,) in others — normalise both.
        tables = []
        for row in rows:
            if len(row) >= 2:
                tables.append({"schema": row[0], "name": row[1]})
            else:
                tables.append({"name": row[0]})
        return orjson.dumps(tables).decode()
    except Exception as e:
        return orjson.dumps({"error": str(e)}).decode()


@mcp.tool()
def get_schema(table: str) -> str:
    """Get the column schema for a Hive table. Use db.table notation for cross-database lookup."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(f"DESCRIBE {table}")
        rows = cursor.fetchall()
        # DESCRIBE returns (col_name, data_type, comment)
        columns = [
            {"name": row[0], "type": row[1], "comment": row[2] if len(row) > 2 else ""}
            for row in rows
            if row[0] and not row[0].startswith("#")  # skip partition/detail sections
        ]
        return orjson.dumps(columns).decode()
    except Exception as e:
        return orjson.dumps({"error": str(e)}).decode()


@mcp.tool()
def preview_table(table: str, limit: int = 10) -> str:
    """Preview the first N rows of a Hive table."""
    return orjson.dumps(_run_query(f"SELECT * FROM {table}", limit=limit)).decode()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
