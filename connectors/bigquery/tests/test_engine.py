"""
Tests for the BigQueryQueryEngine introduced in
analytics_agent/engines/bigquery/engine.py.

Covers:
- _resolve_credentials() priority order (json → base64 → path) and raises when missing
- _get_engine() raises ValueError when project is missing
- _get_engine() raises ValueError when credentials are missing
- _get_engine() passes credentials_base64 kwarg only when credentials are present
- _coerce_value() type conversions (Decimal, datetime, date, bytes, UUID, passthrough)
- _run_query() returns error dict on engine-creation failure
- _run_query() appends LIMIT clause only when needed
- _run_query() coerces row values and sets truncated flag correctly
- get_tools() returns exactly the four expected tool names
- aclose() disposes the engine and clears internal state
"""

from __future__ import annotations

import base64
import datetime
import json
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DUMMY_B64 = base64.b64encode(b'{"type":"service_account","project_id":"p"}').decode()


def _make_engine(cfg: dict | None = None):
    """Instantiate BigQueryQueryEngine without importing heavy deps at module level."""
    from analytics_agent.engines.bigquery.engine import BigQueryQueryEngine

    return BigQueryQueryEngine(cfg or {})


def _cfg_with_creds(**extra) -> dict:
    """Return a config dict that always satisfies the credentials requirement."""
    return {"project": "my-proj", "credentials_base64": _DUMMY_B64, **extra}


# ---------------------------------------------------------------------------
# _resolve_credentials
# ---------------------------------------------------------------------------


class TestResolveCredentials:
    def test_raises_when_no_credentials(self):
        """Credentials are now required; ADC fallback has been removed."""
        eng = _make_engine({"project": "my-proj"})
        with pytest.raises(ValueError, match="credentials"):
            eng._resolve_credentials()

    def test_credentials_json_from_config(self):
        raw = json.dumps({"type": "service_account", "project_id": "p"})
        eng = _make_engine({"project": "my-proj", "credentials_json": raw})
        result = eng._resolve_credentials()
        assert result == base64.b64encode(raw.encode()).decode()

    def test_credentials_json_from_env_var(self, monkeypatch):
        raw = json.dumps({"type": "service_account", "project_id": "p"})
        monkeypatch.setenv("BIGQUERY_CREDENTIALS_JSON", raw)
        eng = _make_engine({"project": "my-proj"})
        result = eng._resolve_credentials()
        assert result == base64.b64encode(raw.encode()).decode()

    def test_credentials_json_config_takes_priority_over_env(self, monkeypatch):
        env_raw = json.dumps({"source": "env"})
        cfg_raw = json.dumps({"source": "cfg"})
        monkeypatch.setenv("BIGQUERY_CREDENTIALS_JSON", env_raw)
        eng = _make_engine({"project": "my-proj", "credentials_json": cfg_raw})
        result = eng._resolve_credentials()
        assert result == base64.b64encode(cfg_raw.encode()).decode()

    def test_credentials_base64_from_config(self):
        b64 = base64.b64encode(b'{"type":"service_account"}').decode()
        eng = _make_engine({"project": "my-proj", "credentials_base64": b64})
        assert eng._resolve_credentials() == b64

    def test_credentials_path_reads_file(self, tmp_path):
        creds_data = b'{"type": "service_account"}'
        creds_file = tmp_path / "sa.json"
        creds_file.write_bytes(creds_data)
        eng = _make_engine({"project": "my-proj", "credentials_path": str(creds_file)})
        result = eng._resolve_credentials()
        assert result == base64.b64encode(creds_data).decode()

    def test_priority_json_over_base64(self):
        raw = json.dumps({"source": "json"})
        b64_other = base64.b64encode(b'{"source":"b64"}').decode()
        eng = _make_engine(
            {
                "project": "my-proj",
                "credentials_json": raw,
                "credentials_base64": b64_other,
            }
        )
        result = eng._resolve_credentials()
        assert result == base64.b64encode(raw.encode()).decode()

    def test_priority_base64_over_path(self, tmp_path):
        creds_file = tmp_path / "sa.json"
        creds_file.write_bytes(b'{"source":"path"}')
        b64 = base64.b64encode(b'{"source":"b64"}').decode()
        eng = _make_engine(
            {
                "project": "my-proj",
                "credentials_base64": b64,
                "credentials_path": str(creds_file),
            }
        )
        assert eng._resolve_credentials() == b64


# ---------------------------------------------------------------------------
# _get_engine
# ---------------------------------------------------------------------------


