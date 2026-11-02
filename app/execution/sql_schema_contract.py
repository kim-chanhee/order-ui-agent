"""SQL의 물리 테이블·컬럼 참조를 확인된 라이브 스키마와 대조한다."""

from __future__ import annotations

import re

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from app.execution.sql_ast import SqlContractViolation

_SCHEMA_HEADER = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\((.*)\)$")


def validate_schema_references(tree: exp.Query, schema_context: str) -> None:
    """조회에 쓰인 테이블·컬럼을 도구가 확인한 라이브 스키마 설명과 대조한다.

    CTE와 출력 별칭은 구분하고 존재하지 않는 물리 이름은 계약 오류로 보고한다.
    """

    schema = _schema_from_context(schema_context)
    if not schema:
        return
    for scope in traverse_scope(tree):
        physical = {alias.casefold(): source for alias, source in scope.sources.items()
                    if isinstance(source, exp.Table)}
        for source in physical.values():
            if source.name.casefold() not in schema:
                raise SqlContractViolation("unknown_table", f"table {source.name!r} was not found in inspected live schema")
        projection_aliases = {p.alias.casefold() for p in scope.expression.selects if p.alias}
        for column in scope.columns:
            name, qualifier = column.name.casefold(), column.table.casefold()
            if qualifier:
                owner = scope
                source = next((v for k, v in owner.sources.items() if k.casefold() == qualifier), None)
                while source is None and owner.parent:
                    owner = owner.parent
                    source = next((v for k, v in owner.sources.items() if k.casefold() == qualifier), None)
                if isinstance(source, Scope):
                    continue  # CTE/subquery projections are validated in their own scope.
                if isinstance(source, exp.Table) and name not in schema[source.name.casefold()]:
                    raise SqlContractViolation("unknown_column", f"column {column.sql()!r} was not found in inspected live schema")
            elif name not in projection_aliases:
                candidates = set().union(*(schema[source.name.casefold()] for source in physical.values())) if physical else set()
                for source in scope.sources.values():
                    if isinstance(source, Scope):
                        candidates.update(p.alias_or_name.casefold() for p in source.expression.selects)
                if name not in candidates and '*' not in candidates and not scope.parent:
                    raise SqlContractViolation("unknown_column", f"column {column.name!r} was not found in inspected live schema")


def _schema_from_context(context: str) -> dict[str, set[str]]:
    """스키마 설명 중 table(column type, ...) 형태의 줄을 읽어 테이블별 컬럼 집합으로 만든다.

    다른 설명 줄은 무시하고 이름은 비교하기 쉽게 소문자로 정리한다.
    """

    schema: dict[str, set[str]] = {}
    for raw_line in context.splitlines():
        match = _SCHEMA_HEADER.fullmatch(raw_line.strip())
        if not match:
            continue
        columns = {
            part.strip().split()[0].strip('"`[]').casefold()
            for part in match.group(2).split(",")
            if part.strip()
        }
        schema[match.group(1).casefold()] = columns
    return schema

