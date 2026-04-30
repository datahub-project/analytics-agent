from __future__ import annotations

import base64
import datetime
import logging
import os
import uuid
from decimal import Decimal
from typing import Any, ClassVar

import orjson
from langchain_core.tools import BaseTool, tool

from analytics_agent.engines.base import QueryEngine

logger = logging.getLogger(__name__)


class BigQueryQueryEngine(QueryEngine):
    """
    BigQuery query engine.

    Connection config keys:
      project            - GCP project ID (required)
      dataset            - default dataset / schema (optional)
      credentials_base64 - base64-encoded service-account JSON
      credentials_path   - path to service-account JSON file on disk
      credentials_json   - raw service-account JSON string
      (env var: BIGQUERY_CREDENTIALS_JSON)

    At least one credentials key must be provided.
    """

    name = "bigquery"

    secret_env_vars: ClassVar[dict[str, str]] = {
        "credentials_json": "BIGQUERY_CREDENTIALS_JSON",
    }

    def __init__(self, connection_cfg: dict[str, Any]) -> None:
        self._cfg = connection_cfg
        self._engine: Any = None

    @property
    def datahub_platform(self) -> str:
        return "bigquery"

    def _resolve_credentials(self) -> str:
        """
        Returns service account credentials as a base64 string,
        ready to be passed to create_engine(credentials_base64=...).

        sqlalchemy-bigquery handles deserialization internally.

        Resolution order:
          1. credentials_json  (raw JSON from config or BIGQUERY_CREDENTIALS_JSON env var)
          2. credentials_base64 (already encoded, from config)
          3. credentials_path  (path to JSON file on disk)

        Raises ValueError if no credentials are found.
        """
        # 1. Raw JSON string -> convert to base64
        raw_json: str | None = self._cfg.get("credentials_json") or os.environ.get(
            "BIGQUERY_CREDENTIALS_JSON"
        )
        if raw_json is not None:
            return base64.b64encode(raw_json.encode("utf-8")).decode("utf-8")

        b64: str | None = self._cfg.get("credentials_base64")
        if b64 is not None:
            return b64

        path: str | None = self._cfg.get("credentials_path")
        if path is not None:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")

        raise ValueError(
            "BigQuery service account credentials are required. "
            "Provide one of: 'credentials_json', 'credentials_base64', "
            "'credentials_path', or set the BIGQUERY_CREDENTIALS_JSON env var."
        )

    def _get_engine(self) -> Any:
        if self._engine is None:
            from sqlalchemy import create_engine

            project = self._cfg.get("project")
            if not project:
                raise ValueError("BigQuery connection config must include 'project'.")

            dataset = self._cfg.get("dataset", "")
            url = f"bigquery://{project}/{dataset}" if dataset else f"bigquery://{project}"

            credentials_base64 = self._resolve_credentials()
            self._engine = create_engine(url, credentials_base64=credentials_base64)
            logger.info(
                "[BigQuery] engine created for project=%s dataset=%s",
                project,
                dataset,
            )
        return self._engine

    @staticmethod
    def _coerce_value(v: Any) -> Any:
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

        effective_sql = sql.strip().rstrip(";")
        if limit is not None and "LIMIT" not in effective_sql.upper():
            effective_sql = f"{effective_sql} LIMIT {limit}"

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
            """Execute a SQL query against BigQuery. Returns JSON with columns and rows."""
            from analytics_agent.config import settings

            result = engine._run_query(sql, limit=settings.sql_row_limit)
            return orjson.dumps(result).decode()

        @tool
        def list_tables(schema: str = "") -> str:
            """List tables in BigQuery. Pass a dataset name to filter, or leave blank for the default dataset."""
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
            """Get the column schema for a BigQuery table. Use dataset.table format if needed."""
            try:
                from sqlalchemy import inspect

                # Support dataset.table notation
                schema, _, tbl = table.partition(".")
                if not tbl:
                    tbl, schema = schema, None  # type: ignore[assignment]

                inspector = inspect(engine._get_engine())
                columns = inspector.get_columns(tbl, schema=schema or None)
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
            """Preview the first N rows of a BigQuery table. Use dataset.table format if needed."""
            result = engine._run_query(f"SELECT * FROM `{table}`", limit=limit)
            return orjson.dumps(result).decode()

        return [execute_sql, list_tables, get_schema, preview_table]  # type: ignore[misc]

    async def aclose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
