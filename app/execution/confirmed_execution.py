"""공통 SQL 에이전트의 실행을 시작하고 성공·실패 결과를 표준화한다.

execute_schema_question이 질문·확정 문맥·캐시를 fast_sql_agent에 전달한다.
성공하면 SQL·컬럼·행과 실행 시간·도구 호출·후보 선택 정보를 응답 데이터로 묶는다.
실패하면 실패 단계·오류 분류·재시도 가능 여부와 사용자용 안내를 반환한다.
오류 문자열에서는 일부 API 키 패턴을 가리고 길이를 제한한다.
이 파일의 책임은 실행 호출과 결과 포장이며, SQL 생성·DB 실행은 하위 계층에 위임한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.execution.confirmed_context import ConfirmedAnalysisContext
from app.execution.fast_sql_agent import classify_failure_message, try_fast_sql_answer


FAST_PRIMARY = "fast_llm_sql"


def sanitize_fallback_error(error: str) -> str:
    """오류 문자열의 key=, Google API 키, sk- 형태를 가리고 최대 길이를 제한한다.

    사용자에게 전달할 진단 문자열을 줄이는 처리이며 모든 종류의 비밀 값을 탐지하는 것은 아니다.
    """

    text = re.sub(r"key=[^\s'\"&]+", "key=[redacted]", error)
    text = re.sub(r"AIza[\w-]+", "[redacted]", text)
    text = re.sub(r"sk-[\w-]+", "sk-[redacted]", text)
    return text[:237].rstrip() + "..." if len(text) > 240 else text


def format_agent_failure_answer(exc: Exception) -> str:
    """예외 내용을 읽어 요청 한도 초과·유효 SQL 생성 실패·기타 실행 실패를 안내한다.

    일반 오류의 상세 내용에는 일부 비밀 패턴을 가린 짧은 문자열을 사용한다.
    """

    text = str(exc)
    if "429" in text:
        return (
            "Answer: LLM API 요청 한도(429)에 걸렸습니다. "
            "잠시 후 다시 시도하거나 다른 LLM 공급자를 사용해 주세요."
        )
    if (
        "never produced a successfully executed query" in text
        and "no explicit tool error" in text
    ):
        return (
            "Answer: 요청을 실행할 SQL을 만들지 못했습니다. "
            "대상 고객·기간·항목 등 조건을 조금 더 구체적으로 지정해 주세요."
        )
    return (
        "Answer: SQL 분석 실행에 실패했습니다. "
        "잠시 후 다시 시도하거나 질문을 더 구체적으로 입력해 주세요.\n"
        f"- detail: {sanitize_fallback_error(text)}"
    )


@dataclass(frozen=True)
class ConfirmedExecutionResult:
    """공통 실행기의 답변·안내·공급자·성공 데이터와 실패 분류 정보를 담는 결과 객체다.

    모드별 서비스는 이 값을 응답 화면과 실행 기록으로 변환한다.
    """

    answer: str
    message: str
    provider: str
    fallback_used: bool
    fallback_error: str
    analysis_payload: dict[str, Any] | None
    failure_stage: str = ""
    failure_category: str = ""
    retryable: bool = False


def execute_schema_question(
    question: str,
    *,
    confirmed_context: ConfirmedAnalysisContext | None = None,
    cached_context: dict[str, Any] | None = None,
) -> ConfirmedExecutionResult:
    """질문·확정 문맥·캐시를 SQL 에이전트에 전달하고 성공·실패를 공통 결과 객체로 반환한다.

    성공 시 SQL·컬럼·행과 시간·도구 호출·후보 선택 통계를 수집한다.
    에이전트 예외는 사용자용 안내와 실패 단계·분류·재시도 가능 여부로 변환한다.
    """

    try:
        result = try_fast_sql_answer(
            question,
            confirmed_context=confirmed_context,
            cached_context=cached_context,
        )
        if result is None:
            raise RuntimeError("SQL agent produced no result")
    except Exception as exc:
        error = sanitize_fallback_error(str(exc))
        failure = classify_failure_message(error)
        return ConfirmedExecutionResult(
            answer=format_agent_failure_answer(RuntimeError(error)),
            message="스키마 기반 SQL Agent가 요청을 실행하지 못했습니다.",
            provider=FAST_PRIMARY,
            fallback_used=True,
            fallback_error=error,
            analysis_payload=None,
            **failure,
        )

    result_view = (
        confirmed_context.confirmed_plan.output.view
        if confirmed_context is not None
        else "table"
    )
    payload = {
        "sql": result.sql,
        "params": [],
        "columns": result.columns,
        "rows": result.rows,
        "metadata": {
            "execution_route": FAST_PRIMARY,
            "llm_elapsed_ms": result.elapsed_ms,
            "llm_model_calls": result.model_calls,
            "llm_retry_count": result.model_retries,
            "schema_tables": result.tables,
            "cached_schema_tables": result.cached_tables,
            "retrieved_schema_tables": result.retrieved_tables,
            "schema_fingerprint": result.schema_fingerprint,
            "validation_passed": True,
            "memory_eligible": result.memory_eligible,
            "returned_row_count": result.returned_row_count,
            "result_truncated": result.result_truncated,
            "has_more_rows": result.result_truncated,
            "schema_tool_calls": result.tool_calls,
            "executed_queries": result.executed_queries,
            "query_complexity": result.complexity,
            "selected_candidate_index": result.selected_candidate_index,
            "candidate_scores": result.candidate_scores,
            "result_view": result_view,
        },
    }
    return ConfirmedExecutionResult(
        answer=result.answer,
        message="실시간 스키마를 확인해 생성한 읽기 전용 SQL 결과입니다.",
        provider=FAST_PRIMARY,
        fallback_used=False,
        fallback_error="",
        analysis_payload=payload,
    )
