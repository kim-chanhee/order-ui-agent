"""상대 기간의 기준 시점과 SQL 날짜 조건을 일관되게 검사한다.

확정된 기간 문맥을 우선하고, 문맥이 없을 때만 질문의 최근 N일·주·월·년 표현을 해석한다.
상대 기간은 시스템 시계 대신 필터 없는 데이터 MAX 날짜 CTE를 기준으로 삼는다.
설정된 기준 테이블·컬럼, 기준 CTE 참조, 요청 기간의 시작·종료 조건을 검사한다.
타임스탬프를 자정까지 잘라 마지막 날을 누락하는 상한은 다음 날 미만 조건으로 교정한다.
구현은 지원하는 SQL 형태를 정규식과 괄호 탐색으로 인식하며 범용 SQL 해석기는 아니다.
정상 SQL 또는 교정된 SQL을 반환하고, 정책 위반 시 ValueError를 발생시킨다.
"""

from __future__ import annotations

import re
from typing import Any


RELATIVE_TIME_POLICY = """Relative-time policy:
- When the user asks for a relative window such as recent/last/past N days, weeks,
  months, or years without an explicit end date, anchor the window to MAX() of the
  relevant date/timestamp column across the relevant dataset timeline.
- Compute that MAX() before applying the requested category, status, event, entity,
  or other subject filters. Apply those filters only to rows inside the resolved
  time window. This keeps comparisons aligned to the dataset's actual end date.
- Never anchor such a window to the machine clock, CURRENT_DATE, CURRENT_TIMESTAMP,
  or SQLite's 'now'.
- For N calendar days, include the anchor date and the preceding N-1 dates.
- For timestamp text, use either date(time_column) BETWEEN the two calendar dates,
  or time_column >= the start date with time_column < date(anchor, '+1 day'),
  or time_column <= the exact unmodified MAX timestamp. Never use
  time_column <= date(anchor), which excludes events later on the anchor date.
- Include the resolved start date and end date in the result whenever practical.
"""


