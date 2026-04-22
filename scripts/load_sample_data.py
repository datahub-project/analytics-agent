#!/usr/bin/env python3
"""
Download the Olist e-commerce SQLite dataset and load it into MySQL.

Usage (from repo root):
    uv run python scripts/load_sample_data.py [options]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
import urllib.request
from pathlib import Path

OLIST_URL = (
    "https://github.com/datahub-project/static-assets/raw/main/"
    "datasets/olist-ecommerce/olist.db"
)

TABLES = [
    "olist_customers",
    "olist_orders",
    "olist_order_items",
    "olist_order_payments",
    "olist_order_reviews",
    "olist_products",
    "olist_sellers",
    "product_category_name_translation",
]

# Fields whose content is long free-text — map to MySQL TEXT instead of VARCHAR(255).
# NOTE: product_category_name and product_category_name_english are kept as VARCHAR(255)
# because they are join keys between tables; TEXT columns cannot be indexed without a
# prefix length in MySQL.
LONG_TEXT_FIELDS = {
    "review_comment_message",
    "review_comment_title",
    "product_description_lenght",  # intentional Olist typo
    "product_description_length",
}

BATCH_SIZE = 500


def _mysql_type(col_name: str, sqlite_type: str) -> str:
    """Map a SQLite declared type to an appropriate MySQL type."""
    t = sqlite_type.upper().strip()
    if t in ("INTEGER", "INT", "TINYINT", "SMALLINT", "MEDIUMINT", "BIGINT"):
        return "BIGINT"
    if t in ("REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL", "NUMBER"):
        return "DOUBLE"
    if t == "BLOB":
        return "LONGBLOB"
    # TEXT and VARCHAR fall through; also empty / unknown types
    if col_name.lower() in LONG_TEXT_FIELDS:
        return "TEXT"
    # Heuristic: long-text field names
    lower = col_name.lower()
    if any(lower.endswith(suffix) for suffix in ("_comment", "_message", "_title", "_desc", "_description")):
        return "TEXT"
    return "VARCHAR(255)"


def _download(url: str, dest: Path) -> None:
    """Download *url* to *dest*, printing a progress bar."""
    total_blocks = 0

    def reporthook(block_num: int, block_size: int, total_size: int) -> None:
        nonlocal total_blocks
        total_blocks = block_num
        if total_size <= 0:
            print(f"\r  downloaded {block_num * block_size:,} bytes", end="", flush=True)
        else:
            pct = min(100, block_num * block_size * 100 // total_size)
            bar = "#" * (pct // 2) + "-" * (50 - pct // 2)
            print(f"\r  [{bar}] {pct:3d}%", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=reporthook)
    print()  # newline after progress bar


def _build_create_table(table: str, columns: list[tuple]) -> str:
    """
    Build a MySQL CREATE TABLE statement from PRAGMA table_info rows.

    PRAGMA columns: cid, name, type, notnull, dflt_value, pk
    """
    col_defs: list[str] = []
    pk_cols: list[str] = []
    for cid, name, col_type, notnull, dflt_value, pk in columns:
        mysql_t = _mysql_type(name, col_type)
        null_clause = "NOT NULL" if notnull else "NULL"
        col_defs.append(f"  `{name}` {mysql_t} {null_clause}")
        if pk:
            pk_cols.append(f"`{name}`")
    if pk_cols:
        col_defs.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")
    cols_sql = ",\n".join(col_defs)
    return f"CREATE TABLE `{table}` (\n{cols_sql}\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Olist sample data into MySQL")
    parser.add_argument("--host", default="localhost", help="MySQL host (default: localhost)")
    parser.add_argument("--port", type=int, default=3306, help="MySQL port (default: 3306)")
    parser.add_argument("--user", default="datahub", help="MySQL user for data loading (default: datahub)")
    parser.add_argument("--password", default="datahub", help="MySQL password for data loading (default: datahub)")
    parser.add_argument(
        "--database", default="analytics_agent_demo", help="MySQL database name (default: analytics_agent_demo)"
    )
    # Admin credentials are only used for CREATE DATABASE + GRANT — the regular
    # user (--user) may not have permission to create databases.
    parser.add_argument("--admin-user", default="root", help="MySQL admin user for CREATE DATABASE (default: root)")
    parser.add_argument("--admin-password", default="datahub", help="MySQL admin password (default: datahub)")
    args = parser.parse_args()

    try:
        import pymysql
    except ImportError:
        print("[!] pymysql not found. Add it to pyproject.toml and run: uv sync", file=sys.stderr)
        sys.exit(1)

    # --- 1. Download SQLite file ---
    print(f"[→] Downloading Olist dataset from GitHub...")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        _download(OLIST_URL, tmp_path)
        print(f"[✓] Downloaded to {tmp_path} ({tmp_path.stat().st_size:,} bytes)")

        # --- 2. Open SQLite ---
        sqlite_conn = sqlite3.connect(str(tmp_path))
        sqlite_conn.row_factory = sqlite3.Row

        db = args.database

        # --- 3. Create database + grant access (requires admin/root privileges) ---
        print(f"[→] Connecting to MySQL at {args.host}:{args.port} as admin ({args.admin_user}) ...")
        admin_conn = pymysql.connect(
            host=args.host,
            port=args.port,
            user=args.admin_user,
            password=args.admin_password,
            charset="utf8mb4",
            autocommit=True,
        )
        admin_cur = admin_conn.cursor()
        admin_cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        # Grant the regular user full access to the new database
        admin_cur.execute(f"GRANT ALL PRIVILEGES ON `{db}`.* TO '{args.user}'@'%'")
        admin_cur.execute("FLUSH PRIVILEGES")
        admin_cur.close()
        admin_conn.close()
        print(f"[✓] Database `{db}` ready (granted to {args.user})")

        # --- 4. Connect as regular user for data loading ---
        print(f"[→] Connecting as {args.user} for data load ...")
        mysql_conn = pymysql.connect(
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            database=db,
            charset="utf8mb4",
            autocommit=False,
        )
        mysql_cur = mysql_conn.cursor()

        # --- 5. Load each table ---
        total_rows = 0
        for table in TABLES:
            sqlite_cur = sqlite_conn.cursor()
            # Get schema
            sqlite_cur.execute(f"PRAGMA table_info({table})")
            columns = sqlite_cur.fetchall()
            if not columns:
                print(f"[!] Table '{table}' not found in SQLite — skipping")
                continue

            col_names = [row[1] for row in columns]
            placeholders = ", ".join(["%s"] * len(col_names))
            quoted_names = ", ".join([f"`{n}`" for n in col_names])

            create_sql = _build_create_table(table, columns)

            # Drop + Create in MySQL
            mysql_cur.execute(f"DROP TABLE IF EXISTS `{table}`")
            mysql_cur.execute(create_sql)
            mysql_conn.commit()

            # Fetch all rows from SQLite
            sqlite_cur.execute(f"SELECT * FROM {table}")
            rows = sqlite_cur.fetchall()
            row_count = len(rows)

            # Insert in batches
            insert_sql = f"INSERT INTO `{table}` ({quoted_names}) VALUES ({placeholders})"
            for offset in range(0, row_count, BATCH_SIZE):
                batch = [tuple(row) for row in rows[offset : offset + BATCH_SIZE]]
                mysql_cur.executemany(insert_sql, batch)
                mysql_conn.commit()

            total_rows += row_count
            print(f"[✓] {table}: {row_count:,} rows loaded")

        # --- 6. Done ---
        mysql_cur.close()
        mysql_conn.close()
        sqlite_conn.close()

        print()
        print(f"[✓] Done! {total_rows:,} total rows loaded into `{db}` across {len(TABLES)} tables.")
        print(f"    MySQL: {args.host}:{args.port}/{db}")

    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
