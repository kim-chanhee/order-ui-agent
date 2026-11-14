"""CTE 범위와 SQLite 식별자 규칙을 반영한 물리 테이블 추출을 검증한다."""

import pytest

from app.execution.sql.sql_ast import (
    extract_filter_literals,
    extract_physical_tables,
    parse_sql_ast,
    physical_tables_from_tree,
)


@pytest.mark.parametrize("sql, expected", [
    ("SELECT 1", set()),
    ("SELECT * FROM Orders o JOIN Items i ON o.id = i.order_id", {"Orders", "Items"}),
    ("WITH recent AS (SELECT * FROM Orders) SELECT * FROM recent", {"Orders"}),
    (
        "SELECT * FROM orders WHERE EXISTS ("
        "WITH orders AS (SELECT * FROM archived_orders) SELECT * FROM orders)",
        {"orders", "archived_orders"},
    ),
    (
        "WITH recent AS (SELECT * FROM Orders) "
        "SELECT * FROM recent WHERE EXISTS ("
        "WITH recent AS (SELECT * FROM Items) SELECT * FROM recent)",
        {"Orders", "Items"},
    ),
    (
        'WITH "Recent" AS (SELECT * FROM "Orders") SELECT * FROM "RECENT"',
        {"Orders"},
    ),
    (
        "WITH orders AS (SELECT * FROM main.orders) SELECT * FROM orders",
        {"orders"},
    ),
    (
        "WITH RECURSIVE chain AS (SELECT id FROM Orders UNION ALL "
        "SELECT o.id FROM Orders o JOIN chain c ON o.parent_id = c.id) "
        "SELECT * FROM chain",
        {"Orders"},
    ),
    (
        "SELECT * FROM (WITH orders AS (SELECT * FROM Items) SELECT * FROM orders) a "
        "UNION ALL SELECT * FROM orders",
        {"Items", "orders"},
    ),
])
def test_physical_tables_respect_query_scopes_without_changing_tree(sql, expected):
    tree = parse_sql_ast(sql)
    original = tree.sql()
    assert physical_tables_from_tree(tree) == expected
    assert tree.sql() == original
    assert extract_physical_tables(sql) == expected


def test_filter_literals_exclude_date_modifiers_but_keep_business_values():
    sql = (
        "SELECT order_id FROM orders WHERE status = 'paid' "
        "AND created_at >= date('2026-10-20', '-1 days')"
    )
    assert set(extract_filter_literals(sql)) == {"paid", "2026-10-20"}
