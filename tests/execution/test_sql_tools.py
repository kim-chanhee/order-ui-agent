"""격리된 SQLite DB로 검사·실행 도구의 허용·차단·교정 동작을 검증한다."""

import json
import sqlite3

import pytest

from app.execution import sql_builder, sql_tools
from app.planning.analysis_models import AnalysisPlan, MetricSpec


@pytest.fixture
def database(tmp_path, monkeypatch):
    """사용자 DB를 건드리지 않는 조회·중복·기간 테스트 데이터를 준비한다."""
    path = tmp_path / "orders.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE orders (order_id TEXT, status TEXT, created_at TEXT, product_name TEXT)")
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", [
            ("1", "paid", "2026-10-18 10:00:00", "Alpha"),
            ("1", "paid", "2026-10-19 08:00:00", "Alpha"),
            ("2", "pending", "2026-10-20 10:00:00", "Beta"),
            ("3", "paid", "2026-10-20 18:45:00", "Gamma"),
        ])
    monkeypatch.setattr(sql_builder, "DEFAULT_DB_PATH", path)
    semantics = tmp_path / "semantics.json"
    semantics.write_text("{}")
    aliases = tmp_path / "aliases.json"
    aliases.write_text("{}")
    summary = tmp_path / "summary.md"
    summary.write_text("")
    monkeypatch.setenv("ANALYSIS_SEMANTICS_PATH", str(semantics))
    monkeypatch.setenv("SCHEMA_VALUE_ALIASES_PATH", str(aliases))
    monkeypatch.setenv("SCHEMA_SUMMARY_PATH", str(summary))
    return path


@pytest.fixture
def state(database):
    """테스트 DB의 확인된 스키마와 범주값을 두 도구에 공유한다."""
    return sql_tools.SqlToolState(
        inspected_tables={"orders"},
        require_schema_inspection=True,
        schema_context=[
            "orders(order_id TEXT, status TEXT, created_at TEXT, product_name TEXT)\n"
            "status values: paid, pending"
        ],
    )


def pipeline(state, **kwargs):
    """동일한 검증 기준과 상태를 쓰는 검사·실행 도구를 만든다."""
    checker = sql_tools.make_query_checker_tool(state=state, **kwargs)
    executor, successes = sql_tools.make_execute_query_tool(state=state, **kwargs)
    return checker, executor, successes


def test_checked_distinct_count_executes_once_and_preserves_raw_result(state):
    plan = AnalysisPlan(original_question="전체 주문 수", metric=MetricSpec(kind="count", field="order_id"))
    checker, executor, successes = pipeline(state, confirmed_plan=plan)
    sql = "SELECT COUNT(DISTINCT order_id) AS order_count FROM orders"
    assert checker.invoke({"sql": sql}) == sql
    result = executor.invoke({"sql": sql})
    assert not result.startswith("Error"), result
    assert successes == [(sql, ["order_count"], [{"order_count": 3}])]


@pytest.mark.parametrize("sql", [
    "UPDATE orders SET status = 'paid'",
    "DELETE FROM orders",
    "DROP TABLE orders",
    "INSERT INTO orders VALUES ('4', 'paid', '2026-10-20', 'Delta')",
    "PRAGMA user_version = 2",
    "SELECT 1; SELECT 2",
])
def test_unsafe_or_multiple_statements_never_reach_execution(state, database, sql):
    checker, executor, successes = pipeline(state)
    assert checker.invoke({"sql": sql}).startswith("Error:")
    assert executor.invoke({"sql": sql}).startswith("Error:")
    assert not state.checked_queries and not successes
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 4
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0


def test_execution_requires_the_exact_checked_query(state):
    checker, executor, successes = pipeline(state)
    first = "SELECT order_id FROM orders"
    second = "SELECT status FROM orders"
    assert "query_checker must be called" in executor.invoke({"sql": first})
    assert checker.invoke({"sql": first}) == first
    assert "query_checker must be called" in executor.invoke({"sql": second})
    assert not successes


def test_execution_requires_schema_inspection_for_every_table(state):
    state.inspected_tables.clear()
    checker, executor, successes = pipeline(state)
    sql = "SELECT order_id FROM orders"
    assert checker.invoke({"sql": sql}) == sql
    assert "Missing: orders" in executor.invoke({"sql": sql})
    assert not successes


