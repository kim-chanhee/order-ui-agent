"""LLM이 호출할 SQL 검사·실행 도구와 두 도구가 공유할 상태를 만든다.

query_checker는 추가 LLM 호출 없이 읽기 전용·계획·기간·업무 의미를 검사한다.
execute_query는 검사에 성공한 SQL 또는 등록된 교정 SQL만 실행할 수 있다.
실행 전에 필요한 테이블의 스키마 확인 여부를 검사하고 의미 검증을 다시 수행한다.
DB 결과는 결과 계약 검사까지 통과해야 성공 목록에 기록된다.
도구는 LLM에 문자열을 반환하고, 호출자는 별도의 성공 목록에서 원시 컬럼·행을 얻는다.
SqlToolState는 검사 이력·교정 결과·확인한 스키마·결과 제한 정보를 한 실행 안에서 공유한다.
두 도구의 공통 SQL 검증 순서는 _validate_execution_sql에서 관리한다.
교정 매핑은 기간 검증 중 날짜 상한이 정리된 SQL을 실행할 때도 필요하다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import tool

from app.execution.semantic_aliases import alias_grounding_context
from app.execution.result_contract import ResultContractViolation, validate_result_contract
from app.execution.sql_builder import MAX_RESULT_ROWS, _format_generic_sql_rows, _run_fallback_sql
from app.execution.sql_safety import validate_read_only_sql
from app.execution.temporal_policy import validate_relative_time_sql
from app.execution.analysis_semantics import validate_configured_semantics_sql
from app.execution.sql_contract import (
    SqlContractViolation,
    extract_filter_literals,
    extract_physical_tables,
    validate_sql_contract,
)


_SQL_IDENTIFIER = r'(?:[A-Za-z_][A-Za-z0-9_]*|"(?:""|[^"])+"|`(?:``|[^`])+`|\[[^\]]+\])'


@dataclass
class SqlToolState:
    """한 에이전트 실행의 검사 성공 SQL·교정 매핑·확인된 테이블·스키마를 공유한다.

    실행 도구는 이 상태로 사전 검사와 스키마 확인 여부를 판단하고 결과 제한 정보도 기록한다.
    """

    checked_queries: set[str] = field(default_factory=set)
    checked_rewrites: dict[str, str] = field(default_factory=dict)
    inspected_tables: set[str] = field(default_factory=set)
    schema_context: list[str] = field(default_factory=list)
    require_schema_inspection: bool = False
    last_result_truncated: bool = False
    last_returned_row_count: int = 0


def normalize_sql(sql: str) -> str:
    """인용된 값을 보존하면서 SQL의 공백과 문장 끝 세미콜론을 정리한다.

    검사한 SQL과 실행 요청 SQL을 비교할 공통 키를 만드는 용도다.
    """

    normalized = sql.strip()
    while normalized.endswith(";"):
        normalized = normalized[:-1].rstrip()
    output: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(normalized):
        character = normalized[index]
        if quote is not None:
            output.append(character)
            if quote == "]" and character == "]":
                quote = None
            elif character == quote:
                if index + 1 < len(normalized) and normalized[index + 1] == quote:
                    output.append(normalized[index + 1])
                    index += 1
                else:
                    quote = None
            index += 1
            continue
        if character in {"'", '"', "`"}:
            quote = character
            output.append(character)
        elif character == "[":
            quote = "]"
            output.append(character)
        elif character.isspace():
            if output and output[-1] != " ":
                output.append(" ")
        else:
            output.append(character)
        index += 1
    return "".join(output).strip()


def make_query_checker_tool(
    *,
    question: str = "",
    temporal_context: Any | None = None,
    confirmed_plan: Any | None = None,
    state: SqlToolState | None = None,
    enforce_configured_temporal_anchor: bool = False,
) -> Any:
    """질문·계획·기간 문맥과 공유 상태를 캡처한 query_checker 도구를 생성한다.

    추가 모델 호출 없이 코드로 검증하고, 기간 상한 교정 결과와 검사 이력을 등록한다.
    """

    tool_state = state if state is not None else SqlToolState()

    @tool
    def query_checker(sql: str) -> str:
        """Double check a SQLite SELECT/WITH query for common mistakes before executing it.

        Always call this on your query before calling execute_query. Returns
        the original query if it looks correct, or a corrected query otherwise.
        """

        # 근거 없는 필터와 읽기 전용·계획·기간·업무 의미 위반을 코드로 검사한다.
        # 성공하면 정규화 키와 교정 SQL을 공유 상태에 등록하고 SQL을 반환한다.
        # 실패하면 Error 문자열을 반환해 모델이 수정할 수 있게 한다.

        checked = sql
        ungrounded_literals = _ungrounded_followup_filter_literals(question, checked)
        if ungrounded_literals:
            values = ", ".join(repr(value) for value in ungrounded_literals)
            return (
                "Error: query checker rejected SQL: follow-up detail query introduced "
                f"unrequested categorical filter(s): {values}. Preserve the prior affected "
                "set and remove new filters unless the current user explicitly requested them."
            )
        schema_context = "\n\n".join(tool_state.schema_context)
        ungrounded_schema_literals = _ungrounded_schema_filter_literals(
            question,
            checked,
            schema_context,
        )
        if ungrounded_schema_literals:
            values = ", ".join(repr(value) for value in ungrounded_schema_literals)
            return (
                "Error: query checker rejected SQL: categorical filter value(s) are not "
                f"grounded in the user question or inspected live schema: {values}. "
                "Retrieve relevant values/schema and rewrite the query."
            )
        try:
            checked = _validate_execution_sql(
                checked,
                question=question,
                confirmed_plan=confirmed_plan,
                schema_context=schema_context,
                temporal_context=temporal_context,
                enforce_configured_temporal_anchor=enforce_configured_temporal_anchor,
            )
        except ValueError as exc:
            return f"Error: query checker rejected SQL: {exc}"
        original_key = normalize_sql(sql)
        checked_key = normalize_sql(checked)
        tool_state.checked_queries.add(checked_key)
        tool_state.checked_rewrites[original_key] = checked
        return checked

    return query_checker


_FOLLOWUP_HISTORY_MARKER = "Previous results from this thread"
_CURRENT_QUESTION_MARKER = "Current user question:"
_TEMPORAL_MODIFIER_PATTERN = re.compile(
    r"^[+-]?\d+\s+(?:day|days|week|weeks|month|months|year|years)$",
    re.IGNORECASE,
)


def _ungrounded_followup_filter_literals(question: str, sql: str) -> list[str]:
    """후속 질문 SQL의 문자열 조건 중 현재 질문·이전 질문·이전 SQL·별칭에 없는 값을 찾는다.

    날짜 이동 수식은 제외하고 새로 추가된 근거 없는 범주 필터 값 목록을 반환한다.
    """

    if _FOLLOWUP_HISTORY_MARKER not in question:
        return []
    current_block, history_block = question.split(_FOLLOWUP_HISTORY_MARKER, 1)
    current_question = current_block.removeprefix(_CURRENT_QUESTION_MARKER).strip().lower()
    grounded_text = "\n".join(
        part
        for part in (
            _grounded_followup_text(current_question, history_block),
            alias_grounding_context(current_question),
        )
        if part
    ).lower()
    try:
        candidate_values = extract_filter_literals(sql)
    except SqlContractViolation:
        candidate_values = []
    ungrounded: list[str] = []
    for raw_value in candidate_values:
        value = raw_value.replace("''", "'").strip()
        if not value or _TEMPORAL_MODIFIER_PATTERN.fullmatch(value):
            continue
        if value.lower() in grounded_text or value in ungrounded:
            continue
        ungrounded.append(value)
    return ungrounded


def _ungrounded_schema_filter_literals(
    question: str,
    sql: str,
    schema_context: str,
) -> list[str]:
    """SQL의 범주 조건 값을 질문·확인한 스키마·현재 발화의 별칭 근거와 대조한다.

    지원하는 날짜 이동 수식을 제외하고 어느 근거에도 없는 값만 반환한다.
    """

    current_question = question.split(_FOLLOWUP_HISTORY_MARKER, 1)[0]
    current_question = current_question.removeprefix(_CURRENT_QUESTION_MARKER).strip()
    grounded_text = (
        f"{question}\n{schema_context}\n"
        f"{alias_grounding_context(current_question)}"
    ).lower()
    try:
        values = extract_filter_literals(sql)
    except SqlContractViolation:
        values = []
    ungrounded: list[str] = []
    for raw_value in values:
        value = raw_value.replace("''", "'").strip()
        if not value or _TEMPORAL_MODIFIER_PATTERN.fullmatch(value):
            continue
        if value.lower() in grounded_text or value in ungrounded:
            continue
        ungrounded.append(value)
    return ungrounded


def _grounded_followup_text(current_question: str, history_block: str) -> str:
    """현재 질문과 저장 기록의 이전 질문·실행 SQL만 모아 필터 검증용 문자열을 만든다.

    이전 모델 답변과 결과 행은 새 필터를 허가하는 근거에 포함하지 않는다.
    """

    grounded_parts = [current_question.lower()]
    json_start = min(
        (index for index in (history_block.find("["), history_block.find("{")) if index >= 0),
        default=-1,
    )
    if json_start < 0:
        return "\n".join(grounded_parts)
    try:
        payload = json.loads(history_block[json_start:])
    except (json.JSONDecodeError, TypeError):
        return "\n".join(grounded_parts)
    records = payload if isinstance(payload, list) else [payload]
    for record in records:
        if not isinstance(record, dict):
            continue
        prior_question = record.get("question")
        prior_sql = record.get("sql")
        if isinstance(prior_question, str):
            grounded_parts.append(prior_question.lower())
        if isinstance(prior_sql, str):
            grounded_parts.append(prior_sql.lower())
    return "\n".join(grounded_parts)


def make_execute_query_tool(
    question: str = "",
    *,
    temporal_context: Any | None = None,
    confirmed_plan: Any | None = None,
    state: SqlToolState | None = None,
    enforce_configured_temporal_anchor: bool = False,
) -> tuple[Any, list[tuple[str, list[str], list[dict[str, Any]]]]]:
    """확정 문맥·공유 상태를 사용하는 execute_query 도구와 성공 조회 목록을 함께 만든다.

    도구는 모델에 문자열을 반환하고 호출자는 성공 목록에서 원시 SQL·컬럼·행을 얻는다.
    """

    tool_state = state if state is not None else SqlToolState()
    successes: list[tuple[str, list[str], list[dict[str, Any]]]] = []

    @tool
    def execute_query(sql: str) -> str:
        """Execute a read-only SQLite SELECT/WITH query and return the result.

        Only SELECT/WITH statements are allowed. If the query is invalid or
        SQLite raises an error, the error message is returned so it can be
        rewritten and retried.
        """

        # 검사 성공 SQL 또는 등록된 교정 SQL만 선택하고 필요한 스키마 확인 이력을 검사한다.
        # 읽기 전용·계획·기간·업무 의미를 재검증한 뒤 제한된 행 수로 실행한다.
        # 결과 계약까지 통과하면 원시 결과를 성공 목록에 기록하고 표·안내 문자열을 반환한다.

        requested_key = normalize_sql(sql)
        if requested_key in tool_state.checked_queries:
            executable_sql = sql
        elif requested_key in tool_state.checked_rewrites:
            executable_sql = tool_state.checked_rewrites[requested_key]
        else:
            return "Error: query_checker must be called successfully before execute_query."
        if tool_state.require_schema_inspection:
            referenced_tables = extract_referenced_tables(executable_sql)
            missing_tables = referenced_tables - tool_state.inspected_tables
            if missing_tables:
                missing = ", ".join(sorted(missing_tables))
                return (
                    "Error: get_table_schema must inspect every referenced table before "
                    f"execute_query. Missing: {missing}"
                )
        try:
            validated = _validate_execution_sql(
                executable_sql,
                question=question,
                confirmed_plan=confirmed_plan,
                schema_context="\n\n".join(tool_state.schema_context)[-24000:],
                temporal_context=temporal_context,
                enforce_configured_temporal_anchor=enforce_configured_temporal_anchor,
            )
        except ValueError as exc:
            return f"Error: {exc}"
        try:
            fetch_limit = MAX_RESULT_ROWS + 1 if MAX_RESULT_ROWS > 0 else 0
            columns, rows = _run_fallback_sql(validated, max_result_rows=fetch_limit)
        except Exception as exc:
            return f"Error: {exc}"
        truncated = MAX_RESULT_ROWS > 0 and len(rows) > MAX_RESULT_ROWS
        if truncated:
            rows = rows[:MAX_RESULT_ROWS]
        tool_state.last_result_truncated = truncated
        tool_state.last_returned_row_count = len(rows)
        row_dicts = [dict(row) for row in rows]
        try:
            validate_result_contract(
                confirmed_plan,
                columns=columns,
                rows=row_dicts,
            )
        except ResultContractViolation as exc:
            return (
                "Error: result contract rejected the executed SQL: "
                f"{exc}. Revise the selected entity/attributes/result grain and try once more."
            )
        successes.append((validated, columns, row_dicts))
        formatted = _format_generic_sql_rows(columns, rows)
        if not rows:
            formatted += (
                "\nValidation warning: the query executed but returned no rows. If the "
                "question implies matching data should exist, verify categorical values and "
                "join paths with the inspected schema, expand only the missing relationship "
                "table, and retry once before accepting the empty result."
            )
        if truncated:
            formatted += f"\n안전상 최대 {MAX_RESULT_ROWS}행만 반환했습니다."
        return formatted

    return execute_query, successes


def _validate_execution_sql(
    sql: str,
    *,
    question: str,
    confirmed_plan: Any | None,
    schema_context: str,
    temporal_context: Any | None,
    enforce_configured_temporal_anchor: bool,
) -> str:
    """검사 도구와 실행 도구가 동일한 순서로 SQL 실행 기준을 검증한다.

    읽기 전용 → 계획·스키마 → 기간 → 고유 건수 → 업무 의미 순으로 검사한다.
    기간 검사에서 날짜 상한이 교정될 수 있어 최종 SQL을 반환하며 위반은 호출자에게 전달한다.
    실행 도구에서도 다시 호출해 검사 이후 바뀐 실행 조건을 확인한다.
    """

    validated = validate_read_only_sql(sql)
    validated = validate_sql_contract(
        confirmed_plan,
        validated,
        schema_context=schema_context,
        temporal_context=temporal_context,
    )
    validated = validate_relative_time_sql(
        question,
        validated,
        temporal_context=temporal_context,
        enforce_configured_anchor=enforce_configured_temporal_anchor,
    )
    validated = validate_confirmed_metric_sql(confirmed_plan, validated)
    return validate_configured_semantics_sql(
        confirmed_plan, validated, temporal_context=temporal_context
    )


def validate_confirmed_metric_sql(confirmed_plan: Any | None, sql: str) -> str:
    """확정 지표가 distinct 건수일 때 안정적인 ID의 COUNT(DISTINCT ...) 사용을 확인한다.

    명시된 물리 ID가 있으면 그 필드를 요구하고 의미 이름이면 *_id 집계를 요구한다.
    계획이 없거나 검사 대상 지표가 아니면 SQL을 그대로 반환하며 위반 시 ValueError를 발생시킨다.
    AST 지표 검사에서 기대 필드를 추론하지 못한 경우에도 ID 집계 경계를 유지하므로 별도로 둔다.
    """

    if confirmed_plan is None:
        return sql
    if hasattr(confirmed_plan, "model_dump"):
        plan = confirmed_plan.model_dump(mode="json")
    elif isinstance(confirmed_plan, dict):
        plan = confirmed_plan
    else:
        raise TypeError("confirmed_plan must be a mapping or Pydantic model")
    metric = plan.get("metric") if isinstance(plan, dict) else None
    if not isinstance(metric, dict) or metric.get("kind") != "count" or metric.get("distinct") is not True:
        return sql
    field_name = str(metric.get("field") or "").strip()
    normalized = re.sub(r'[`"\[\]]', "", sql)
    physical_identifier = field_name.lower() == "id" or field_name.lower().endswith("_id")
    target = (
        re.escape(field_name)
        if physical_identifier
        else r"[A-Za-z_][A-Za-z0-9_]*_id"
    )
    distinct_count = re.compile(
        rf"\bCOUNT\s*\(\s*DISTINCT\s+(?:[A-Za-z_][A-Za-z0-9_]*\s*\.\s*)?{target}\s*\)",
        re.IGNORECASE,
    )
    if not distinct_count.search(normalized):
        required = field_name if physical_identifier else "a stable *_id"
        raise ValueError(
            f"confirmed metric requires COUNT(DISTINCT {required}) so relationship-expanded rows do not duplicate the requested unit"
        )
    return sql


_TABLE_REFERENCE_PATTERN = re.compile(
    rf"\b(?:FROM|JOIN)\s+(?P<table>{_SQL_IDENTIFIER}(?:\s*\.\s*{_SQL_IDENTIFIER})?)",
    re.IGNORECASE,
)
_CTE_NAME_PATTERN = re.compile(
    rf"(?:\bWITH\b|,)\s*(?P<name>{_SQL_IDENTIFIER})\s+AS\s*\(",
    re.IGNORECASE,
)


def extract_referenced_tables(sql: str) -> set[str]:
    """단순 테이블 별칭인 CTE 이름을 제외하고 SQL의 FROM/JOIN 테이블명을 추출한다.

    검사 이력과 대조해 실행 전 미확인 테이블을 찾기 위한 문자열 기반 보조 함수다.
    """

    try:
        return extract_physical_tables(sql)
    except SqlContractViolation:
        # Preserve useful best-effort extraction for diagnostics of malformed SQL.
        pass
    cte_names = {
        _last_identifier_part(match.group("name"))
        for match in _CTE_NAME_PATTERN.finditer(sql)
    }
    referenced = {
        _last_identifier_part(match.group("table"))
        for match in _TABLE_REFERENCE_PATTERN.finditer(sql)
    }
    return referenced - cte_names


def _last_identifier_part(identifier: str) -> str:
    """스키마 접두사 등이 붙은 SQL 식별자에서 마지막 이름 부분을 추출한다.

    인용 기호와 중복 인용 처리를 정리해 실제 테이블명 비교에 사용할 문자열을 반환한다.
    """

    value = re.split(r"\s*\.\s*", identifier.strip())[-1]
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    elif len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "`"}:
        value = value[1:-1].replace(value[0] * 2, value[0])
    return value
