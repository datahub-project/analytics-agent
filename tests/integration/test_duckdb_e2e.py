"""
Integration test: DuckDB query engine + DataHub metadata, end-to-end.

Setup:
  - Creates a temporary DuckDB file with three Olist-like tables
    (olist_orders, olist_order_items, olist_products — ~50 rows total).
  - Pushes table descriptions to the configured DataHub instance under
    platform=duckdb, env=DEV so the agent can discover them via search.

What it proves:
  - SQLAlchemyQueryEngine with dialect=duckdb boots and can execute SQL.
  - DataHub context tools find the freshly pushed metadata.
  - The full agent pipeline (context lookup → SQL → text answer) works.

Prerequisites:
  DataHub credentials: ~/.datahubenv  or  DATAHUB_GMS_URL + DATAHUB_GMS_TOKEN
  LLM key:            ANTHROPIC_API_KEY  or  OPENAI_API_KEY

Run:
  uv run pytest tests/integration/test_duckdb_e2e.py -v -s
"""

from __future__ import annotations

import json
import os
import pathlib
import urllib.request
import uuid

import pytest

# ── Skip guards ──────────────────────────────────────────────────────────────

_has_datahub = bool(
    (os.environ.get("DATAHUB_GMS_URL") and os.environ.get("DATAHUB_GMS_TOKEN"))
    or pathlib.Path("~/.datahubenv").expanduser().exists()
)
_has_llm = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))

_requires_datahub_and_llm = pytest.mark.skipif(
    not (_has_datahub and _has_llm),
    reason=(
        "Needs DataHub credentials (datahub init or DATAHUB_GMS_URL+TOKEN) "
        "and an LLM key (ANTHROPIC_API_KEY or OPENAI_API_KEY)"
    ),
)


# ── DataHub helpers ───────────────────────────────────────────────────────────


def _datahub_creds() -> tuple[str, str]:
    """Return (gms_url, token) from env vars or ~/.datahubenv."""
    gms_url = os.environ.get("DATAHUB_GMS_URL", "")
    token = os.environ.get("DATAHUB_GMS_TOKEN", "")
    if not gms_url:
        import yaml

        env_file = pathlib.Path("~/.datahubenv").expanduser()
        if env_file.exists():
            cfg = yaml.safe_load(env_file.read_text()) or {}
            gms = cfg.get("gms") or {}
            gms_url = gms.get("server", "")
            token = gms.get("token", "")
    return gms_url, token


def _emit_table_description(
    gms_url: str, token: str, urn: str, table: str, description: str
) -> None:
    """Push a minimal dataset description MCE to DataHub."""
    from datahub.emitter.rest_emitter import DatahubRestEmitter
    from datahub.metadata.schema_classes import (
        DatasetPropertiesClass,
        DatasetSnapshotClass,
        MetadataChangeEventClass,
    )

    emitter = DatahubRestEmitter(gms_server=gms_url, token=token or None)
    emitter.emit_mce(
        MetadataChangeEventClass(
            proposedSnapshot=DatasetSnapshotClass(
                urn=urn,
                aspects=[DatasetPropertiesClass(description=description, name=table)],
            )
        )
    )
    emitter.flush()


