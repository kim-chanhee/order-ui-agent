"""LLM의 스키마 탐색·SQL 검사·실행 도구 호출을 조정하는 핵심 에이전트.

질문과 확정 계획에서 관련 테이블을 먼저 검색하고 스키마·관계·이전 사례를 준비한다.
LLM이 도구 결과와 오류를 보고 다음 도구를 선택하는 ReAct 루프를 수행한다.
복잡한 요청은 시간 여유가 있을 때 대안 SQL도 실행하고 후보별 점수로 결과를 선택한다.
일시적인 공급자·네트워크 오류만 재시도하며 반복 횟수와 전체 시간 예산을 관리한다.
검증된 SQL·원시 결과·최종 설명·호출 통계를 FastSqlResult에 담는다.
읽기 전용 보장과 의미 검사는 sql_tools 및 개별 검증 모듈에 위임한다.
"""

from __future__ import annotations

import os
import json
import random
from dataclasses import dataclass, field
from time import perf_counter, sleep
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.core.llm_settings import resolve_agent_llm_settings
from app.execution.confirmed_context import ConfirmedAnalysisContext
from app.execution.schema_tools import (
    discover_relationships,
    get_semantic_context,
    get_table_schema,
    list_tables,
    retrieve_relevant_schema,
)
from app.execution.sql_builder import _format_generic_sql_rows, explain_query_plan
from app.execution.sql_contract import SqlContractViolation, validate_sql_contract
from app.execution.sql_tools import (
    SqlToolState,
    make_execute_query_tool,
    make_query_checker_tool,
    normalize_sql,
)
from app.execution.temporal_policy import RELATIVE_TIME_POLICY
from app.execution.analysis_semantics import semantic_execution_context


FAST_SQL_TIMEOUT_SECONDS = float(os.environ.get("FAST_SQL_TIMEOUT_SECONDS", "20"))
FAST_SQL_TOTAL_TIMEOUT_SECONDS = float(os.environ.get("FAST_SQL_TOTAL_TIMEOUT_SECONDS", "45"))
FAST_SQL_MAX_TOKENS = int(os.environ.get("FAST_SQL_MAX_TOKENS", "1600"))
FAST_SQL_REACT_MAX_TURNS = int(os.environ.get("FAST_SQL_REACT_MAX_TURNS", "10"))
# ChatOpenAI keeps ``max_retries=0`` so a stuck call cannot silently eat the total
# budget; transient provider/network retries are handled here instead, with an
# explicit deadline check between attempts.
FAST_SQL_RATE_LIMIT_RETRIES = int(os.environ.get("FAST_SQL_RATE_LIMIT_RETRIES", "3"))
FAST_SQL_RATE_LIMIT_BACKOFF_SECONDS = float(
    os.environ.get("FAST_SQL_RATE_LIMIT_BACKOFF_SECONDS", "1.5")
)
FAST_SQL_COMPLEX_CANDIDATES = int(os.environ.get("FAST_SQL_COMPLEX_CANDIDATES", "2"))
FAST_SQL_MIN_ALTERNATIVE_SECONDS = float(
    os.environ.get("FAST_SQL_MIN_ALTERNATIVE_SECONDS", "8")
)


@dataclass(frozen=True)
class ModelErrorClassification:
    """모델 호출 오류의 분류명·재시도 가능 여부·HTTP 상태를 함께 보관한다.

    재시도 정책이 공급자 오류와 의미 오류를 구분하는 기준으로 사용한다.
    """

    category: str
    retryable: bool
    status_code: int | None = None


def _is_rate_limit_error(exc: BaseException) -> bool:
    """예외 클래스명·상태 코드·메시지에서 요청 한도 초과 여부를 찾는다.

    SDK마다 오류 표현이 달라도 429 계열을 공통으로 분류하기 위한 보조 함수다.
    """

    if exc.__class__.__name__ in {"RateLimitError", "TooManyRequestsError"}:
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status == 429 or status == "429":
        return True
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "too many requests" in text


def classify_model_error(exc: BaseException) -> ModelErrorClassification:
    """모델 호출 예외를 요청 한도·일시적 공급자 오류·인증·시간 초과·연결 오류 등으로 분류한다.

    재시도 여부와 상태 코드를 포함한 ModelErrorClassification을 반환한다.
    """

    raw_status = (
        getattr(exc, "status_code", None)
        or getattr(exc, "code", None)
        or getattr(getattr(exc, "response", None), "status_code", None)
    )
    try:
        status = int(raw_status) if raw_status is not None else None
    except (TypeError, ValueError):
        status = None
    name = exc.__class__.__name__.casefold()
    text = str(exc).casefold()
    if _is_rate_limit_error(exc):
        return ModelErrorClassification("provider_rate_limit", True, 429)
    if status in {408, 425, 500, 502, 503, 504}:
        return ModelErrorClassification("provider_transient", True, status)
    if status in {401, 403}:
        return ModelErrorClassification("provider_auth", False, status)
    if (
        isinstance(exc, TimeoutError)
        or "timeout" in name
        or "timed out" in text
        or "deadline exceeded" in text
    ):
        return ModelErrorClassification("network_timeout", True, status)
    if (
        isinstance(exc, ConnectionError)
        or "connection" in name
        or "connection reset" in text
        or "connection refused" in text
        or "temporarily unavailable" in text
    ):
        return ModelErrorClassification("network_connection", True, status)
    return ModelErrorClassification("model_non_retryable", False, status)


