"""Tests for _apply_row_limit — the helper that appends LIMIT only to SELECT statements."""

import pytest
from analytics_agent.engines.base import _apply_row_limit

# ---------------------------------------------------------------------------
# Parametrize format: (description, sql, limit, expected_suffix_or_full)
# We check that the result equals the expected string exactly.
# ---------------------------------------------------------------------------

SELECT_CASES = [
    # Basic SELECT — limit should be appended
    ("simple select", "SELECT * FROM foo", 500, "SELECT * FROM foo LIMIT 500"),
    # Trailing semicolon stripped before limit added
    ("select with semicolon", "SELECT * FROM foo;", 500, "SELECT * FROM foo LIMIT 500"),
    # Leading/trailing whitespace stripped
    ("select with whitespace", "  SELECT * FROM foo  ", 500, "SELECT * FROM foo LIMIT 500"),
    # Lowercase keyword
    ("lowercase select", "select * from foo", 500, "select * from foo LIMIT 500"),
    # Mixed case keyword
    ("mixed case select", "Select * From foo", 500, "Select * From foo LIMIT 500"),
    # Multi-line SELECT
    (
        "multiline select",
        "SELECT\n  id,\n  name\nFROM foo\nWHERE id > 0",
        100,
        "SELECT\n  id,\n  name\nFROM foo\nWHERE id > 0 LIMIT 100",
    ),
    # SELECT with ORDER BY
    ("select with order by", "SELECT id FROM foo ORDER BY id DESC", 50, "SELECT id FROM foo ORDER BY id DESC LIMIT 50"),
    # SELECT with GROUP BY and HAVING
    (
        "select with group by having",
        "SELECT dept, COUNT(*) FROM emp GROUP BY dept HAVING COUNT(*) > 5",
        200,
        "SELECT dept, COUNT(*) FROM emp GROUP BY dept HAVING COUNT(*) > 5 LIMIT 200",
    ),
    # SELECT with JOIN
    (
        "select with join",
        "SELECT a.id, b.name FROM a JOIN b ON a.id = b.id",
        500,
        "SELECT a.id, b.name FROM a JOIN b ON a.id = b.id LIMIT 500",
    ),
    # Subquery in FROM
    (
        "select with subquery",
        "SELECT * FROM (SELECT id FROM foo WHERE active = 1) sub",
        500,
        "SELECT * FROM (SELECT id FROM foo WHERE active = 1) sub LIMIT 500",
    ),
    # UNION — outer statement starts with SELECT
    (
        "union select",
        "SELECT id FROM a UNION SELECT id FROM b",
        500,
        "SELECT id FROM a UNION SELECT id FROM b LIMIT 500",
    ),
]

ALREADY_LIMITED_CASES = [
    # Already has LIMIT — must not add another
    ("already has limit upper", "SELECT * FROM foo LIMIT 10", 500, "SELECT * FROM foo LIMIT 10"),
    ("already has limit lower", "select * from foo limit 10", 500, "select * from foo limit 10"),
    ("already has limit mixed", "SELECT * FROM foo Limit 10", 500, "SELECT * FROM foo Limit 10"),
    # LIMIT inside a subquery — contains LIMIT but at top level we should still not add
    (
        "limit in subquery",
        "SELECT * FROM (SELECT id FROM foo LIMIT 5) sub",
        500,
        "SELECT * FROM (SELECT id FROM foo LIMIT 5) sub",
    ),
]

