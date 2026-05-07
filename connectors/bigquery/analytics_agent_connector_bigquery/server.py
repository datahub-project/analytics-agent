"""BigQuery MCP connector server for Analytics Agent.

Runs as a subprocess launched by the analytics-agent core via:
    uvx analytics-agent-connector-bigquery

Reads all config from environment variables. Exposes 4 tools:
  execute_sql, list_tables, get_schema, preview_table
"""

from __future__ import annotations

import base64
import datetime
import logging
import os
import uuid
from decimal import Decimal
from typing import Any

import orjson
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

SQL_ROW_LIMIT = int(os.environ.get("SQL_ROW_LIMIT", "500"))

mcp = FastMCP("bigquery-connector")

# ── Engine ────────────────────────────────────────────────────────────────────

_engine: Any = None


def _resolve_credentials() -> str:
    """Return service-account credentials as base64. Resolution order:
    1. BIGQUERY_CREDENTIALS_JSON (raw JSON string)
    2. BIGQUERY_CREDENTIALS_BASE64 (already base64)
    3. BIGQUERY_CREDENTIALS_PATH (path to JSON file)
    """
    raw_json = os.environ.get("BIGQUERY_CREDENTIALS_JSON", "")
    if raw_json:
        return base64.b64encode(raw_json.encode()).decode()

    b64 = os.environ.get("BIGQUERY_CREDENTIALS_BASE64", "")
    if b64:
        return b64

    path = os.environ.get("BIGQUERY_CREDENTIALS_PATH", "")
    if path:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()

    raise ValueError(
        "BigQuery credentials not configured. "
        "Set BIGQUERY_CREDENTIALS_JSON, BIGQUERY_CREDENTIALS_BASE64, "
        "or BIGQUERY_CREDENTIALS_PATH."
    )


def _get_engine():
    global _engine
    if _engine is None:
        from sqlalchemy import create_engine

        project = os.environ.get("BIGQUERY_PROJECT", "")
        if not project:
            raise ValueError("BIGQUERY_PROJECT is not configured.")

        dataset = os.environ.get("BIGQUERY_DATASET", "")
        url = f"bigquery://{project}/{dataset}" if dataset else f"bigquery://{project}"

        _engine = create_engine(url, credentials_base64=_resolve_credentials())
    return _engine


# ── Type coercion ─────────────────────────────────────────────────────────────

def _coerce(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v) if v % 1 else int(v)
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.hex()
    if isinstance(v, uuid.UUID):
        return str(v)
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
        engine = _get_engine()
    except Exception as e:
        return {"error": str(e), "columns": [], "rows": [], "truncated": False}

    effective_sql = _apply_limit(sql, effective_limit)
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            cursor = conn.execute(text(effective_sql))
            columns = list(cursor.keys()) if cursor.returns_rows else []
            rows = cursor.fetchall()
            truncated = len(rows) >= effective_limit
            coerced = [
                {c: _coerce(v) for c, v in zip(columns, row, strict=False)} for row in rows
            ]
            return {"columns": columns, "rows": coerced, "truncated": truncated}
    except Exception as e:
        return {"error": str(e), "columns": [], "rows": [], "truncated": False}


# ── MCP tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def execute_sql(sql: str) -> str:
    """Execute a SQL query against BigQuery. Returns JSON with columns and rows."""
    return orjson.dumps(_run_query(sql, SQL_ROW_LIMIT)).decode()


@mcp.tool()
def list_tables(schema: str | None = None) -> str:
    """List tables in BigQuery. Pass a dataset name to filter, or leave blank for the default dataset."""
    try:
        from sqlalchemy import inspect

        inspector = inspect(_get_engine())
        table_names = inspector.get_table_names(schema=schema or None)
        tables = [{"name": t, "schema": schema or None} for t in table_names]
        return orjson.dumps(tables).decode()
    except Exception as e:
        return orjson.dumps({"error": str(e)}).decode()


@mcp.tool()
def get_schema(table: str) -> str:
    """Get the column schema for a BigQuery table. Use dataset.table format if needed."""
    try:
        from sqlalchemy import inspect

        schema, _, tbl = table.partition(".")
        if not tbl:
            tbl, schema = schema, None  # type: ignore[assignment]

        inspector = inspect(_get_engine())
        columns = inspector.get_columns(tbl, schema=schema or None)
        result = [
            {"name": col["name"], "type": str(col["type"]), "nullable": col.get("nullable", True)}
            for col in columns
        ]
        return orjson.dumps(result).decode()
    except Exception as e:
        return orjson.dumps({"error": str(e)}).decode()


@mcp.tool()
def preview_table(table: str, limit: int = 10) -> str:
    """Preview the first N rows of a BigQuery table. Use dataset.table format if needed."""
    return orjson.dumps(_run_query(f"SELECT * FROM `{table}`", limit=limit)).decode()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
