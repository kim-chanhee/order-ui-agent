"""생성 SQL이 DB를 변경하지 못하도록 읽기 전용 경계를 적용한다.

validate_read_only_sql은 주석·인용 문자열을 가린 뒤 문장 수·허용 시작 구문·차단 단어를 검사한다.
SELECT/WITH와 제한된 EXPLAIN QUERY PLAN SELECT 형태를 허용한다.
create_read_only_connection은 mode=ro 연결과 SQLite authorizer로 실행 권한도 제한한다.
내부 스키마 탐색에는 PRAGMA 읽기가 필요하지만 사용자 SQL의 PRAGMA는 차단한다.
이 모듈은 변경 차단을 담당하며 분석 계획과의 의미 일치는 별도 계약 검사에서 다룬다.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path


BLOCKED_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "ATTACH",
    "DETACH",
    "REPLACE",
    "VACUUM",
    "REINDEX",
    "PRAGMA",
    "LOAD_EXTENSION",
}
READ_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_PRAGMA,
}


def _strip_comments_and_strings(sql: str) -> str:
    """SQL 주석과 인용 문자열·식별자를 공백으로 가리면서 문장 형태는 유지한다.

    리터럴 안의 차단 단어나 세미콜론을 실제 SQL 구문으로 잘못 세지 않도록 한다.
    """

    result: list[str] = []
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if ch == "-" and nxt == "-":
            result.append(" ")
            i += 2
            while i < len(sql) and sql[i] not in "\r\n":
                result.append(" ")
                i += 1
            continue
        if ch == "/" and nxt == "*":
            result.extend("  ")
            i += 2
            while i + 1 < len(sql) and not (sql[i] == "*" and sql[i + 1] == "/"):
                result.append(" ")
                i += 1
            if i + 1 < len(sql):
                result.extend("  ")
                i += 2
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            result.append(" ")
            i += 1
            while i < len(sql):
                result.append(" ")
                if sql[i] == quote:
                    if quote == "'" and i + 1 < len(sql) and sql[i + 1] == "'":
                        result.append(" ")
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == "[":
            result.append(" ")
            i += 1
            while i < len(sql):
                result.append(" ")
                if sql[i] == "]":
                    i += 1
                    break
                i += 1
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def _statement_count(masked_sql: str) -> int:
    """마스킹된 SQL을 세미콜론으로 나누고 비어 있지 않은 문장 수를 센다.

    문장 끝의 세미콜론만으로 생긴 빈 조각은 제외한다.
    """

    statements = [part.strip() for part in masked_sql.split(";")]
    if statements and not statements[-1]:
        statements.pop()
    return len([part for part in statements if part])


def validate_read_only_sql(sql: str) -> str:
    """비어 있지 않은 단일 조회문인지와 차단된 SQL 키워드 포함 여부를 검사한다.

    SELECT/WITH 또는 제한된 EXPLAIN QUERY PLAN SELECT를 허용한다.
    위반하면 ValueError를 발생시키고 통과하면 바깥 공백을 제거한 SQL을 반환한다.
    """

    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL must not be empty")
    sql = sql.strip()
    masked = _strip_comments_and_strings(sql)
    if _statement_count(masked) != 1:
        raise ValueError("SQL must contain exactly one statement")

    normalized = masked.strip()
    if not re.match(r"(?is)^(SELECT|WITH)\b", normalized):
        if not re.match(r"(?is)^EXPLAIN\s+QUERY\s+PLAN\s+SELECT\b", normalized):
            raise ValueError("Only SELECT or WITH read-only SQL is allowed")

    tokens = {token.upper() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", normalized)}
    blocked = sorted(tokens & BLOCKED_KEYWORDS)
    if blocked:
        raise ValueError(f"Unsafe SQL keyword rejected: {blocked[0]}")
    return sql


def _readonly_authorizer(action_code: int, _arg1: str | None, _arg2: str | None, _db: str | None, _source: str | None) -> int:
    """SQLite가 요청한 작업 코드가 허용된 읽기 작업인지 판단한다.

    목록에 있는 작업만 SQLITE_OK로 허용하고 나머지는 SQLITE_DENY로 차단한다.
    """

    if action_code in READ_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def create_read_only_connection(path: Path) -> sqlite3.Connection:
    """주어진 DB 경로를 절대 경로로 바꾸고 SQLite mode=ro 연결을 연다.

    잠금 대기 시간과 authorizer를 설정해 반환하며 연결을 닫는 책임은 호출자에게 있다.
    """

    absolute = Path(path).expanduser().resolve()
    uri = f"file:{absolute.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.set_authorizer(_readonly_authorizer)
    return conn