def classify_failure_message(error: str) -> dict[str, Any]:
    """실행 실패 문자열을 읽어 모델·스키마·계약 검증·SQL 실행 등의 실패 메타데이터로 변환한다.

    명시된 패턴으로 분류할 수 없으면 unknown/unclassified로 남긴다.
    """

    lowered = error.casefold()
    if "429" in lowered or "rate limit" in lowered:
        return {"failure_stage": "model", "failure_category": "provider_rate_limit", "retryable": True}
    if any(term in lowered for term in ("timed out", "timeout", "deadline exceeded")):
        return {"failure_stage": "model", "failure_category": "network_timeout", "retryable": True}
    if any(term in lowered for term in ("connection error", "connection reset", "connection refused", "apiconnectionerror")):
        return {"failure_stage": "model", "failure_category": "network_connection", "retryable": True}
    if any(term in lowered for term in ("query checker rejected", "sqlcontract", "count_unit_mismatch", "metric_projection_mismatch")):
        return {"failure_stage": "contract_validation", "failure_category": "semantic_contract", "retryable": False}
    if any(term in lowered for term in ("no such table", "no such column", "unknown_table", "unknown_column")):
        return {"failure_stage": "schema_resolution", "failure_category": "schema_mismatch", "retryable": False}
    if any(term in lowered for term in ("syntax error", "sql execution", "database")):
        return {"failure_stage": "sql_execution", "failure_category": "sql_error", "retryable": False}
    if "never produced a successfully executed query" in lowered:
        return {"failure_stage": "sql_generation", "failure_category": "no_valid_candidate", "retryable": False}
    return {"failure_stage": "unknown", "failure_category": "unclassified", "retryable": False}


def _invoke_model_with_retry(
    llm_with_tools: Any,
    messages: list[Any],
    *,
    deadline: float | None,
    retry_counter: list[int] | None = None,
) -> Any:
    """도구가 연결된 모델을 호출하고 일시적 공급자·네트워크 오류만 재시도한다.

    지수 백오프와 임의 지연을 적용하며 재시도 한도 또는 전체 마감 시각을 넘으면 예외를 다시 던진다.
    전달된 카운터가 있으면 실제 재시도 횟수를 누적한다.
    """

    attempt = 0
    while True:
        try:
            return llm_with_tools.invoke(messages)
        except Exception as exc:  # noqa: BLE001 - re-raised below unless retryable
            classification = classify_model_error(exc)
            if not classification.retryable or attempt >= FAST_SQL_RATE_LIMIT_RETRIES:
                raise
            backoff = FAST_SQL_RATE_LIMIT_BACKOFF_SECONDS * (2 ** attempt)
            backoff += random.uniform(0, FAST_SQL_RATE_LIMIT_BACKOFF_SECONDS)
            if deadline is not None and perf_counter() + backoff >= deadline:
                raise
            sleep(backoff)
            attempt += 1
            if retry_counter is not None:
                retry_counter[0] += 1


@dataclass(frozen=True)
class FastSqlResult:
    """선택된 SQL·컬럼·원시 행·답변과 에이전트 실행 통계를 담는다.

    스키마 후보·실행 SQL 목록·도구 로그·결과 제한·후보 점수도 후속 응답과 관찰을 위해 보존한다.
    """

    answer: str
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    elapsed_ms: int
    tables: list[str]
    model_calls: int = 0
    cached_tables: list[str] = field(default_factory=list)
    retrieved_tables: list[str] = field(default_factory=list)
    schema_fingerprint: str = ""
    memory_eligible: bool = False
    result_truncated: bool = False
    returned_row_count: int = 0
    tool_calls: list[str] = field(default_factory=list)
    executed_queries: list[dict[str, Any]] = field(default_factory=list)
    complexity: str = "simple"
    selected_candidate_index: int = 0
    candidate_scores: list[dict[str, Any]] = field(default_factory=list)
    model_retries: int = 0