NON_SELECT_CASES = [
    # SHOW commands (Hive, MySQL, Spark) — the original bug report
    ("show databases", "SHOW DATABASES", 500, "SHOW DATABASES"),
    ("show tables", "SHOW TABLES", 500, "SHOW TABLES"),
    ("show schemas", "SHOW SCHEMAS", 500, "SHOW SCHEMAS"),
    ("show columns", "SHOW COLUMNS FROM foo", 500, "SHOW COLUMNS FROM foo"),
    ("show create table", "SHOW CREATE TABLE foo", 500, "SHOW CREATE TABLE foo"),
    # lowercase show
    ("show databases lower", "show databases", 500, "show databases"),
    # INSERT
    ("insert values", "INSERT INTO foo (id) VALUES (1)", 500, "INSERT INTO foo (id) VALUES (1)"),
    ("insert select", "INSERT INTO foo SELECT * FROM bar", 500, "INSERT INTO foo SELECT * FROM bar"),
    # UPDATE
    ("update", "UPDATE foo SET x = 1 WHERE id = 2", 500, "UPDATE foo SET x = 1 WHERE id = 2"),
    # DELETE
    ("delete", "DELETE FROM foo WHERE id = 1", 500, "DELETE FROM foo WHERE id = 1"),
    # CREATE TABLE AS SELECT
    ("ctas", "CREATE TABLE new_table AS SELECT * FROM old_table", 500, "CREATE TABLE new_table AS SELECT * FROM old_table"),
    # CREATE TABLE
    ("create table", "CREATE TABLE foo (id INT)", 500, "CREATE TABLE foo (id INT)"),
    # DROP TABLE
    ("drop table", "DROP TABLE foo", 500, "DROP TABLE foo"),
    # ALTER TABLE
    ("alter table", "ALTER TABLE foo ADD COLUMN bar INT", 500, "ALTER TABLE foo ADD COLUMN bar INT"),
    # DESCRIBE / DESC
    ("describe", "DESCRIBE foo", 500, "DESCRIBE foo"),
    ("desc", "DESC foo", 500, "DESC foo"),
    # EXPLAIN
    ("explain", "EXPLAIN SELECT * FROM foo", 500, "EXPLAIN SELECT * FROM foo"),
    # TRUNCATE
    ("truncate", "TRUNCATE TABLE foo", 500, "TRUNCATE TABLE foo"),
    # WITH (CTE) — starts with WITH not SELECT; limit not added (documented behaviour)
    (
        "cte with",
        "WITH cte AS (SELECT id FROM foo) SELECT * FROM cte",
        500,
        "WITH cte AS (SELECT id FROM foo) SELECT * FROM cte",
    ),
    # MERGE
    ("merge", "MERGE INTO target USING source ON target.id = source.id WHEN MATCHED THEN UPDATE SET x = 1", 500,
     "MERGE INTO target USING source ON target.id = source.id WHEN MATCHED THEN UPDATE SET x = 1"),
    # CALL stored procedure
    ("call", "CALL my_proc()", 500, "CALL my_proc()"),
    # SET variable
    ("set variable", "SET search_path = myschema", 500, "SET search_path = myschema"),
]

NO_LIMIT_PARAM_CASES = [
    # limit=None means never append, regardless of statement type
    ("select no limit param", "SELECT * FROM foo", None, "SELECT * FROM foo"),
    ("show no limit param", "SHOW DATABASES", None, "SHOW DATABASES"),
    # Semicolon still stripped even with limit=None
    ("select semicolon no limit param", "SELECT * FROM foo;", None, "SELECT * FROM foo"),
]

EDGE_CASES = [
    # Semicolon stripped regardless
    ("show with semicolon", "SHOW DATABASES;", 500, "SHOW DATABASES"),
    ("insert with semicolon", "INSERT INTO foo VALUES (1);", 500, "INSERT INTO foo VALUES (1)"),
    # Extra internal whitespace preserved
    ("select extra spaces", "SELECT  *  FROM  foo", 500, "SELECT  *  FROM  foo LIMIT 500"),
    # Limit value of 1
    ("limit of 1", "SELECT id FROM foo", 1, "SELECT id FROM foo LIMIT 1"),
]

ALL_CASES = SELECT_CASES + ALREADY_LIMITED_CASES + NON_SELECT_CASES + NO_LIMIT_PARAM_CASES + EDGE_CASES


@pytest.mark.parametrize("description,sql,limit,expected", ALL_CASES, ids=[c[0] for c in ALL_CASES])
def test_apply_row_limit(description: str, sql: str, limit: int | None, expected: str) -> None:
    assert _apply_row_limit(sql, limit) == expected