@pytest.mark.parametrize("sql, error", [
    ("SELECT missing_column FROM orders", "unknown_column"),
    ("SELECT order_id FROM missing_table", "unknown_table"),
])
def test_unknown_schema_references_are_rejected(state, sql, error):
    checker, _, successes = pipeline(state)
    assert error in checker.invoke({"sql": sql})
    assert not state.checked_queries and not successes


def test_execution_revalidates_schema_after_successful_check(state):
    checker, executor, successes = pipeline(state)
    sql = "SELECT status FROM orders"
    assert checker.invoke({"sql": sql}) == sql
    state.schema_context[:] = ["orders(order_id TEXT)"]
    assert "unknown_column" in executor.invoke({"sql": sql})
    assert not successes


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(order_id) AS order_count FROM orders",
    "SELECT COUNT(DISTINCT product_name) AS order_count FROM orders",
])
def test_count_plan_rejects_duplicate_or_wrong_count_unit(state, sql):
    plan = AnalysisPlan(original_question="주문 수", metric=MetricSpec(kind="count", field="order_id"))
    checker, _, _ = pipeline(state, confirmed_plan=plan)
    assert checker.invoke({"sql": sql}).startswith("Error:")
    assert not state.checked_queries


def test_generic_distinct_count_still_requires_a_stable_identifier(state):
    plan = {"metric": {"kind": "count", "distinct": True}}
    checker, _, _ = pipeline(state, confirmed_plan=plan)
    result = checker.invoke({"sql": "SELECT COUNT(DISTINCT status) FROM orders"})
    assert "stable *_id" in result


def test_result_contract_rejects_missing_requested_display_name(state):
    plan = AnalysisPlan(
        original_question="상품 이름", target_entity="product",
        requested_attributes=["display_name"], result_grain="distinct_product",
    )
    checker, executor, successes = pipeline(state, confirmed_plan=plan)
    sql = "SELECT DISTINCT order_id FROM orders"
    assert checker.invoke({"sql": sql}) == sql
    assert "missing_display_name" in executor.invoke({"sql": sql})
    assert not successes


def test_ungrounded_categorical_filter_is_rejected(state):
    checker, _, _ = pipeline(state, question="주문 목록")
    result = checker.invoke({"sql": "SELECT order_id FROM orders WHERE status = 'cancelled'"})
    assert "not grounded" in result
    assert not state.checked_queries


def test_followup_cannot_add_a_new_filter_even_if_it_exists_in_schema(state):
    history = [{"question": "결제 주문", "sql": "SELECT order_id FROM orders WHERE status = 'paid'"}]
    question = "그 주문 목록\nPrevious results from this thread\n" + json.dumps(history)
    checker, _, _ = pipeline(state, question=question)
    result = checker.invoke({"sql": "SELECT order_id FROM orders WHERE status = 'pending'"})
    assert "unrequested categorical filter" in result


def test_relative_period_rewrite_is_executed_when_original_sql_is_submitted(state):
    checker, executor, successes = pipeline(
        state, question="최근 2일 주문", temporal_context={
            "mode": "relative", "relative_days": 2,
            "anchor_table": "orders", "anchor_field": "created_at",
        },
    )
    sql = (
        "WITH anchor AS (SELECT MAX(created_at) AS anchor_at FROM orders) "
        "SELECT order_id, created_at FROM orders CROSS JOIN anchor "
        "WHERE created_at >= date(anchor_at, '-1 days') "
        "AND created_at <= date(anchor_at) ORDER BY created_at"
    )
    checked = checker.invoke({"sql": sql})
    assert not checked.startswith("Error"), checked
    assert "< date(anchor_at, '+1 day')" in checked
    result = executor.invoke({"sql": sql})
    assert not result.startswith("Error"), result
    assert successes[0][0] == checked
    assert [row["order_id"] for row in successes[0][2]] == ["1", "2", "3"]


def test_relative_period_rejects_machine_clock(state):
    checker, _, _ = pipeline(state, temporal_context={"mode": "relative", "relative_days": 2})
    result = checker.invoke({"sql": "SELECT order_id FROM orders WHERE created_at >= CURRENT_DATE"})
    assert "not the machine clock" in result