def try_fast_sql_answer(
    question: str,
    *,
    confirmed_context: ConfirmedAnalysisContext | None = None,
    cached_context: dict[str, Any] | None = None,
) -> FastSqlResult | None:
    """질문과 확정 계획으로 SQL 도구 호출 루프를 구성하고 검증된 실행 결과를 선택한다.

    관련 스키마·관계·이전 사례를 먼저 준비하고 복잡도에 따라 추론 옵션과 대안 후보 생성을 조절한다.
    성공 SQL이 없으면 오류를 발생시키며, 성공하면 원시 결과·답변·호출 통계를 FastSqlResult로 반환한다.
    """

    provider, base_url, api_key, model, _timeout = resolve_agent_llm_settings()
    kwargs: dict[str, Any] = {
        "model": model,
        "timeout": (5.0, FAST_SQL_TIMEOUT_SECONDS),
        "max_retries": 0,
        "max_completion_tokens": FAST_SQL_MAX_TOKENS,
    }
    if not model.startswith("gpt-5"):
        kwargs["temperature"] = 0
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key

    started = perf_counter()
    execution_request = confirmed_context.execution_request() if confirmed_context else question
    retrieval_question = execution_request
    validation_request = (
        confirmed_context.semantic_validation_text() if confirmed_context else question
    )
    temporal_context = confirmed_context.temporal_context if confirmed_context else None
    confirmed_plan = confirmed_context.confirmed_plan if confirmed_context else None
    complexity = classify_query_complexity(question, confirmed_plan)
    if model.startswith("gpt-5"):
        kwargs["reasoning_effort"] = _reasoning_effort_for_complexity(complexity, model=model)
    llm = ChatOpenAI(**kwargs)
    catalog_context = str(list_tables.invoke({}))
    cached_table_names = list(
        dict.fromkeys(
            str(table).strip()
            for table in (cached_context or {}).get("schema_tables", [])
            if str(table).strip()
        )
    )
    retrieval = retrieve_relevant_schema(
        retrieval_question,
        cached_tables=cached_table_names,
    )
    retrieved_table_names = list(retrieval.table_names)
    retrieved_schema_context = ""
    if retrieved_table_names:
        retrieved_schema_context = str(
            get_table_schema.invoke(
                {
                    "table_names": ",".join(retrieved_table_names),
                    "question": retrieval_question,
                    "compact": True,
                }
            )
        )
    relationship_context = ""
    if len(retrieved_table_names) > 1:
        selected_names = ",".join(retrieved_table_names)
        relationship_context = str(
            discover_relationships.invoke(
                {
                    "table_names": selected_names,
                    "candidate_table_names": selected_names,
                }
            )
        )
        relationship_context = _prioritize_relationship_context(
            relationship_context
        )
    similar_examples = list((cached_context or {}).get("similar_sql_examples", []))[:3]
    system_prompt = _build_react_system_prompt(
        confirmed_context,
        catalog_context=catalog_context,
        cached_schema_context=retrieved_schema_context,
        relationship_context=relationship_context,
        retrieval_context=retrieval.context,
        similar_examples=similar_examples,
    )
    messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=execution_request.strip()),
    ]

    sql_tool_state = SqlToolState(require_schema_inspection=True)
    preloaded_table_names = retrieved_table_names
    if retrieved_schema_context:
        sql_tool_state.schema_context.append(retrieved_schema_context)
        sql_tool_state.inspected_tables.update(preloaded_table_names)
    execute_query_tool, successes = make_execute_query_tool(
        validation_request,
        temporal_context=temporal_context,
        confirmed_plan=confirmed_plan,
        state=sql_tool_state,
        enforce_configured_temporal_anchor=True,
    )
    tools = [
        get_table_schema,
        get_semantic_context,
        discover_relationships,
        make_query_checker_tool(
            question=validation_request,
            temporal_context=temporal_context,
            confirmed_plan=confirmed_plan,
            state=sql_tool_state,
            enforce_configured_temporal_anchor=True,
        ),
        execute_query_tool,
    ]
    tool_log: list[str] = []
    tool_error_log: list[str] = []
    tables_seen: list[str] = list(preloaded_table_names)
    model_call_counter = [0]
    model_retry_counter = [0]
    final_response = _run_react_tool_loop(
        llm,
        tools,
        messages,
        tool_log,
        tables_seen,
        sql_tool_state=sql_tool_state,
        deadline=started + FAST_SQL_TOTAL_TIMEOUT_SECONDS,
        model_call_counter=model_call_counter,
        tool_error_log=tool_error_log,
        model_retry_counter=model_retry_counter,
    )

    deadline = started + FAST_SQL_TOTAL_TIMEOUT_SECONDS
    if (
        complexity == "complex"
        and FAST_SQL_COMPLEX_CANDIDATES > 1
        and len(successes) == 1
        and perf_counter() + FAST_SQL_MIN_ALTERNATIVE_SECONDS < deadline
        and not getattr(final_response, "tool_calls", None)
    ):
        messages.extend(
            [
                final_response,
                HumanMessage(
                    content=(
                        "검증을 위해 기존 SQL을 그대로 복사하지 말고 독립적인 대안 SQL 후보 하나를 "
                        "작성하세요. 동일한 확정 계획을 모두 충족해야 하며 query_checker와 "
                        "execute_query를 거친 뒤 결과를 간단히 요약하세요."
                    )
                ),
            ]
        )
        final_response = _run_react_tool_loop(
            llm,
            tools,
            messages,
            tool_log,
            tables_seen,
            max_turns=max(3, FAST_SQL_REACT_MAX_TURNS // 2),
            sql_tool_state=sql_tool_state,
            deadline=deadline,
            model_call_counter=model_call_counter,
            tool_error_log=tool_error_log,
            model_retry_counter=model_retry_counter,
        )

    if not successes:
        error_detail = "; ".join(tool_error_log[-3:]) or "no explicit tool error"
        raise RuntimeError(
            "react SQL agent never produced a successfully executed query; "
            f"last tool errors: {error_detail}; tool calls: {tool_log}"
        )
    selected_index, candidate_scores = _select_best_success(
        successes,
        confirmed_plan=confirmed_plan,
        schema_context="\n\n".join(sql_tool_state.schema_context),
        temporal_context=temporal_context,
    )
    sql, columns, rows = successes[selected_index]
    final_answer = _response_text(final_response) if selected_index == len(successes) - 1 else ""
    if not final_answer:
        final_answer = _format_generic_sql_rows(columns, rows)
    final_answer = _compact_answer_repeated_in_rows(final_answer, columns, rows)
    elapsed_ms = round((perf_counter() - started) * 1000)
    return FastSqlResult(
        answer=final_answer,
        sql=sql,
        columns=columns,
        rows=rows,
        elapsed_ms=elapsed_ms,
        tables=tables_seen,
        model_calls=model_call_counter[0],
        cached_tables=cached_table_names,
        retrieved_tables=retrieved_table_names,
        schema_fingerprint=retrieval.schema_fingerprint,
        memory_eligible=_memory_eligible(successes),
        result_truncated=sql_tool_state.last_result_truncated,
        returned_row_count=sql_tool_state.last_returned_row_count,
        tool_calls=tool_log,
        executed_queries=[
            {"sql": executed_sql, "columns": executed_columns, "rows": executed_rows}
            for executed_sql, executed_columns, executed_rows in successes
        ],
        complexity=complexity,
        selected_candidate_index=selected_index,
        candidate_scores=candidate_scores,
        model_retries=model_retry_counter[0],
    )


def classify_query_complexity(question: str, confirmed_plan: Any | None = None) -> str:
    """계획의 다중 지표·비율·비교·그룹·후속 참조·필터 수와 질문의 특정 표현을 살핀다.

    조건 중 하나라도 해당하면 complex, 나머지는 simple을 반환해 추론 강도와 후보 생성에 사용한다.
    """

    plan = (
        confirmed_plan.model_dump(mode="json")
        if hasattr(confirmed_plan, "model_dump")
        else confirmed_plan if isinstance(confirmed_plan, dict) else {}
    )
    metrics = [item for item in plan.get("metrics", []) if isinstance(item, dict)]
    if isinstance(plan.get("metric"), dict):
        metrics = [plan["metric"], *metrics]
    structural_signals = (
        len(metrics) > 1,
        any(metric.get("kind") == "ratio" for metric in metrics),
        bool(plan.get("comparison")),
        len(plan.get("group_by", [])) > 1,
        bool(plan.get("context_reference")),
        len(plan.get("filters", [])) > 2,
    )
    text = question.casefold()
    lexical_signals = (
        "비율", "율", "ratio", "percentage", "비교", "대비", "가장", "순위",
        "상위", "하위", "직접", "연결된", "각각", "동시에", "교집합",
    )
    return "complex" if any(structural_signals) or any(term in text for term in lexical_signals) else "simple"


def _reasoning_effort_for_complexity(complexity: str, *, model: str = "") -> str:
    """요청 복잡도와 모델명에 맞는 기본 추론 강도를 선택한다.

    복잡도별 환경 변수가 있으면 기본값보다 우선해 적용한다.
    """

    env_name = "AGENT_COMPLEX_REASONING_EFFORT" if complexity == "complex" else "AGENT_REASONING_EFFORT"
    simple_default = "none" if model.startswith("gpt-5.6") else "minimal"
    default = "medium" if complexity == "complex" else simple_default
    return os.environ.get(env_name, default).strip() or default


def _select_best_success(
    successes: list[tuple[str, list[str], list[dict[str, Any]]]],
    *,
    confirmed_plan: Any | None,
    schema_context: str,
    temporal_context: Any | None,
) -> tuple[int, list[dict[str, Any]]]:
    """실행에 성공한 후보를 계획 계약·결과 모양·비어 있지 않은 행·실행 계획 비용으로 평가한다.

    확정 계획이 있으면 최고 점수의 인덱스와 전체 점수 목록을 반환한다.
    확정 계획이 없으면 여러 조회가 보완적일 수 있어 기존처럼 마지막 결과를 선택한다.
    """

    scored: list[dict[str, Any]] = []
    for index, (sql, columns, rows) in enumerate(successes):
        score = 0.0
        reasons: list[str] = []
        try:
            validate_sql_contract(
                confirmed_plan,
                sql,
                schema_context=schema_context,
                temporal_context=temporal_context,
            )
            score += 100.0
            reasons.append("contract_pass")
        except (SqlContractViolation, ValueError) as exc:
            reasons.append(f"contract_fail:{exc}")
        score += min(len(columns), 12) * 2.0
        if rows:
            score += 3.0
            reasons.append("non_empty")
        try:
            details = explain_query_plan(sql)
        except Exception as exc:  # execution already succeeded; EXPLAIN is advisory
            details = []
            reasons.append(f"explain_unavailable:{exc}")
        full_scans = sum(
            "SCAN " in detail.upper() and "USING INDEX" not in detail.upper()
            and "USING COVERING INDEX" not in detail.upper()
            for detail in details
        )
        temp_sorts = sum("USE TEMP B-TREE" in detail.upper() for detail in details)
        score -= full_scans * 0.5 + temp_sorts
        if full_scans or temp_sorts:
            reasons.append(f"plan_penalty:scans={full_scans},temp_sorts={temp_sorts}")
        scored.append(
            {
                "index": index,
                "score": round(score, 3),
                "reasons": reasons,
                "sql": sql,
            }
        )
    # Without a confirmed plan, several executions may be complementary parts of
    # one answer rather than competing candidates; preserve historical last-result
    # behavior in that case.
    selected = (
        len(scored) - 1
        if confirmed_plan is None
        else max(range(len(scored)), key=lambda index: (scored[index]["score"], index))
    )
    return selected, scored


def _compact_answer_repeated_in_rows(
    answer: str,
    columns: list[str],
    rows: list[dict[str, Any]],
) -> str:
    """답변 본문이 결과 표의 항목을 길게 반복할 때 핵심 문장만 남긴다.

    단일 분류별 건수 결과는 가능하면 행에서 계산한 요약으로 바꾸고 상세는 결과 표로 안내한다.
    """

    grouped_summary = _summarize_grouped_count_rows(columns, rows)
    if grouped_summary and (
        "SQL을 실행했고" in answer
        or "행을 조회했습니다" in answer
        or "| ---" in answer
        or "대안 SQL" in answer
        or "두 쿼리" in answer
        or "일관되게 반환" in answer
    ):
        return grouped_summary

    if len(rows) < 8 or len(answer) < 200:
        return answer
    candidate_values: list[str] = []
    for column in columns:
        values = list(dict.fromkeys(
            str(row.get(column)).strip()
            for row in rows
            if row.get(column) not in (None, "") and not isinstance(row.get(column), (int, float))
        ))
        if len(values) >= min(5, max(2, len(rows) // 2)):
            candidate_values.extend(value for value in values if len(value) >= 2)
    positions = sorted(
        position
        for value in candidate_values
        if (position := answer.find(value)) >= 0
    )
    if len(positions) < 5:
        return answer
    first = positions[0]
    cut = max(
        answer.rfind("\n", 0, first),
        answer.rfind(" - ", 0, first),
        answer.rfind(":", 0, first),
    )
    if cut < 40:
        return answer
    summary = answer[:cut].rstrip(" \n:-")
    return summary + ".\n상세 항목과 수량은 아래 결과 표에서 확인할 수 있습니다."


def _summarize_grouped_count_rows(
    columns: list[str],
    rows: list[dict[str, Any]],
) -> str | None:
    """하나의 분류 컬럼과 하나의 count 컬럼으로 된 결과에서 항목 종류 수와 건수 합계를 계산한다.

    두 개 이상인 항목의 일부 사례를 덧붙이며 구조나 수치가 조건에 맞지 않으면 None을 반환한다.
    """

    if len(rows) < 2 or len(columns) < 2:
        return None
    count_columns = [column for column in columns if "count" in column.casefold()]
    if len(count_columns) != 1:
        return None
    count_column = count_columns[0]
    dimension_columns = [column for column in columns if column != count_column]
    if len(dimension_columns) != 1:
        return None
    dimension_column = dimension_columns[0]
    pairs: list[tuple[str, int]] = []
    for row in rows:
        label = row.get(dimension_column)
        raw_count = row.get(count_column)
        if label in (None, "") or isinstance(raw_count, bool):
            return None
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            return None
        if count < 0 or float(raw_count) != count:
            return None
        pairs.append((str(label), count))

    dimension_key = dimension_column.casefold()
    dimension_label = (
        "상품명"
        if "product" in dimension_key and "name" in dimension_key
        else "이름" if "name" in dimension_key else dimension_column.replace("_", " ")
    )
    count_key = count_column.casefold()
    unit = (
        "물품"
        if "item" in count_key
        or (count_key == "count" and "product" in dimension_key)
        else "주문" if "order" in count_key
        else "고객" if "customer" in count_key
        else "항목"
    )
    total = sum(count for _, count in pairs)
    repeated = sorted(
        ((label, count) for label, count in pairs if count > 1),
        key=lambda item: -item[1],
    )[:3]
    summary = (
        f"조회된 {len(rows)}행은 서로 다른 {dimension_label} {len(rows)}종이며, "
        f"{unit} 수 합계는 {total}개입니다."
    )
    if repeated:
        examples = ", ".join(f"{label} {count}개" for label, count in repeated)
        summary += f" {examples}처럼 같은 {dimension_label}이 반복됩니다."
    return summary


def _run_react_tool_loop(
    llm: Any,
    tools: list[Any],
    messages: list[Any],
    tool_log: list[str],
    tables_seen: list[str],
    *,
    max_turns: int = FAST_SQL_REACT_MAX_TURNS,
    sql_tool_state: SqlToolState | None = None,
    deadline: float | None = None,
    model_call_counter: list[int] | None = None,
    tool_error_log: list[str] | None = None,
    model_retry_counter: list[int] | None = None,
) -> Any:
    """LLM이 반환한 도구 호출을 실행하고 결과·오류를 대화에 추가하며 다음 응답을 요청한다.

    messages·도구 로그·확인한 테이블·공유 SQL 상태와 호출 카운터를 직접 갱신한다.
    도구 호출 종료, 반복 한도 또는 마감 조건에서 마지막 모델 응답을 반환한다.
    """

    tool_by_name = {getattr(tool_obj, "name", None): tool_obj for tool_obj in tools}
    llm_with_tools = llm.bind_tools(tools)
    if model_call_counter is not None:
        model_call_counter[0] += 1
    response = _invoke_model_with_retry(
        llm_with_tools,
        messages,
        deadline=deadline,
        retry_counter=model_retry_counter,
    )
    turns = 0
    while getattr(response, "tool_calls", None) and turns < max_turns:
        messages.append(response)
        for call in response.tool_calls:
            name = call["name"]
            args = call.get("args") or {}
            tool_obj = tool_by_name.get(name)
            if tool_obj is None:
                result = f"Unknown tool: {name}"
            else:
                try:
                    result = str(tool_obj.invoke(args))
                except Exception as exc:
                    result = f"Tool error: {exc}"
            tool_log.append(f"{name}({args})")
            if tool_error_log is not None and result.lower().startswith(
                ("error:", "tool error:")
            ):
                sql_tail = normalize_sql(str(args.get("sql", "")))[-500:]
                tool_error_log.append(
                    f"{name} SQL tail: {sql_tail} => {result[:500]}"
                )
            if name == "get_table_schema":
                if sql_tool_state is not None:
                    sql_tool_state.schema_context.append(result)
                for table in str(args.get("table_names", "")).split(","):
                    table = table.strip()
                    if table and table not in tables_seen:
                        tables_seen.append(table)
                    if table and sql_tool_state is not None:
                        sql_tool_state.inspected_tables.add(table)
            messages.append(ToolMessage(content=result, tool_call_id=call["id"]))
        if deadline is not None and perf_counter() >= deadline:
            break
        if model_call_counter is not None:
            model_call_counter[0] += 1
        response = _invoke_model_with_retry(
            llm_with_tools,
            messages,
            deadline=deadline,
            retry_counter=model_retry_counter,
        )
        turns += 1
    return response


def _response_text(response: Any) -> str:
    """모델의 최종 응답에서 문자열 또는 텍스트 블록만 모아 설명문을 반환한다.

    아직 도구 호출이 남았거나 사용할 텍스트가 없으면 빈 문자열을 반환한다.
    """

    if response is None or getattr(response, "tool_calls", None):
        return ""
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            str(item.get("text", "")).strip()
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part)
    return ""


def _memory_eligible(
    successes: list[tuple[str, list[str], list[dict[str, Any]]]],
) -> bool:
    """마지막 성공 조회에 컬럼과 행이 모두 있는지 확인한다.

    향후 사례로 활용할 근거가 있는 실행인지 표시하며 실제 저장은 수행하지 않는다.
    """

    if not successes:
        return False
    _sql, columns, rows = successes[-1]
    return bool(columns and rows)


def _build_react_system_prompt(
    confirmed_context: ConfirmedAnalysisContext | dict[str, Any] | None,
    *,
    catalog_context: str = "",
    cached_schema_context: str = "",
    relationship_context: str = "",
    retrieval_context: str = "",
    similar_examples: list[dict[str, Any]] | None = None,
) -> str:
    """확정 계획·테이블 목록·검색 스키마·관계·이전 SQL 사례를 실행 지침과 결합한다.

    LLM이 따라야 할 조회 순서, 검증 도구 사용, 상대 기간 및 답변 규칙을 시스템 프롬프트로 반환한다.
    """

    plan_block = ""
    if confirmed_context:
        import json as _json

        context_payload = (
            confirmed_context.model_dump(mode="json")
            if isinstance(confirmed_context, ConfirmedAnalysisContext)
            else confirmed_context
        )

        plan_block = (
            "\nCONFIRMED ANALYSIS PLAN (authoritative for WHAT the user wants):\n"
            + _json.dumps(context_payload, ensure_ascii=False, indent=2)
            + "\nWhen this confirmed plan is present, it is authoritative for every user-editable "
            "analytical meaning: date range, target/event conditions, metric and count unit, grouping, "
            "comparison, filters, sorting, and limit. The original natural-language question is supporting "
            "conversation context only. Never override a confirmed field because the original question used "
            "a different value. Runtime schema remains authoritative only for physical tables, columns, joins, "
            "and executable SQL construction.\n"
            "When confirmed_plan.context_reference.scope_id is present, the attached previous-results JSON "
            "contains matching context_id values. Use only the matching prior result as inherited result scope; "
            "other history entries are alternatives, not cumulative filters. Explicit current-turn fields still "
            "override that prior scope.\n"
        )
    examples_block = (
        json.dumps(similar_examples, ensure_ascii=False, indent=2)
        if similar_examples
        else "(none)"
    )
    return f"""You are an agent designed to interact with an arbitrary read-only SQLite database.
Given an input question, work out which tables you need, write a syntactically correct SQLite
query, check it, run it, and answer using the result. Unless the user asks for a specific number
of rows, do not add an arbitrary LIMIT.

The current table catalog is already loaded below. Do not spend a tool call listing tables.
Call get_table_schema only for a table whose full schema is not already present in the preloaded
schema block. The live schema returned below or by that tool is authoritative. Semantic metadata from
schema_summary.md is advisory business context: use it when available, prefer suitable analysis
tables it describes, but never treat it as proof that a runtime table or column exists. Use
get_semantic_context when more business context is needed. Derive every table, column,
relationship, filter, aggregation, and business meaning from the current question and tool
results. Do not assume a particular domain or silently add a period, entity, event, metric,
denominator, threshold, or row limit.

Current table catalog (programmatically loaded; no model tool call was used):
{catalog_context}

{semantic_execution_context() or "No additional schema-adjacent execution semantics are configured."}

Question-time schema retrieval:
{retrieval_context or "(not available)"}

Preloaded live schemas selected for this question (reuse before calling tools):
{cached_schema_context or "(none)"}

Relationships found inside the selected seed set (reuse before calling a tool):
{relationship_context or "(none)"}

Verified similar question-SQL examples (examples only; adapt to the live schema and never execute
them blindly):
{examples_block}

When analysis-oriented tables are discovered, inspect suitable analysis_* candidates before
raw event_*/object_* source tables because flattened tables usually expose stable business IDs.
Do not stop after inspecting a table that lacks identifiers or attributes needed by the question;
inspect additional candidates instead. If the selected table lacks requested entity details,
call discover_relationships to find identifier-based joins, inspect both candidate schemas, and
only then write SQL. Every physical table referenced by SQL must have been inspected with
get_table_schema. Relationship candidates are heuristic, so confirm their columns and sample
values before joining.

The retrieved schemas are a high-recall seed set, not a hard boundary. If they do not expose a
requested entity, attribute, filter value, or supported join path, call discover_relationships
and inspect only the missing bridge/target schemas. Do not preload unrelated relationship tables.

Do not choose a raw table merely because its name resembles the user's wording. Match the
requested counting unit to a stable identifier in the inspected schema. A generic event ID is
not an order, item, customer, or other business-entity ID. If an inspected analysis-oriented
table directly contains the requested condition, temporal column, and business identifier,
prefer it over a raw table that lacks that identifier.

Preserve relationship meaning exactly. A request for entities directly linked to an event must
use an inspected direct event-object or equivalent association and, when present, its type or
qualifier. When those events can be shared by several parent records and the question selects a
specific parent set, intersect event-linked entities with membership in that selected parent set;
also intersect the direct event rows by parent identifier with the exact period-qualified population
used in the numerator/selection, not merely with the selected customer's broader event history. Do
not leak entities belonging to another period or parent attached to the same event. Conversely, when
the user asks for every entity contained in affected parent records, use the parent-child scope.
Before filtering on a qualifier, type, or category value drawn from a linking/association table
(for example a table that only relates one entity to another) that has not yet been inspected with
get_table_schema, inspect that exact table first so the value is grounded in its data profile.
query_checker rejects a categorical literal that is not grounded in the question or in an inspected
table's data profile; guessing a qualifier value from a related table's schema wastes a turn on that
rejection.

When the question asks for a name or label (for example a request for an item name, product name, or
any "name"/"label"), verify from the inspected schema or data profile that the selected column
actually stores a human-readable value, not an internal identifier. If the directly-linked entity
only exposes an identifier but a related entity reachable via an inspected relationship exposes the
descriptive name, select that related name instead, and never alias an identifier column as a name.
When a confirmed plan is present, its target_entity, requested_attributes, result_grain,
relationship_scope, and excluded_attributes form the result contract. Select only attributes needed
to satisfy that contract and avoid history/measure columns that the plan excludes.

Use the schema-adjacent timeline_anchor when configured and verified in the live schema. It is the
shared endpoint even when the population being measured lives in another table. Otherwise use the
data-derived temporal ranges returned by list_tables and the most relevant unfiltered timeline.
When counting entities created during a period, use configured lifecycle creation semantics rather
than any lifecycle event that happened to occur in the window. Apply requested category/status
filters only after the population and time window are resolved. In SQLite, express an inclusive N-day
window with date(anchor, '-(N-1) days') through date()/datetime(); never subtract seconds from
a timestamp string and never use INTERVAL syntax. Never ask the user for today's date or the
machine current date for a relative window: the database maximum is the endpoint. For every
relative window, create a filter-free anchor CTE shaped like
`WITH data_anchor AS (SELECT MAX(date_column) AS anchor_at FROM relevant_table)`, join that CTE
into the outer query, and apply category/status filters only in the outer query. For an inclusive
N-day period, the lower bound is date(anchor_at, '-(N-1) days') and the upper bound is date(anchor_at).
For timestamp-valued columns, either use
`date(time_column) BETWEEN date(anchor_at, '-(N-1) days') AND date(anchor_at)` or the equivalent
half-open form `time_column >= date(anchor_at, '-(N-1) days') AND time_column < date(anchor_at,
'+1 day')`, or compare to the exact timestamp with `time_column <= anchor_at`. Never use
`time_column <= date(anchor_at)` because that drops events later on the anchor date.

For counts, inspect identifier columns and state the counted unit. Do not COUNT(*) over a
relationship-expanded table when the question asks how many affected business records there
are. Use COUNT(DISTINCT stable_business_id). If the unit is genuinely ambiguous, return both
the matching occurrence count and distinct affected-record count with explicit labels.

When the question asks for a rate, ratio, percentage, or share, compute it explicitly in SQL as
(matching subset count) / (relevant population count) using the same population definition as the
rest of the question. Never substitute the raw numerator count for the requested rate, and never
sort or rank by that numerator count when the question asks for the highest or lowest rate -- rank
by the computed rate itself. When the question asks for the single highest or lowest by such a
value, return exactly that many rows (for example one row for "the highest"), not an arbitrary
top-N list. When a question asks for several distinct metrics together (for example a total, a
subset count, and a rate derived from them), every requested metric must appear as its own column
in the final result -- do not stop once only one of the requested metrics has been computed.

For a follow-up asking for details of a previously affected set, preserve the selected prior set
and join only to obtain requested identifiers or attributes. Do not introduce a different event,
status, parent scope, or exclusion unless the current question or confirmed plan requests it.

{RELATIVE_TIME_POLICY}

You MUST call query_checker on your SQL before calling execute_query. query_checker is a local,
deterministic safety check and does not call another model. If execute_query returns an error,
rewrite the query based on the error message and try again.

Do not write INSERT, UPDATE, DELETE, DROP, ALTER, or any other DML/DDL statement -- only
SELECT/WITH queries are allowed, and execute_query will reject anything else.

{plan_block}
After all necessary execute_query calls succeed, produce a direct final answer that synthesizes
all relevant query results. Do not assume the last query alone answers a multi-part question.
State the applied scope and key finding compactly; structured rows are rendered separately, so do
not repeat a long result as another full prose or Markdown table. Report only values directly
returned by executed SQL, and never claim a requested column is unavailable when it is present.
If execute_query reports truncation, disclose that the rows are partial. Do not invent or mentally sum a grand total from
grouped rows; if a grand total is necessary, obtain it in SQL first. Keep the distinction between
the count of affected business records, distinct affected objects, and product names explicit.
"""


def _prioritize_relationship_context(relationship_context: str) -> str:
    """관계 탐색 결과에서 값 중첩이 확인된 직접 이벤트 연결을 앞쪽에 배치한다.

    헤더는 보존하고 관계 설명 줄만 우선순위로 정렬해 제한된 문맥에서 중요한 경로가 먼저 보이게 한다.
    """

    lines = relationship_context.splitlines()
    if len(lines) <= 1:
        return relationship_context
    header = [line for line in lines if not line.lstrip().startswith("-")]
    relationships = [line for line in lines if line.lstrip().startswith("-")]

    def priority(line: str) -> tuple[int, str]:
        """관계 설명 한 줄의 정렬 키를 계산한다.

        값 중첩이 있는 event-object 연결, event 식별자 연결, 기타 중첩, 나머지 순으로 우선한다.
        """

        lowered = line.lower()
        has_overlap = "value overlap=yes" in lowered
        is_event = "normalized identifier=event_id" in lowered
        is_event_object = ".event_id ->" in lowered and ".ocel_event_id" in lowered
        if has_overlap and is_event_object:
            return 0, lowered
        if has_overlap and is_event:
            return 1, lowered
        if has_overlap:
            return 2, lowered
        return 3, lowered

    return "\n".join([*header, *sorted(relationships, key=priority)])