class TestGetEngine:
    def test_raises_when_project_missing(self):
        eng = _make_engine({})
        with pytest.raises(ValueError, match="project"):
            eng._get_engine()

    def test_raises_when_credentials_missing(self):
        """Credentials are required; no ADC fallback."""
        eng = _make_engine({"project": "my-proj"})
        with pytest.raises(ValueError, match="credentials"):
            eng._get_engine()

    def test_creates_engine_with_project_and_credentials(self):
        eng = _make_engine(_cfg_with_creds())
        mock_engine = MagicMock()
        with patch("sqlalchemy.create_engine", return_value=mock_engine) as mock_ce:
            result = eng._get_engine()
        url_used = mock_ce.call_args[0][0]
        assert url_used == "bigquery://my-proj"
        assert result is mock_engine

    def test_creates_engine_with_dataset(self):
        eng = _make_engine(_cfg_with_creds(dataset="my_ds"))
        mock_engine = MagicMock()
        with patch("sqlalchemy.create_engine", return_value=mock_engine) as mock_ce:
            eng._get_engine()
        url_used = mock_ce.call_args[0][0]
        assert url_used == "bigquery://my-proj/my_ds"

    def test_passes_credentials_base64_when_present(self):
        raw = json.dumps({"type": "service_account"})
        eng = _make_engine({"project": "my-proj", "credentials_json": raw})
        mock_engine = MagicMock()
        expected_b64 = base64.b64encode(raw.encode()).decode()
        with patch("sqlalchemy.create_engine", return_value=mock_engine) as mock_ce:
            eng._get_engine()
        _, kwargs = mock_ce.call_args
        assert kwargs.get("credentials_base64") == expected_b64

    def test_engine_is_cached(self):
        eng = _make_engine(_cfg_with_creds())
        mock_engine = MagicMock()
        with patch("sqlalchemy.create_engine", return_value=mock_engine) as mock_ce:
            first = eng._get_engine()
            second = eng._get_engine()
        assert mock_ce.call_count == 1
        assert first is second


# ---------------------------------------------------------------------------
# _coerce_value
# ---------------------------------------------------------------------------


class TestCoerceValue:
    @pytest.fixture(autouse=True)
    def engine(self):
        from analytics_agent.engines.bigquery.engine import BigQueryQueryEngine

        self.coerce = BigQueryQueryEngine._coerce_value

    def test_decimal_whole_becomes_int(self):
        assert self.coerce(Decimal("42")) == 42
        assert isinstance(self.coerce(Decimal("42")), int)

    def test_decimal_fractional_becomes_float(self):
        assert self.coerce(Decimal("3.14")) == pytest.approx(3.14)
        assert isinstance(self.coerce(Decimal("3.14")), float)

    def test_datetime_isoformat(self):
        dt = datetime.datetime(2024, 1, 15, 12, 30, 0)
        assert self.coerce(dt) == "2024-01-15T12:30:00"

    def test_date_isoformat(self):
        d = datetime.date(2024, 1, 15)
        assert self.coerce(d) == "2024-01-15"

    def test_bytes_to_hex(self):
        assert self.coerce(b"\xde\xad\xbe\xef") == "deadbeef"

    def test_uuid_to_str(self):
        u = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert self.coerce(u) == "12345678-1234-5678-1234-567812345678"

    def test_passthrough_string(self):
        assert self.coerce("hello") == "hello"

    def test_passthrough_int(self):
        assert self.coerce(99) == 99

    def test_passthrough_none(self):
        assert self.coerce(None) is None


# ---------------------------------------------------------------------------
# _run_query
# ---------------------------------------------------------------------------


