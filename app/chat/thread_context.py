"""대화(thread) 맥락 관리.

같은 대화 안에서 후속 질문("그 물품은?", "위 결과에서 상위 5개만")을
이해할 수 있게 이전 SQL 결과를 붙이고, 실행 후 메타데이터를 저장한다.

주요 기능:
    - 모드별 최근 문답을 저장해 확인 질문에 대한 후속 답변을 이해하도록 돕는다.
    - 최근 SQL 결과 최대 5건을 압축해 후속 질문에 첨부한다.
    - 마지막 SQL·참조 테이블과 유사 질문의 SQL 예시를 캐시 맥락으로 제공한다.
    - 질문과 SQL의 해시로 이전 결과를 참조할 안정적인 식별자를 만든다.
    - 결과별 행 샘플 최대 20개와 ID 컬럼별 고유 값 최대 100개를 보존한다.
    - 실행 후 마지막 질문·SQL·컬럼·테이블·실행 경로를 thread에 기록한다.

호출처:
    execution/{baseline,a2ui}/service.py  → contextual_request, agent_cache_context (SQL 실행 전)
    실행 결과 저장 경로     → remember_execution_context (실행 완료 후)
"""

from __future__ import annotations

import json
import hashlib

from app.runtime.state_store import (
    get_similar_sql_examples,
    get_thread_context,
    get_thread_results,
    update_thread_context,
)


CONTEXT_HISTORY_LIMIT = 5
CONTEXT_ROW_SAMPLE_LIMIT = 20
CONTEXT_IDENTITY_VALUE_LIMIT = 100


def contextual_request(question: str, thread_id: str | None) -> str:
    """SQL 에이전트에 보낼 질문에 이전 실행 결과를 덧붙인다.

    SQL이 기록된 최근 결과 최대 5건의 질문·답변·SQL·행 샘플을 JSON으로 첨부한다.
    이전 결과가 없으면 원본 질문만 반환한다.
    """

    records = get_thread_results(thread_id)
    successful_records = [
        record
        for record in records
        if ((record.get("normalized_spec") or {}).get("analysis_execution") or {}).get("sql")
    ]
    if not successful_records:
        return question.strip()
    history = [compact_context_record(record) for record in successful_records[-CONTEXT_HISTORY_LIMIT:]]
    return (
        "Current user question:\n"
        + question.strip()
        + "\n\nPrevious results from this thread (use only to resolve references in the current question):\n"
        + json.dumps(history, ensure_ascii=False)
    )


def agent_cache_context(thread_id: str | None, question: str = "") -> dict:
    """SQL 에이전트가 재사용할 캐시 정보를 반환한다.

    반환 키:
        last_sql             - 마지막 실행 SQL
        schema_tables        - 사용된 테이블 목록
        similar_sql_examples - 비슷한 질문의 검증된 SQL 예시 (최대 3개)
    """

    context: dict = {}
    for record in reversed(get_thread_results(thread_id)):
        normalized = record.get("normalized_spec") or {}
        execution = normalized.get("analysis_execution") or {}
        metadata = execution.get("metadata") or {}
        sql = execution.get("sql")
        tables = metadata.get("schema_tables")
        if sql and isinstance(tables, list):
            try:
                from app.execution.sql_tools import extract_referenced_tables

                referenced = sorted(extract_referenced_tables(sql))
            except Exception:
                referenced = []
            context = {
                "last_sql": sql,
                "schema_tables": referenced or [str(table) for table in tables if table],
            }
            break
    if question.strip():
        try:
            from app.execution.schema_tools import schema_fingerprint

            examples = get_similar_sql_examples(
                question,
                schema_fingerprint=schema_fingerprint(),
                limit=3,
            )
        except Exception:
            examples = []
        if examples:
            context["similar_sql_examples"] = examples
    return context


