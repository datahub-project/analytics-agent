from __future__ import annotations

import datetime
import logging
import uuid
from decimal import Decimal
from typing import Any

import orjson
from langchain_core.tools import BaseTool, tool

from analytics_agent.engines.base import QueryEngine, _apply_row_limit

logger = logging.getLogger(__name__)


class SQLAlchemyQueryEngine(QueryEngine):
    name = "sqlalchemy"

    def __init__(self, connection_cfg: dict[str, Any]) -> None:
        self._cfg = connection_cfg
        self._engine: Any = None

    @property
    def datahub_platform(self) -> str:
        """DataHub platform name derived from the configured dialect (mysql+pymysql → mysql)."""
        dialect = self._cfg.get("dialect", "")
        if dialect:
            return dialect.split("+")[0]
        # Fall back to the URL scheme if dialect isn't set
        url = self._cfg.get("url", "")
        if url:
            return url.split("+")[0].split("://")[0]
        return "sqlalchemy"

    def _build_url(self) -> str:
        """Build a SQLAlchemy URL string from config."""
        if "url" in self._cfg:
            return self._cfg["url"]

        from sqlalchemy.engine import URL

        dialect = self._cfg.get("dialect", "")
        if not dialect:
            raise ValueError("SQLAlchemy connection config must include either 'url' or 'dialect'.")

        # render_as_string(hide_password=False) is required — str(URL) masks the password with ***
        return URL.create(
            drivername=dialect,
            username=self._cfg.get("user") or self._cfg.get("username") or None,
            password=self._cfg.get("password") or None,
            host=self._cfg.get("host") or None,
            port=self._cfg.get("port") or None,
            database=self._cfg.get("database") or None,
        ).render_as_string(hide_password=False)

    def _get_engine(self) -> Any:
        """Build and cache a sync SQLAlchemy engine (lazy)."""
        if self._engine is None:
            from sqlalchemy import create_engine

            url = self._build_url()
            self._engine = create_engine(url)
            logger.info("[SQLAlchemy] engine created for url=%s", repr(url))
        return self._engine

    @staticmethod
    def _coerce_value(v: Any) -> Any:
        """Convert SQLAlchemy-returned types to JSON-native Python types."""
        if isinstance(v, Decimal):
            return float(v) if v % 1 else int(v)
        if isinstance(v, (datetime.datetime, datetime.date)):
            return v.isoformat()
        if isinstance(v, bytes):
            return v.hex()
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    def _run_query(self, sql: str, limit: int | None = None) -> dict:
        from analytics_agent.config import settings

        try:
            engine = self._get_engine()
        except Exception as e:
            return {"error": str(e), "columns": [], "rows": [], "truncated": False}

        effective_sql = _apply_row_limit(sql, limit)

        try:
            from sqlalchemy import text

            with engine.connect() as conn:
                cursor = conn.execute(text(effective_sql))
                columns = list(cursor.keys()) if cursor.returns_rows else []
                rows = cursor.fetchall()
                truncated = len(rows) >= (limit or settings.sql_row_limit)
                coerced = [
                    {c: self._coerce_value(v) for c, v in zip(columns, row, strict=False)}
                    for row in rows
                ]
                return {"columns": columns, "rows": coerced, "truncated": truncated}
        except Exception as e:
            return {"error": str(e), "columns": [], "rows": [], "truncated": False}

    def get_tools(self) -> list[BaseTool]:
        engine = self

        @tool
        def execute_sql(sql: str) -> str:
            """Execute a SQL query against the connected database. Returns JSON with columns and rows."""
            from analytics_agent.config import settings

            result = engine._run_query(sql, limit=settings.sql_row_limit)
            return orjson.dumps(result).decode()

        @tool
        def list_tables(schema: str = "") -> str:
            """List tables available in the database. Optionally filter by schema name."""
            try:
                from sqlalchemy import inspect

                inspector = inspect(engine._get_engine())
                table_names = inspector.get_table_names(schema=schema or None)
                tables = [{"name": t, "schema": schema or None} for t in table_names]
                return orjson.dumps(tables).decode()
            except Exception as e:
                return orjson.dumps({"error": str(e)}).decode()

        @tool
        def get_schema(table: str) -> str:
            """Get the column schema for a database table."""
            try:
                from sqlalchemy import inspect

                inspector = inspect(engine._get_engine())
                columns = inspector.get_columns(table)
                result = [
                    {
                        "name": col["name"],
                        "type": str(col["type"]),
                        "nullable": col.get("nullable", True),
                    }
                    for col in columns
                ]
                return orjson.dumps(result).decode()
            except Exception as e:
                return orjson.dumps({"error": str(e)}).decode()

        @tool
        def preview_table(table: str, limit: int = 10) -> str:
            """Preview the first N rows of a database table."""
            result = engine._run_query(f"SELECT * FROM {table}", limit=limit)
            return orjson.dumps(result).decode()

        return [execute_sql, list_tables, get_schema, preview_table]

    async def aclose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
