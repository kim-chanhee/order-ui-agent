"""SQL 계약 검증에서 공유하는 예외·SQLite 파싱·AST 정보 추출."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError

_TEMPORAL_MODIFIER = re.compile(
    r"^[+-]?\d+\s+(?:day|days|week|weeks|month|months|year|years)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SqlContractViolation(ValueError):
    """계획과 SQL의 불일치를 안정적인 오류 코드와 상세 내용으로 표현한다.

    실행 도구와 실패 분류기가 위반 종류를 구분하고 LLM이 수정하도록 전달하는 예외다.
    """

    code: str
    detail: str

    def __str__(self) -> str:
        """계약 오류를 코드와 상세 사유가 함께 보이는 문자열로 반환한다.

        도구 응답과 로그에서 오류 종류를 식별하기 쉽게 한다.
        """

        return f"[{self.code}] {self.detail}"


def parse_sql_ast(sql: str) -> exp.Query:
    """SQLite 문법으로 SQL을 파싱하고 정확히 하나의 조회문인지 확인한다.

    문법 오류·여러 문장·조회문이 아닌 입력은 SqlContractViolation으로 보고한다.
    """

    try:
        statements = [statement for statement in parse(sql, read="sqlite") if statement]
    except ParseError as exc:
        raise SqlContractViolation("sql_parse_error", f"SQLite SQL parse failed: {exc}") from exc
    if len(statements) != 1:
        raise SqlContractViolation("statement_count", "SQL must contain exactly one statement")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise SqlContractViolation("not_a_query", "Only a SELECT/WITH query is allowed")
    return tree


def extract_physical_tables(sql: str) -> set[str]:
    """단일 SQL의 구문 트리에서 실제 테이블 이름을 모은다.

    WITH절의 CTE 이름은 임시 참조이므로 실제 테이블 목록에서 제외한다.
    """

    tree = parse_sql_ast(sql)
    cte_names = {cte.alias_or_name.casefold() for cte in tree.find_all(exp.CTE)}
    return {
        table.name
        for table in tree.find_all(exp.Table)
        if table.name and table.name.casefold() not in cte_names
    }


def extract_filter_literals(sql: str) -> list[str]:
    """구문 트리의 실제 조건식에 참여하는 문자열 값을 중복 없이 추출한다.

    LIKE 양끝 와일드카드와 날짜 이동 수식은 정리·제외하며 주석과 단순 출력 상수는 조건 근거로 보지 않는다.
    """

    tree = parse_sql_ast(sql)
    values: list[str] = []
    for predicate in tree.find_all(exp.Predicate):
        for literal in predicate.find_all(exp.Literal):
            if not literal.is_string:
                continue
            value = str(literal.this).replace("''", "'").strip()
            if isinstance(predicate, (exp.Like, exp.ILike)):
                value = value.strip("%_").strip()
            if not value or _TEMPORAL_MODIFIER.fullmatch(value):
                continue
            if value not in values:
                values.append(value)
    return values


def physical_tables_from_tree(tree: exp.Query) -> set[str]:
    """이미 파싱한 구문 트리에서 CTE를 제외한 물리 테이블 집합을 반환한다.

    업무 관계가 요구하는 테이블의 포함 여부를 검사할 때 재사용한다.
    """

    cte_names = {cte.alias_or_name.casefold() for cte in tree.find_all(exp.CTE)}
    return {table.name for table in tree.find_all(exp.Table) if table.name.casefold() not in cte_names}

