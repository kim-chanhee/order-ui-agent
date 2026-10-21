"""검증된 SQL을 실제 DB에서 실행하고 결과를 기본 표 형식으로 표시한다.

파일명과 달리 SQL을 생성하지 않는다. 생성 SQL의 읽기 전용 여부를 다시 확인한 뒤
설정된 SQLite DB에서 매개변수와 함께 실행하고 컬럼 이름과 행을 반환한다.
조회 행 수와 SQLite VM 연산량을 제한하고 연결은 항상 닫는다.
EXPLAIN QUERY PLAN은 실제 결과 조회 없이 실행 계획을 제공한다.
결과 표시 함수는 단일 값 또는 제한된 Markdown 표로 기본 답변을 만든다.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing

from app.data.database import DEFAULT_DB_PATH
from app.execution.sql_safety import create_read_only_connection, validate_read_only_sql


SqlParams = tuple[object, ...]
MAX_RESULT_ROWS = int(os.environ.get("SQL_MAX_RESULT_ROWS", "200"))
SQL_MAX_VM_STEPS = int(os.environ.get("SQL_MAX_VM_STEPS", "2000000"))
SQL_PROGRESS_CALLBACK_STEPS = int(os.environ.get("SQL_PROGRESS_CALLBACK_STEPS", "1000"))


def _run_fallback_sql(
    query: str,
    params: SqlParams = (),
    *,
    max_result_rows: int = MAX_RESULT_ROWS,
) -> tuple[list[str], list[sqlite3.Row]]:
    """SQL을 읽기 전용으로 검증한 뒤 설정된 DB에 매개변수와 함께 실행한다.

    결과 행 수와 VM 연산량을 제한하고 제한 초과 중단은 알아보기 쉬운 RuntimeError로 바꾼다.
    연결을 닫은 뒤 컬럼 이름 목록과 sqlite3.Row 목록을 반환한다.
    """

    query = validate_read_only_sql(query)
    with closing(create_read_only_connection(DEFAULT_DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        progress_calls = 0

        def stop_expensive_query() -> int:
            """SQLite 진행 콜백 호출 수로 누적 VM 연산량을 추정한다.

            설정된 연산 한도에 도달하면 1을 반환해 실행 중인 조회를 중단시킨다.
            """

            nonlocal progress_calls
            progress_calls += 1
            return int(progress_calls * SQL_PROGRESS_CALLBACK_STEPS >= SQL_MAX_VM_STEPS)

        if SQL_MAX_VM_STEPS > 0 and SQL_PROGRESS_CALLBACK_STEPS > 0:
            conn.set_progress_handler(stop_expensive_query, SQL_PROGRESS_CALLBACK_STEPS)
        try:
            cursor = conn.execute(query, params)
            if max_result_rows > 0:
                rows = cursor.fetchmany(max_result_rows + 1)[:max_result_rows]
            else:
                rows = cursor.fetchall()
        except sqlite3.OperationalError as exc:
            if "interrupt" in str(exc).lower():
                raise RuntimeError("SQL execution exceeded the configured resource limit") from exc
            raise
        finally:
            conn.set_progress_handler(None, 0)
        columns = [description[0] for description in (cursor.description or [])]
    return columns, rows


def explain_query_plan(sql: str) -> list[str]:
    """읽기 전용 검증을 통과한 SQL의 EXPLAIN QUERY PLAN 상세 줄을 반환한다.

    실제 결과 조회 없이 스캔·인덱스·임시 정렬 등의 실행 계획을 후보 평가에 제공한다.
    """

    validated = validate_read_only_sql(sql)
    with closing(create_read_only_connection(DEFAULT_DB_PATH)) as conn:
        rows = conn.execute(f"EXPLAIN QUERY PLAN {validated}").fetchall()
    return [str(row[3]) for row in rows if len(row) > 3]


def _format_generic_sql_rows(columns: list[str], rows: list[sqlite3.Row]) -> str:
    """원시 컬럼과 행을 기본 한국어 답변으로 표시한다.

    단일 값은 문장으로, 일반 결과는 최대 6개 컬럼·20개 행의 Markdown 표로 보여준다.
    """

    if len(rows) == 1 and len(columns) == 1:
        return f"Answer: 조회 결과 {_display_column_label(columns[0])}는 {rows[0][columns[0]]}입니다."

    lines = [f"Answer: SQL을 실행했고 {len(rows)}행을 조회했습니다."]
    if not rows or not columns:
        return "\n".join(lines)

    preview_columns = columns[:6]
    lines.extend(_markdown_table(preview_columns, rows[:20]))
    if len(rows) > 20:
        lines.append(f"\n상위 20행만 표시했습니다. 전체 {len(rows)}행입니다.")
    return "\n".join(lines)


def _display_column_label(column: str) -> str:
    """컬럼명의 언더스코어를 공백으로 바꿔 기본 표시 이름을 만든다.

    업무 의미 번역이나 별도 라벨 매핑은 수행하지 않는다.
    """

    return column.replace("_", " ")


def _markdown_table(columns: list[str], rows: list[sqlite3.Row]) -> list[str]:
    """선택된 컬럼과 행에서 Markdown 표의 헤더·구분선·본문 줄 목록을 만든다.

    각 셀은 _format_table_value로 정리해 표 문법이 깨지지 않게 한다.
    """

    header = "| " + " | ".join(_display_column_label(column) for column in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(_format_table_value(row[column]) for column in columns) + " |"
        for row in rows
    ]
    return ["", header, separator, *body]


def _format_table_value(value: object) -> str:
    """None은 대시로, 나머지는 문자열로 표시한다.

    파이프 문자를 이스케이프하고 줄바꿈을 공백으로 바꿔 하나의 Markdown 셀에 맞춘다.
    """

    if value is None:
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ")