_RELATIVE_WINDOW_PATTERNS = (
    re.compile(r"(?:최근|지난)\s*(?P<amount>\d+)\s*(?P<unit>일|주|주일|개월|달|년)"),
    re.compile(
        r"\b(?:recent|last|past)\s+(?P<amount>\d+)\s+"
        r"(?P<unit>day|week|month|year)s?\b",
        re.IGNORECASE,
    ),
)
_MACHINE_CLOCK_PATTERN = re.compile(
    r"\bCURRENT_(?:DATE|TIME|TIMESTAMP)\b|['\"]now['\"]",
    re.IGNORECASE,
)
_SQLITE_DATE_FUNCTION_PATTERN = re.compile(
    r"\b(?:date|datetime|julianday)\s*\(", re.IGNORECASE
)
_INTERVAL_PATTERN = re.compile(r"\bINTERVAL\b", re.IGNORECASE)
_IDENTIFIER_PART = r'(?:[A-Za-z_][A-Za-z0-9_]*|"(?:""|[^"])+"|`(?:``|[^`])+`|\[[^\]]+\])'
_QUALIFIED_IDENTIFIER = rf"{_IDENTIFIER_PART}(?:\s*\.\s*{_IDENTIFIER_PART})?"
_CTE_START_PATTERN = re.compile(
    rf"(?P<name>{_IDENTIFIER_PART})\s+AS\s*\(",
    re.IGNORECASE,
)
_ANCHOR_BODY_PATTERN = re.compile(
    rf"""^\s*SELECT\s+MAX\s*\(\s*
        (?:(?P<wrapper>date|datetime|julianday)\s*\(\s*)?
        (?P<column>{_QUALIFIED_IDENTIFIER})
        (?(wrapper)\s*\))\s*\)
        \s+(?:AS\s+)?(?P<alias>{_IDENTIFIER_PART})
        \s+FROM\s+(?P<table>{_QUALIFIED_IDENTIFIER})
        (?:\s+(?:AS\s+)?(?P<table_alias>{_IDENTIFIER_PART}))?\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def _relative_window_spec(question: str) -> tuple[int, str] | None:
    """질문에서 지원하는 최근 기간 표현을 순서대로 찾아 수량과 단위를 추출한다.

    일치하지 않으면 None을 반환해 상대 기간을 임의로 만들지 않는다.
    """

    for pattern in _RELATIVE_WINDOW_PATTERNS:
        match = pattern.search(question)
        if match:
            return int(match.group("amount")), match.group("unit").lower()
    return None


def validate_relative_time_sql(
    question: str,
    sql: str,
    *,
    temporal_context: Any | None = None,
    enforce_configured_anchor: bool = False,
) -> str:
    """확정 기간을 우선해 상대 기간이 필요한지 판단하고 SQL의 기준 CTE·기간 조건을 검사한다.

    시스템 시계·미지원 INTERVAL·잘못된 기준 테이블과 컬럼을 거부한다.
    지원하는 타임스탬프 상한은 하루 전체를 포함하도록 교정하고, 나머지 위반은 ValueError로 보고한다.
    """

    relative_required, spec = _authoritative_relative_spec(question, temporal_context)
    if not relative_required:
        return sql
    inspected_sql = _strip_sql_comments(sql)
    if _MACHINE_CLOCK_PATTERN.search(inspected_sql):
        raise ValueError(
            "relative time windows must use the relevant data maximum, not the machine clock"
        )
    if _INTERVAL_PATTERN.search(inspected_sql):
        raise ValueError("SQLite relative windows must not use unsupported INTERVAL syntax")

    anchor = _find_unfiltered_data_anchor(inspected_sql)
    if anchor is None:
        raise ValueError(
            "relative time SQL must define an unfiltered anchor CTE shaped like "
            "SELECT MAX(date_column) AS anchor_at FROM relevant_table"
        )
    if not _SQLITE_DATE_FUNCTION_PATTERN.search(inspected_sql):
        raise ValueError(
            "relative time windows must compare values through SQLite date/datetime functions"
        )
    cte_name, anchor_table, date_column, anchor_alias, outer_sql = anchor
    table_name = _unqualified_identifier(anchor_table)
    column_name = _unqualified_identifier(date_column)
    expected_anchor = _expected_anchor(temporal_context)
    if expected_anchor is None and enforce_configured_anchor:
        # Baseline requests do not carry a confirmed TemporalExecutionContext, but
        # they still have to use the dataset-wide timeline configured beside the
        # schema.  Without this fallback a model can anchor "recent 60 days" to
        # MAX() of an already-filtered subject table (for example the latest
        # failed-delivery event), silently moving the whole window backwards.
        from app.execution.analysis_semantics import timeline_anchor

        expected_anchor = timeline_anchor()
    if expected_anchor and (
        table_name.casefold() != expected_anchor[0].casefold()
        or column_name.casefold() != expected_anchor[1].casefold()
    ):
        raise ValueError(
            "relative time SQL must use the schema-configured dataset timeline anchor "
            f"{expected_anchor[0]}.{expected_anchor[1]}"
        )
    if not expected_anchor and not _contains_identifier(outer_sql, table_name):
        raise ValueError(
            "relative time SQL must query the same table used by the data MAX anchor"
        )
    if not _contains_identifier(outer_sql, cte_name):
        raise ValueError("relative time SQL must reference the data MAX anchor CTE")

    if spec:
        amount, unit = spec
        if unit in {"일", "day"}:
            preceding_days = max(amount - 1, 0)
        elif unit in {"주", "주일", "week"}:
            preceding_days = max(amount * 7 - 1, 0)
        elif unit in {"개월", "달", "month"}:
            preceding_days = None
            modifier = f"-{amount} months"
        elif unit in {"년", "year"}:
            preceding_days = None
            modifier = f"-{amount} years"
        else:
            preceding_days = None
            modifier = ""
        if preceding_days is not None:
            modifier = f"-{preceding_days} days"
        canonical_sql = _canonicalize_timestamp_upper_bound(
            inspected_sql,
            cte_name=cte_name,
            anchor_alias=anchor_alias,
            date_column=column_name,
        )
        if canonical_sql != inspected_sql:
            inspected_sql = canonical_sql
            refreshed_anchor = _find_unfiltered_data_anchor(inspected_sql)
            if refreshed_anchor is not None:
                _, _, _, _, outer_sql = refreshed_anchor
        if modifier and not _uses_anchor_window(
            outer_sql,
            cte_name=cte_name,
            anchor_alias=anchor_alias,
            date_column=None if expected_anchor else column_name,
            modifier=modifier,
        ):
            raise ValueError(
                f"relative window must use '{modifier}' from the unfiltered data MAX anchor "
                "and use one of these upper bounds: date(column) <= date(anchor), "
                "timestamp < date(anchor, '+1 day'), or timestamp <= the exact anchor"
            )
    return inspected_sql if inspected_sql != _strip_sql_comments(sql) else sql


def _expected_anchor(temporal_context: Any | None) -> tuple[str, str] | None:
    """기간 문맥에서 기준 테이블·컬럼 쌍을 추출한다.

    모델과 딕셔너리를 지원하며 두 값 중 하나라도 없으면 None을 반환한다.
    """

    if temporal_context is None:
        return None
    data = temporal_context.model_dump(mode="json") if hasattr(temporal_context, "model_dump") else temporal_context
    if not isinstance(data, dict):
        return None
    table, field = data.get("anchor_table"), data.get("anchor_field")
    return (str(table), str(field)) if table and field else None


def _authoritative_relative_spec(
    question: str,
    temporal_context: Any | None,
) -> tuple[bool, tuple[int, str] | None]:
    """확정 기간 문맥이 있으면 그 모드와 일수를 상대 기간 검사의 기준으로 삼는다.

    all_time/custom이면 원래 질문의 상대 표현을 무시하고, 문맥이 없을 때만 질문에서 기간을 추출한다.
    """

    if temporal_context is None:
        spec = _relative_window_spec(question)
        return spec is not None, spec
    if hasattr(temporal_context, "model_dump"):
        data = temporal_context.model_dump(mode="json")
    elif isinstance(temporal_context, dict):
        data = temporal_context
    else:
        raise TypeError("temporal_context must be a mapping or Pydantic model")
    mode = data.get("mode")
    if mode not in {"relative", "preset"}:
        return False, None
    days = data.get("relative_days")
    return True, (int(days), "day") if days is not None else None


def _strip_sql_comments(sql: str) -> str:
    """인용된 문자열·식별자를 보존하면서 SQL 줄·블록 주석을 제거한다.

    주석의 날짜 표현이나 키워드가 기간 정책 검사에 영향을 주지 않게 한다.
    """

    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(sql):
        character = sql[index]
        following = sql[index + 1] if index + 1 < len(sql) else ""
        if quote is not None:
            output.append(character)
            if quote == "]" and character == "]":
                quote = None
            elif character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    output.append(sql[index + 1])
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
        elif character == "-" and following == "-":
            output.extend("  ")
            index += 2
            while index < len(sql) and sql[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue
        elif character == "/" and following == "*":
            output.extend("  ")
            index += 2
            while index + 1 < len(sql) and not (sql[index] == "*" and sql[index + 1] == "/"):
                output.append(" ")
                index += 1
            if index + 1 < len(sql):
                output.extend("  ")
                index += 2
            continue
        else:
            output.append(character)
        index += 1
    return "".join(output)


def _find_unfiltered_data_anchor(sql: str) -> tuple[str, str, str, str, str] | None:
    """필터 없는 MAX(날짜 컬럼) 조회 형태의 CTE를 찾아 기준 정보를 추출한다.

    지원하는 date/datetime/julianday 래핑도 허용하며 CTE명·테이블·컬럼·결과 별칭·뒤쪽 SQL을 반환한다.
    """

    for match in _CTE_START_PATTERN.finditer(sql):
        opening_parenthesis = match.end() - 1
        closing_parenthesis = _matching_parenthesis(sql, opening_parenthesis)
        if closing_parenthesis is None:
            continue
        body = sql[opening_parenthesis + 1 : closing_parenthesis]
        anchor_match = _ANCHOR_BODY_PATTERN.fullmatch(body)
        if not anchor_match:
            continue
        return (
            _plain_identifier(match.group("name")),
            anchor_match.group("table"),
            anchor_match.group("column"),
            _plain_identifier(anchor_match.group("alias")),
            sql[closing_parenthesis + 1 :],
        )
    return None


def _matching_parenthesis(sql: str, opening_index: int) -> int | None:
    """지정한 여는 괄호의 짝을 인용·이스케이프·중첩을 고려해 찾는다.

    대응하는 닫는 괄호를 찾지 못하면 None을 반환한다.
    """

    depth = 0
    quote: str | None = None
    index = opening_index
    while index < len(sql):
        character = sql[index]
        if quote is not None:
            if quote == "]" and character == "]":
                quote = None
            elif character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif character in {"'", '"', "`"}:
            quote = character
        elif character == "[":
            quote = "]"
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _uses_anchor_window(
    outer_sql: str,
    *,
    cte_name: str,
    anchor_alias: str,
    date_column: str | None,
    modifier: str,
) -> bool:
    """기준 날짜의 이동식과 조회 날짜의 시작·종료 조건이 지원하는 패턴인지 확인한다.

    BETWEEN, 양끝 비교, 다음 날 미만 범위, 정확한 기준 시각 상한 등의 조합을 검사한다.
    """

    function = r"(?:date|datetime|julianday)"
    alias = re.escape(anchor_alias)
    column = re.escape(date_column) if date_column else None
    anchor_qualifiers = _anchor_cte_qualifiers(outer_sql, cte_name)
    qualifier_pattern = "|".join(re.escape(value) for value in anchor_qualifiers)
    anchor_reference = rf"(?:(?:{qualifier_pattern})\s*\.\s*)?{alias}"
    date_reference = (
        rf"(?:{_IDENTIFIER_PART}\s*\.\s*)?{column}"
        if column
        else _QUALIFIED_IDENTIFIER
    )
    value_expression = rf"\b{function}\s*\(\s*{date_reference}\s*\)"
    start_expression = (
        rf"\b{function}\s*\(\s*{anchor_reference}\s*,\s*"
        rf"['\"]{re.escape(modifier)}['\"]\s*\)"
    )
    end_expression = rf"\b{function}\s*\(\s*{anchor_reference}\s*\)"
    exclusive_end_expression = (
        rf"\b{function}\s*\(\s*{anchor_reference}\s*,\s*['\"]\+1 day['\"]\s*\)"
    )
    between_pattern = re.compile(
        rf"{value_expression}\s+BETWEEN\s+{start_expression}\s+AND\s+{end_expression}",
        re.IGNORECASE,
    )
    lower_pattern = re.compile(
        rf"{value_expression}\s*>=\s*{start_expression}",
        re.IGNORECASE,
    )
    upper_pattern = re.compile(
        rf"{value_expression}\s*<=\s*{end_expression}",
        re.IGNORECASE,
    )
    half_open_lower_pattern = re.compile(
        rf"{date_reference}\s*>=\s*{start_expression}",
        re.IGNORECASE,
    )
    half_open_upper_pattern = re.compile(
        rf"{date_reference}\s*<\s*{exclusive_end_expression}",
        re.IGNORECASE,
    )
    exact_anchor_upper_pattern = re.compile(
        rf"{date_reference}\s*<=\s*{anchor_reference}",
        re.IGNORECASE,
    )
    return bool(
        between_pattern.search(outer_sql)
        or (lower_pattern.search(outer_sql) and upper_pattern.search(outer_sql))
        or (
            half_open_lower_pattern.search(outer_sql)
            and half_open_upper_pattern.search(outer_sql)
        )
        or (
            half_open_lower_pattern.search(outer_sql)
            and exact_anchor_upper_pattern.search(outer_sql)
        )
    )


def _canonicalize_timestamp_upper_bound(
    sql: str,
    *,
    cte_name: str,
    anchor_alias: str,
    date_column: str,
) -> str:
    """타임스탬프 컬럼을 기준 날짜 자정 이하로 잘라 마지막 날을 누락할 수 있는 조건을 찾는다.

    일치한 상한을 다음 날 미만 형태로 바꾸고, 나머지 SQL은 그대로 보존한다.
    """

    function = r"(?:date|datetime|julianday)"
    alias = re.escape(anchor_alias)
    column = re.escape(date_column)
    anchor = _find_unfiltered_data_anchor(sql)
    outer_sql = anchor[4] if anchor is not None else sql
    anchor_qualifiers = _anchor_cte_qualifiers(outer_sql, cte_name)
    qualifier_pattern = "|".join(re.escape(value) for value in anchor_qualifiers)
    anchor_reference = rf"(?:(?:{qualifier_pattern})\s*\.\s*)?{alias}"
    date_reference = rf"(?:{_IDENTIFIER_PART}\s*\.\s*)?{column}"
    pattern = re.compile(
        rf"(?P<column>{date_reference})\s*<=\s*"
        rf"(?P<function>{function})\s*\(\s*(?P<anchor>{anchor_reference})\s*\)",
        re.IGNORECASE,
    )

    def replace(match: re.Match[str]) -> str:
        """정규식으로 찾은 상한 조건 하나를 다음 날 미만 조건으로 렌더링한다.

        기존 날짜 함수와 기준 별칭을 유지해 pattern.sub 콜백으로 반환한다.
        """

        return (
            f"{match.group('column')} < "
            f"{match.group('function')}({match.group('anchor')}, '+1 day')"
        )

    return pattern.sub(replace, sql)


def _anchor_cte_qualifiers(outer_sql: str, cte_name: str) -> list[str]:
    """바깥 SQL의 FROM/JOIN에서 기준 CTE와 그 별칭을 수집한다.

    기간 조건이 CTE 이름 또는 별칭으로 기준 날짜를 참조하는 경우를 함께 인식하게 한다.
    """

    qualifiers = [cte_name]
    pattern = re.compile(
        rf"\b(?:FROM|JOIN)\s+{re.escape(cte_name)}"
        rf"(?:\s+(?:AS\s+)?(?P<alias>{_IDENTIFIER_PART}))?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(outer_sql):
        alias = match.group("alias")
        if alias:
            plain = _plain_identifier(alias)
            if plain not in qualifiers:
                qualifiers.append(plain)
    return qualifiers


def _contains_identifier(sql: str, identifier: str) -> bool:
    """SQL에 지정 식별자가 다른 이름의 일부가 아닌 독립된 이름으로 등장하는지 검사한다.

    대소문자를 무시해 기준 테이블·CTE 참조 여부를 판단한다.
    """

    return bool(
        re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(identifier)}(?![A-Za-z0-9_])",
            sql,
            re.IGNORECASE,
        )
    )


def _unqualified_identifier(identifier: str) -> str:
    """점으로 한정된 식별자에서 마지막 이름을 고르고 인용 표시를 제거한다.

    기준 테이블·컬럼의 실제 이름 부분만 비교할 때 사용한다.
    """

    return _plain_identifier(re.split(r"\s*\.\s*", identifier)[-1])


def _plain_identifier(identifier: str) -> str:
    """대괄호·큰따옴표·백틱으로 둘러싸인 식별자를 일반 이름으로 변환한다.

    같은 인용 기호를 두 번 쓴 이스케이프도 복원하고 인용되지 않은 값은 그대로 반환한다.
    """

    value = identifier.strip()
    if value.startswith("[") and value.endswith("]"):
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "`"}:
        return value[1:-1].replace(value[0] * 2, value[0])
    return value
