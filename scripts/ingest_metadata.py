#!/usr/bin/env python3
"""
Register the Fiction Retail MySQL tables in DataHub via GraphQL:
  1. createIngestionSource — upsert a MySQL ingestion recipe
  2. createIngestionExecutionRequest — run it inside DataHub's executor
  3. Poll until SUCCESS, then patch in human-readable descriptions

The sink section is intentionally omitted from the recipe — DataHub fills it
in automatically so the executor can always reach the correct GMS endpoint.

Usage (from repo root):
    uv run python scripts/ingest_metadata.py [options]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

TABLE_DESCRIPTIONS: dict[str, str] = {
    "customers": "Retail customers with contact details, location, and segment classification",
    "orders": "Order records including status, payment method, and total amount",
    "order_items": "Line items linking orders to products with quantity, unit price, and discount",
    "products": "Product catalog with category, brand, price, and physical dimensions",
    "suppliers": "Supplier directory with country and contract information",
    "inventory": "Stock levels per product and warehouse with reorder thresholds",
    "warehouses": "Warehouse locations with capacity and operational details",
    "shipments": "Shipment tracking records with carrier, dates, and delivery state",
    "returns": "Return and refund records with reason codes",
    "promotions": "Promotional campaigns with discount rules, validity windows, and category scope",
}


def _gql(gms_url: str, token: str, query: str, variables: dict | None = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    req = urllib.request.Request(
        f"{gms_url}/api/graphql",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.loads(r.read())
    if "errors" in body:
        raise RuntimeError(f"GraphQL error: {body['errors']}")
    return body.get("data", {})


def _upsert_ingestion_source(gms_url: str, token: str, mysql_host_port: str, database: str, mysql_user: str, mysql_password: str) -> str:
    """Create (or update if already exists) the MySQL ingestion source. Returns the source URN."""

    recipe = json.dumps({
        "source": {
            "type": "mysql",
            "config": {
                "host_port": mysql_host_port,
                "database": database,
                "username": mysql_user,
                "password": mysql_password,
                "profile_pattern": {"deny": [".*"]},
            },
        }
        # sink intentionally omitted — DataHub infers the correct GMS endpoint
    })

    # Check if a source with our name already exists
    existing = _gql(gms_url, token, """
        { listIngestionSources(input: {start: 0, count: 50}) {
            ingestionSources { urn name }
        }}
    """)
    sources = existing.get("listIngestionSources", {}).get("ingestionSources", [])
    existing_urn = next((s["urn"] for s in sources if s["name"] == "Analytics Agent Demo — MySQL"), None)

    input_fields = {
        "name": "Analytics Agent Demo — MySQL",
        "type": "mysql",
        "description": f"Fiction Retail sample data in {database}",
        "config": {
            "recipe": recipe,
            "executorId": "default",
            "debugMode": False,
        },
    }

    if existing_urn:
        print(f"[→] Updating existing ingestion source: {existing_urn}")
        _gql(gms_url, token,
             "mutation($urn: String!, $input: UpdateIngestionSourceInput!) { updateIngestionSource(urn: $urn, input: $input) }",
             {"urn": existing_urn, "input": input_fields})
        return existing_urn
    else:
        print("[→] Creating ingestion source...")
        result = _gql(gms_url, token,
                      "mutation($input: UpdateIngestionSourceInput!) { createIngestionSource(input: $input) }",
                      {"input": input_fields})
        urn = result["createIngestionSource"]
        print(f"[✓] Ingestion source created: {urn}")
        return urn


def _run_and_wait(gms_url: str, token: str, source_urn: str, timeout_secs: int = 300) -> None:
    """Trigger an execution request and poll until it succeeds or fails."""
    result = _gql(gms_url, token,
                  "mutation($input: CreateIngestionExecutionRequestInput!) { createIngestionExecutionRequest(input: $input) }",
                  {"input": {"ingestionSourceUrn": source_urn}})
    exec_urn = result["createIngestionExecutionRequest"]
    print(f"[→] Execution started: {exec_urn}")

    deadline = time.time() + timeout_secs
    poll_interval = 5
    printf_dots = False
    while time.time() < deadline:
        time.sleep(poll_interval)
        r = _gql(gms_url, token,
                 "query($urn: String!) { executionRequest(urn: $urn) { result { status report } } }",
                 {"urn": exec_urn})
        result_data = (r.get("executionRequest") or {}).get("result") or {}
        status = result_data.get("status", "PENDING")

        if status in ("RUNNING", "PENDING"):
            print(".", end="", flush=True)
            printf_dots = True
            poll_interval = min(poll_interval + 2, 15)
            continue

        if printf_dots:
            print()

        if status == "SUCCESS":
            print("[✓] Ingestion pipeline succeeded")
            return

        # FAILURE or other terminal state
        report = result_data.get("report", "")
        raise RuntimeError(f"Ingestion execution {status}:\n{report[-500:]}")

    raise TimeoutError(f"Ingestion did not complete within {timeout_secs}s")


def _patch_descriptions(gms_url: str, token: str, database: str) -> None:
    """Emit human-readable descriptions on top of the ingested schema."""
    from datahub.emitter.rest_emitter import DatahubRestEmitter
    from datahub.metadata.schema_classes import (
        AuditStampClass, DatasetPropertiesClass,
        DatasetSnapshotClass, MetadataChangeEventClass,
    )

    emitter = DatahubRestEmitter(gms_server=gms_url, token=token or None)
    now_ms = int(time.time() * 1000)
    stamp = AuditStampClass(time=now_ms, actor="urn:li:corpuser:datahub")

    for table, description in TABLE_DESCRIPTIONS.items():
        urn = f"urn:li:dataset:(urn:li:dataPlatform:mysql,{database}.{table},PROD)"
        snapshot = DatasetSnapshotClass(
            urn=urn,
            aspects=[DatasetPropertiesClass(description=description, name=table)],
        )
        try:
            emitter.emit_mce(MetadataChangeEventClass(proposedSnapshot=snapshot))
            print(f"[✓] Description: {table}")
        except Exception as e:
            print(f"[!] Failed description for {table}: {e}", file=sys.stderr)
    emitter.flush()


def _seed_demo_context(gms_url: str, token: str, database: str) -> None:
    """Seed demo-ready tags, glossary terms, and table ownership for Fiction Retail tables."""
    from datahub.emitter.rest_emitter import DatahubRestEmitter
    from datahub.metadata.schema_classes import (
        AuditStampClass,
        DatasetSnapshotClass,
        GlobalTagsClass,
        GlossaryTermAssociationClass,
        GlossaryTermInfoClass,
        GlossaryTermsClass,
        GlossaryTermSnapshotClass,
        MetadataChangeEventClass,
        OwnerClass,
        OwnershipClass,
        OwnershipTypeClass,
        TagAssociationClass,
        TagPropertiesClass,
        TagSnapshotClass,
    )

    emitter = DatahubRestEmitter(gms_server=gms_url, token=token or None)
    now_ms = int(time.time() * 1000)
    stamp = AuditStampClass(time=now_ms, actor="urn:li:corpuser:datahub")

    def _dataset_urn(table: str) -> str:
        return f"urn:li:dataset:(urn:li:dataPlatform:mysql,{database}.{table},PROD)"

    # ── 1. Create tag entities ──────────────────────────────────────────────
    TAGS: dict[str, str] = {
        "pii": "Contains personally identifiable information",
        "financial": "Contains monetary values",
        "transactional": "Records individual business transactions",
        "reference_data": "Lookup or configuration data that changes infrequently",
    }
    for tag_name, description in TAGS.items():
        try:
            emitter.emit_mce(MetadataChangeEventClass(
                proposedSnapshot=TagSnapshotClass(
                    urn=f"urn:li:tag:{tag_name}",
                    aspects=[TagPropertiesClass(name=tag_name, description=description)],
                )
            ))
            print(f"[✓] Tag: {tag_name}")
        except Exception as e:
            print(f"[!] Failed tag {tag_name}: {e}", file=sys.stderr)

    # ── 2. Create glossary term entities ────────────────────────────────────
    TERMS: dict[str, dict[str, str]] = {
        "order_status": {
            "name": "Order Status",
            "definition": (
                "Lifecycle state of an order. Values: pending, processing, shipped, delivered, "
                "cancelled, returned."
            ),
        },
        "customer_segment": {
            "name": "Customer Segment",
            "definition": (
                "Classification of a customer based on purchase behavior or profile. "
                "Used to target promotions and personalize recommendations."
            ),
        },
        "discount_pct": {
            "name": "Discount Percentage",
            "definition": (
                "Percentage reduction applied to the unit price of an order item. "
                "Sourced from the applied promotion or negotiated directly."
            ),
        },
        "reorder_threshold": {
            "name": "Reorder Threshold",
            "definition": (
                "Minimum quantity_on_hand below which a restock should be triggered "
                "for a given product at a warehouse."
            ),
        },
        "return_reason_code": {
            "name": "Return Reason Code",
            "definition": (
                "Standardized code classifying why an item was returned. "
                "Used for quality tracking and supplier performance analysis."
            ),
        },
        "shipment_state": {
            "name": "Shipment State",
            "definition": (
                "Current status of a shipment in the fulfillment pipeline. "
                "Values: pending, in_transit, delivered, failed."
            ),
        },
    }
    for term_id, term in TERMS.items():
        try:
            emitter.emit_mce(MetadataChangeEventClass(
                proposedSnapshot=GlossaryTermSnapshotClass(
                    urn=f"urn:li:glossaryTerm:{term_id}",
                    aspects=[GlossaryTermInfoClass(
                        name=term["name"],
                        definition=term["definition"],
                        termSource="INTERNAL",
                    )],
                )
            ))
            print(f"[✓] Glossary term: {term['name']}")
        except Exception as e:
            print(f"[!] Failed glossary term {term_id}: {e}", file=sys.stderr)

    # ── 3. Per-table: collect full tag/term/owner lists, emit one MCE each ──
    # All aspects for each table are bundled into a single DatasetSnapshotClass
    # so GlobalTagsClass and GlossaryTermsClass are each written exactly once —
    # a second emit of either aspect would replace the first (overwrite bug).
    TAG_MAP: dict[str, list[str]] = {
        "customers": ["pii"],
        "orders": ["financial", "transactional"],
        "order_items": ["financial", "transactional"],
        "shipments": ["transactional"],
        "returns": ["financial", "transactional"],
        "products": ["reference_data"],
        "suppliers": ["reference_data"],
        "warehouses": ["reference_data"],
        "promotions": ["reference_data"],
    }
    TERM_MAP: dict[str, list[str]] = {
        "orders": ["order_status"],
        "customers": ["customer_segment"],
        "order_items": ["discount_pct"],
        "inventory": ["reorder_threshold"],
        "returns": ["return_reason_code"],
        "shipments": ["shipment_state"],
    }
    OWNER_MAP: dict[str, str] = {
        "customers": "customer_team",
        "orders": "commerce_team",
        "order_items": "commerce_team",
        "products": "catalog_team",
        "suppliers": "catalog_team",
        "inventory": "logistics_team",
        "warehouses": "logistics_team",
        "shipments": "logistics_team",
        "returns": "finance_team",
        "promotions": "marketing_team",
    }
    for table in sorted(set(TAG_MAP) | set(TERM_MAP) | set(OWNER_MAP)):
        aspects: list = []
        tags = TAG_MAP.get(table, [])
        if tags:
            aspects.append(GlobalTagsClass(
                tags=[TagAssociationClass(tag=f"urn:li:tag:{t}") for t in tags]
            ))
        terms = TERM_MAP.get(table, [])
        if terms:
            aspects.append(GlossaryTermsClass(
                terms=[GlossaryTermAssociationClass(urn=f"urn:li:glossaryTerm:{t}") for t in terms],
                auditStamp=stamp,
            ))
        owner = OWNER_MAP.get(table)
        if owner:
            aspects.append(OwnershipClass(
                owners=[OwnerClass(
                    owner=f"urn:li:corpGroup:{owner}",
                    type=OwnershipTypeClass.TECHNICAL_OWNER,
                )],
                lastModified=stamp,
            ))
        if not aspects:
            continue
        try:
            emitter.emit_mce(MetadataChangeEventClass(
                proposedSnapshot=DatasetSnapshotClass(urn=_dataset_urn(table), aspects=aspects)
            ))
            print(f"[✓] Context: {table}")
        except Exception as e:
            print(f"[!] Failed context for {table}: {e}", file=sys.stderr)

    emitter.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Fiction Retail metadata into DataHub via GraphQL")
    parser.add_argument("--gms-url", default="http://localhost:8080")
    parser.add_argument("--token", default="")
    parser.add_argument("--database", default="analytics_agent_demo")
    parser.add_argument("--mysql-host-port", default="mysql:3306")
    parser.add_argument("--mysql-user", default="datahub")
    parser.add_argument("--mysql-password", default="datahub")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--skip-context-seed", action="store_true",
                        help="Skip seeding demo tags, glossary terms, and ownership")
    args = parser.parse_args()

    # 1. Test connectivity
    try:
        _gql(args.gms_url, args.token, "{ me { corpUser { username } } }")
        print(f"[✓] Connected to DataHub GMS at {args.gms_url}")
    except Exception as e:
        print(f"[✗] Cannot reach DataHub GMS: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. Upsert ingestion source
    source_urn = _upsert_ingestion_source(
        args.gms_url, args.token,
        args.mysql_host_port, args.database,
        args.mysql_user, args.mysql_password,
    )

    # 3. Run and wait
    print(f"[→] Running ingestion (timeout: {args.timeout}s)...")
    _run_and_wait(args.gms_url, args.token, source_urn, timeout_secs=args.timeout)

    # 4. Patch descriptions
    print()
    print("[→] Adding table descriptions...")
    _patch_descriptions(args.gms_url, args.token, args.database)

    # 5. Seed demo context
    if not args.skip_context_seed:
        print()
        print("[→] Seeding demo context (tags, glossary terms, ownership)...")
        _seed_demo_context(args.gms_url, args.token, args.database)
        print("[✓] Demo context seeded — 4 tags, 6 glossary terms, 10 table owners")

    print()
    print(f"[✓] Done — {len(TABLE_DESCRIPTIONS)} tables indexed and described in DataHub.")
    print(f"    View in DataHub UI: http://localhost:9002")


if __name__ == "__main__":
    main()