def test_execution_revalidates_the_distinct_count_plan(state):
    plan = {"metric": {"kind": "count", "distinct": True, "field": "order_id"}}
    checker, executor, successes = pipeline(state, confirmed_plan=plan)
    sql = "SELECT COUNT(DISTINCT order_id) AS order_count FROM orders"
    assert checker.invoke({"sql": sql}) == sql
    # 검사 후 계획이 바뀌었더라도 실행 직전에 현재 집계 단위를 다시 확인한다.
    plan["metric"]["field"] = "id"
    assert executor.invoke({"sql": sql}).startswith("Error:")
    assert not successes


def test_result_truncation_remains_visible_to_caller(state, monkeypatch):
    monkeypatch.setattr(sql_tools, "MAX_RESULT_ROWS", 2)
    checker, executor, successes = pipeline(state)
    sql = "SELECT order_id FROM orders ORDER BY created_at"
    assert checker.invoke({"sql": sql}) == sql
    assert "최대 2행" in executor.invoke({"sql": sql})
    assert len(successes[0][2]) == state.last_returned_row_count == 2
    assert state.last_result_truncated


def test_configured_creation_predicate_is_still_enforced(state, monkeypatch):
    semantics = {"entity_lifecycles": {"order": {
        "table": "orders", "creation_field": "status", "creation_value": "paid", "id_field": "order_id",
    }}}
    from app.execution import analysis_semantics, sql_contract
    monkeypatch.setattr(sql_contract, "load_analysis_semantics", lambda: semantics)
    monkeypatch.setattr(analysis_semantics, "load_analysis_semantics", lambda: semantics)
    checker, _, _ = pipeline(state, confirmed_plan={"target_entity": "order"}, temporal_context={"mode": "relative"})
    result = checker.invoke({"sql": "SELECT order_id FROM orders WHERE status = 'pending'"})
    assert "missing_creation_predicate" in result


@pytest.mark.parametrize("mode", ["baseline", "agent2ui"])
def test_mode_service_runs_real_agent_tools_and_returns_result(state, monkeypatch, mode):
    """LLM 응답만 대체하고 두 모드의 서비스→에이전트→검사→DB→응답을 검증한다."""
    from unittest.mock import Mock
    from langchain_core.messages import AIMessage
    from app.execution import fast_sql_agent, schema_tools
    from app.execution.a2ui import service as a2ui_service
    from app.execution.baseline import service as baseline_service
    from app.planning.ui_models import UiPlan
    from app.routes.a2ui.schemas import ConfirmDraftRequest
    from app.routes.schemas import ChatRequest

    monkeypatch.setattr(schema_tools, "DEFAULT_DB_PATH", sql_builder.DEFAULT_DB_PATH)
    monkeypatch.setattr(fast_sql_agent, "resolve_agent_llm_settings", lambda: ("test", "", "test-key", "test-model", 5))
    sql = "SELECT COUNT(DISTINCT order_id) AS order_count FROM orders"
    model = Mock()
    model.bind_tools.return_value.invoke.side_effect = [
        AIMessage(content="", tool_calls=[{"name": "query_checker", "args": {"sql": sql}, "id": "check-1"}]),
        AIMessage(content="", tool_calls=[{"name": "execute_query", "args": {"sql": sql}, "id": "execute-1"}]),
        AIMessage(content="고유 주문은 3건입니다."),
    ]
    monkeypatch.setattr(fast_sql_agent, "ChatOpenAI", lambda **kwargs: model)
    question = "전체 주문 수"
    plan = UiPlan(summary=question, analysis_plan=AnalysisPlan(
        original_question=question, metric=MetricSpec(kind="count", field="order_id"),
    ))
    if mode == "baseline":
        monkeypatch.setattr(baseline_service, "build_review_plan", lambda *args, **kwargs: plan)
        monkeypatch.setattr(baseline_service, "agent_cache_context", lambda *args: {})
        response = baseline_service.baseline_response_payload(
            ChatRequest(question=question), thread_id="test-thread", routing_context=[],
        )
    else:
        monkeypatch.setattr(a2ui_service, "agent_cache_context", lambda *args: {})
        response = a2ui_service.confirm_response_payload(ConfirmDraftRequest(
            question=question, thread_id="test-thread", plan=plan, surface_id="test-surface", revision=1,
        ))
    execution = response["execution_result"]
    normalized = execution["normalized_spec"]
    assert normalized["fallback_used"] is False, normalized.get("fallback_error")
    assert execution["input_source"] == mode
    assert normalized["analysis_execution"]["rows"] == [{"order_count": 3}]
    assert response["a2ui_surface"]
    assert model.bind_tools.return_value.invoke.call_count == 3