class TestRunQuery:
    def _make_mock_cursor(self, columns, rows, returns_rows=True):
        cursor = MagicMock()
        cursor.returns_rows = returns_rows
        cursor.keys.return_value = columns
        cursor.fetchall.return_value = rows
        return cursor

    def test_returns_error_dict_on_engine_failure(self):
        eng = _make_engine({})  # no project → ValueError on _get_engine
        result = eng._run_query("SELECT 1")
        assert "error" in result
        assert result["columns"] == []
        assert result["rows"] == []
        assert result["truncated"] is False

    def test_appends_limit_when_missing(self):
        eng = _make_engine({"project": "p"})
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        cursor = self._make_mock_cursor(["n"], [(1,)])
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = cursor
        mock_engine.connect.return_value = mock_conn
        eng._engine = mock_engine

        with patch("analytics_agent.config.settings") as mock_settings:
            mock_settings.sql_row_limit = 100
            with patch("sqlalchemy.text", side_effect=lambda s: s):
                eng._run_query("SELECT * FROM t", limit=50)
                executed_sql = mock_conn.execute.call_args[0][0]
        assert "LIMIT 50" in executed_sql

    def test_does_not_append_limit_when_already_present(self):
        eng = _make_engine({"project": "p"})
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        cursor = self._make_mock_cursor(["n"], [(1,)])
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = cursor
        mock_engine.connect.return_value = mock_conn
        eng._engine = mock_engine

        sql_with_limit = "SELECT * FROM t LIMIT 10"
        with patch("analytics_agent.config.settings") as mock_settings:
            mock_settings.sql_row_limit = 100
            with patch("sqlalchemy.text", side_effect=lambda s: s):
                eng._run_query(sql_with_limit, limit=50)
                executed_sql = mock_conn.execute.call_args[0][0]
        assert executed_sql.count("LIMIT") == 1

    def test_truncated_flag_set_when_rows_equal_limit(self):
        eng = _make_engine({"project": "p"})
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        # Return exactly `limit` rows → truncated should be True
        cursor = self._make_mock_cursor(["id"], [(i,) for i in range(10)])
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = cursor
        mock_engine.connect.return_value = mock_conn
        eng._engine = mock_engine

        with patch("analytics_agent.config.settings") as mock_settings:
            mock_settings.sql_row_limit = 10
            with patch("sqlalchemy.text", side_effect=lambda s: s):
                result = eng._run_query("SELECT id FROM t", limit=10)
        assert result["truncated"] is True

    def test_truncated_false_when_fewer_rows_than_limit(self):
        eng = _make_engine({"project": "p"})
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        cursor = self._make_mock_cursor(["id"], [(1,), (2,)])
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = cursor
        mock_engine.connect.return_value = mock_conn
        eng._engine = mock_engine

        with patch("analytics_agent.config.settings") as mock_settings:
            mock_settings.sql_row_limit = 100
            with patch("sqlalchemy.text", side_effect=lambda s: s):
                result = eng._run_query("SELECT id FROM t", limit=100)
        assert result["truncated"] is False

    def test_row_values_are_coerced(self):
        eng = _make_engine({"project": "p"})
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        dt = datetime.date(2024, 6, 1)
        cursor = self._make_mock_cursor(["d"], [(dt,)])
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = cursor
        mock_engine.connect.return_value = mock_conn
        eng._engine = mock_engine

        with patch("analytics_agent.config.settings") as mock_settings:
            mock_settings.sql_row_limit = 100
            with patch("sqlalchemy.text", side_effect=lambda s: s):
                result = eng._run_query("SELECT d FROM t")
        assert result["rows"][0]["d"] == "2024-06-01"

    def test_returns_error_dict_on_query_failure(self):
        eng = _make_engine({"project": "p"})
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.side_effect = Exception("syntax error")
        mock_engine.connect.return_value = mock_conn
        eng._engine = mock_engine

        with patch("analytics_agent.config.settings") as mock_settings:
            mock_settings.sql_row_limit = 100
            with patch("sqlalchemy.text", side_effect=lambda s: s):
                result = eng._run_query("BAD SQL")
        assert "error" in result
        assert "syntax error" in result["error"]


# ---------------------------------------------------------------------------
# get_tools
# ---------------------------------------------------------------------------


class TestGetTools:
    def test_returns_four_tools(self):
        eng = _make_engine(_cfg_with_creds())
        tools = eng.get_tools()
        assert len(tools) == 4

    def test_tool_names(self):
        eng = _make_engine(_cfg_with_creds())
        names = {t.name for t in eng.get_tools()}
        assert names == {"execute_sql", "list_tables", "get_schema", "preview_table"}


# ---------------------------------------------------------------------------
# aclose
# ---------------------------------------------------------------------------


class TestAclose:
    @pytest.mark.asyncio
    async def test_disposes_engine_and_clears_state(self):
        eng = _make_engine({"project": "p"})
        mock_engine = MagicMock()
        eng._engine = mock_engine
        await eng.aclose()
        mock_engine.dispose.assert_called_once()
        assert eng._engine is None

    @pytest.mark.asyncio
    async def test_aclose_noop_when_no_engine(self):
        eng = _make_engine({"project": "p"})
        # Should not raise
        await eng.aclose()


# ---------------------------------------------------------------------------
# datahub_platform property
# ---------------------------------------------------------------------------


def test_datahub_platform_name():
    eng = _make_engine({"project": "p"})
    assert eng.datahub_platform == "bigquery"