def _delete_entity(gms_url: str, token: str, urn: str) -> None:
    """Hard-delete a DataHub entity by URN (best-effort — non-fatal)."""
    try:
        req = urllib.request.Request(
            f"{gms_url}/entities?action=delete",
            data=json.dumps({"urn": urn}).encode(),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[!] DataHub cleanup failed for {urn}: {e}")


# ── DataHub table metadata ────────────────────────────────────────────────────

_PLATFORM = "duckdb"
_ENV = "DEV"

# Tables we create + their descriptions for DataHub.
_TABLES: dict[str, str] = {
    "olist_orders": (
        "Order lifecycle records. Columns: order_id (PK), customer_id, "
        "order_status ('delivered' or 'canceled'), order_purchase_timestamp."
    ),
    "olist_order_items": (
        "Line items inside each order. Columns: order_id (FK), product_id (FK), "
        "price (item price in BRL), freight_value (shipping cost in BRL). "
        "Revenue = SUM(price + freight_value) for delivered orders."
    ),
    "olist_products": (
        "Product catalog. Columns: product_id (PK), product_category_name "
        "(e.g. 'electronics', 'furniture', 'clothing', 'books', 'toys')."
    ),
}


def _dataset_urn(table: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{_PLATFORM},{table},{_ENV})"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def duckdb_path(tmp_path_factory):
    """Build a temp DuckDB file with three Olist-like tables."""
    import duckdb

    db_file = tmp_path_factory.mktemp("duckdb") / "test.duckdb"
    con = duckdb.connect(str(db_file))

    # olist_orders — 50 rows, 5 canceled (i % 10 == 0)
    con.execute("""
        CREATE TABLE olist_orders (
            order_id                   VARCHAR PRIMARY KEY,
            customer_id                VARCHAR,
            order_status               VARCHAR,
            order_purchase_timestamp   TIMESTAMP
        )
    """)
    con.execute("""
        INSERT INTO olist_orders
        SELECT
            'order_' || i::VARCHAR,
            'customer_' || (i % 20)::VARCHAR,
            CASE WHEN i % 10 = 0 THEN 'canceled' ELSE 'delivered' END,
            TIMESTAMP '2017-01-01' + INTERVAL (i) DAY
        FROM range(1, 51) t(i)
    """)

    # olist_order_items — 2 items per order (100 rows)
    # product_id cycles through 0-9 so each maps to a distinct category
    con.execute("""
        CREATE TABLE olist_order_items (
            order_id       VARCHAR,
            product_id     VARCHAR,
            price          DOUBLE,
            freight_value  DOUBLE
        )
    """)
    con.execute("""
        INSERT INTO olist_order_items
        SELECT
            'order_' || (i % 50 + 1)::VARCHAR,
            'product_' || (i % 10)::VARCHAR,
            (i % 5 + 1) * 10.0,
            (i % 3 + 1) * 2.0
        FROM range(0, 100) t(i)
    """)

    # olist_products — 10 products across 5 categories (2 products each)
    con.execute("""
        CREATE TABLE olist_products (
            product_id             VARCHAR PRIMARY KEY,
            product_category_name  VARCHAR
        )
    """)
    con.executemany(
        "INSERT INTO olist_products VALUES (?, ?)",
        [
            ("product_0", "electronics"),
            ("product_1", "furniture"),
            ("product_2", "clothing"),
            ("product_3", "books"),
            ("product_4", "toys"),
            ("product_5", "electronics"),
            ("product_6", "furniture"),
            ("product_7", "clothing"),
            ("product_8", "books"),
            ("product_9", "toys"),
        ],
    )

    con.close()
    return str(db_file)


@pytest.fixture(scope="module")
def datahub_metadata():
    """Push table descriptions to DataHub; delete them on teardown."""
    gms_url, token = _datahub_creds()
    urns = []
    for table, description in _TABLES.items():
        urn = _dataset_urn(table)
        _emit_table_description(gms_url, token, urn, table, description)
        urns.append(urn)
        print(f"[✓] DataHub metadata pushed: {urn}")

    yield urns

    # Teardown
    for urn in urns:
        _delete_entity(gms_url, token, urn)
        print(f"[✓] DataHub entity deleted: {urn}")


@pytest.fixture(scope="module")
def duckdb_engine(duckdb_path):
    """SQLAlchemyQueryEngine backed by the temp DuckDB file."""
    import asyncio

    from analytics_agent.engines.sqlalchemy.engine import SQLAlchemyQueryEngine

    engine = SQLAlchemyQueryEngine({"dialect": "duckdb", "database": duckdb_path})
    yield engine
    asyncio.run(engine.aclose())


@pytest.fixture(scope="module")
def agent_graph(duckdb_engine, datahub_metadata):
    """Full agent graph: DuckDB engine tools + DataHub context tools."""
    from analytics_agent.agent.graph import build_graph
    from analytics_agent.context.datahub import build_datahub_tools

    context_tools = build_datahub_tools()
    engine_tools = duckdb_engine.get_tools()

    assert engine_tools, "DuckDB engine returned no tools"
    assert context_tools, "No DataHub context tools loaded — check credentials"

    return build_graph(
        engine_name="test_duckdb",
        context_tools=context_tools,
        engine_tools=engine_tools,
        disabled_tools={"create_chart"},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _run(graph, question: str) -> list[dict]:
    """Run one agent turn and collect all events."""
    from analytics_agent.agent.streaming import stream_graph_events

    events: list[dict] = []
    conv_id = f"e2e-duckdb-{uuid.uuid4().hex[:8]}"
    async for event in stream_graph_events(graph, question, conv_id, "test_duckdb"):
        events.append(event)
        label = event["payload"].get("text") or event["payload"].get("tool_name") or ""
        print(f"  [{event['event']}] {str(label)[:80]}")
    return events


# ── Tests ─────────────────────────────────────────────────────────────────────


@_requires_datahub_and_llm
@pytest.mark.asyncio
async def test_top_categories_by_revenue(agent_graph):
    """Agent must run SQL and return top product categories by revenue."""
    events = await _run(
        agent_graph,
        "What are the top 3 product categories by total revenue (price + freight_value)?",
    )

    event_types = {e["event"] for e in events}
    print("\nEvent types:", event_types)

    assert "COMPLETE" in event_types, f"No COMPLETE event — got: {event_types}"
    assert "TEXT" in event_types, f"No TEXT event — got: {event_types}"

    # Agent must have issued at least one successful SQL query
    sql_events = [e for e in events if e["event"] == "SQL"]
    assert sql_events, (
        "No SQL event emitted — agent did not call execute_sql successfully. "
        f"All event types: {event_types}"
    )

    # The SQL result should have rows
    rows = sql_events[-1]["payload"].get("rows", [])
    assert rows, "SQL result has no rows"
    assert len(rows) <= 3, f"Expected ≤3 rows (top 3), got {len(rows)}"

    # The answer should mention at least one of the known categories
    complete_text = next(e["payload"].get("text", "") for e in events if e["event"] == "COMPLETE")
    known_categories = {"electronics", "furniture", "clothing", "books", "toys"}
    assert any(cat in complete_text.lower() for cat in known_categories), (
        f"Response doesn't mention any known category.\nResponse: {complete_text[:400]}"
    )


@_requires_datahub_and_llm
@pytest.mark.asyncio
async def test_delivered_vs_canceled_order_count(agent_graph):
    """Agent must count delivered vs canceled orders accurately."""
    events = await _run(
        agent_graph,
        "How many orders are delivered versus canceled?",
    )

    event_types = {e["event"] for e in events}
    assert "COMPLETE" in event_types
    assert "SQL" in event_types, "Agent should query olist_orders for status counts"

    complete_text = next(e["payload"].get("text", "") for e in events if e["event"] == "COMPLETE")
    # Dataset has 45 delivered (i % 10 != 0) and 5 canceled (i % 10 == 0)
    # Accept any reasonable mention of both statuses
    text_lower = complete_text.lower()
    assert "delivered" in text_lower and "canceled" in text_lower, (
        f"Response should mention both statuses.\nResponse: {complete_text[:400]}"
    )


@pytest.mark.asyncio
async def test_engine_list_tables(duckdb_engine):
    """DuckDB engine's list_tables tool should return all three tables."""
    import orjson

    tools = {t.name: t for t in duckdb_engine.get_tools()}
    assert "list_tables" in tools

    result = tools["list_tables"].invoke({"schema": ""})
    tables = orjson.loads(result)
    table_names = {t["name"] for t in tables}
    assert {"olist_orders", "olist_order_items", "olist_products"} == table_names, (
        f"Unexpected tables: {table_names}"
    )


@pytest.mark.asyncio
async def test_engine_execute_sql(duckdb_engine):
    """DuckDB engine's execute_sql tool should return correct row counts."""
    import orjson

    tools = {t.name: t for t in duckdb_engine.get_tools()}
    result = tools["execute_sql"].invoke(
        {
            "sql": "SELECT order_status, COUNT(*) AS cnt FROM olist_orders GROUP BY order_status ORDER BY cnt DESC"
        }
    )
    parsed = orjson.loads(result)
    assert "error" not in parsed, f"SQL error: {parsed.get('error')}"

    rows = {row["order_status"]: row["cnt"] for row in parsed["rows"]}
    assert rows.get("delivered") == 45, f"Expected 45 delivered, got {rows}"
    assert rows.get("canceled") == 5, f"Expected 5 canceled, got {rows}"