def context_record_id(record: dict) -> str:
    """질문과 SQL을 해시해 동일한 내용의 분석을 참조할 scope 식별자를 반환한다."""

    execution = ((record.get("normalized_spec") or {}).get("analysis_execution") or {})
    payload = json.dumps(
        {
            "question": str(record.get("question") or "").strip(),
            "sql": str(execution.get("sql") or "").strip(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "scope_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def compact_context_record(record: dict) -> dict:
    """이전 결과를 계획·SQL·행 샘플·ID 값 중심으로 압축해 후속 질문의 맥락으로 만든다."""

    execution = ((record.get("normalized_spec") or {}).get("analysis_execution") or {})
    metadata = execution.get("metadata") or {}
    columns = [str(column) for column in execution.get("columns") or []]
    rows = [row for row in execution.get("rows") or [] if isinstance(row, dict)]
    identity_values = {
        column: list(dict.fromkeys(
            str(row[column])
            for row in rows
            if row.get(column) not in (None, "")
        ))[:CONTEXT_IDENTITY_VALUE_LIMIT]
        for column in columns
        if column.lower() == "id" or column.lower().endswith("_id")
    }
    normalized = record.get("normalized_spec") or {}
    plan = normalized.get("analysis_plan")
    if not isinstance(plan, dict):
        confirmed = normalized.get("confirmed_context") or {}
        plan = confirmed.get("confirmed_plan") if isinstance(confirmed, dict) else None
    return {
        "context_id": context_record_id(record),
        "question": record.get("question"),
        "answer": record.get("answer"),
        "sql": execution.get("sql"),
        "analysis_plan": plan if isinstance(plan, dict) else None,
        "columns": columns,
        "rows": rows[:CONTEXT_ROW_SAMPLE_LIMIT],
        "identity_values": identity_values,
        "schema_tables": metadata.get("schema_tables") or [],
    }


def remember_execution_context(thread_id: str | None, execution_result: dict | None) -> None:
    """실행 완료 후 thread에 메타데이터만 저장한다.

    마지막 질문, SQL, 컬럼, 테이블, 실행 경로 등을 저장한다.
    실제 답변 본문은 thread_results에 별도로 저장된다.
    """

    if not thread_id or not execution_result:
        return
    normalized = execution_result.get("normalized_spec") or {}
    execution = normalized.get("analysis_execution") or {}
    metadata = execution.get("metadata") or {}
    values = {
        "last_question": normalized.get("original_question"),
        "last_columns": execution.get("columns"),
        "last_sql": execution.get("sql"),
        "schema_tables": metadata.get("schema_tables"),
        "last_execution_route": metadata.get("execution_route"),
    }
    update_thread_context(thread_id, values)


DIALOGUE_TURN_LIMIT = 6
DIALOGUE_TEXT_LIMIT = 8000


def recent_dialogue(thread_id: str | None, input_source: str) -> list[dict]:
    """같은 대화·모드에서 최근 사용자 질문과 답변·분류 정보를 읽는다."""

    context = get_thread_context(thread_id)
    turns = context.get(f"chat_dialogue_{input_source}") or []
    return turns[-DIALOGUE_TURN_LIMIT:] if isinstance(turns, list) else []


def remember_dialogue(question: str, response: dict) -> None:
    """분석 기록과 별도로 일반 대화·확인 질문·계획 안내까지 최근 문답에 저장한다."""

    thread_id = response.get("thread_id")
    input_source = response.get("input_source")
    if not thread_id or not input_source:
        return
    execution = response.get("execution_result") or {}
    normalized = execution.get("normalized_spec") or {}
    turn = {
        "question": question.strip()[:DIALOGUE_TEXT_LIMIT],
        "answer": str(response.get("answer") or "")[:DIALOGUE_TEXT_LIMIT],
        "kind": execution.get("kind"),
        "turn_decision": normalized.get("turn_decision"),
    }
    turns = [*recent_dialogue(thread_id, input_source), turn][-DIALOGUE_TURN_LIMIT:]
    update_thread_context(thread_id, {f"chat_dialogue_{input_source}": turns})
