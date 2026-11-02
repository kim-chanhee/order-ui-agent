"""분석 계획과 생성 SQL의 일치 검사를 조율한다.

파싱·AST 추출은 sql_ast, 스키마 검사는 sql_schema_contract,
집계·등록 지표 검사는 sql_metric_contract가 담당한다.
이 모듈은 계획의 그룹·정렬·개수 제한·필터·설정된 업무 조건을 검사한다.
기존 호출자를 위해 공개 예외와 AST 유틸리티의 import 경로를 유지한다.
DB 조회와 변경 차단은 각각 sql_builder와 sql_safety가 담당한다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlglot import exp

from app.execution.analysis_semantics import load_analysis_semantics
from app.execution.join_contract import validate_join_roles
from app.execution.registered_metrics import compile_registered_metric
from app.execution.sql_ast import (
    SqlContractViolation,
    extract_filter_literals,
    extract_physical_tables,
    parse_sql_ast,
    physical_tables_from_tree,
)
from app.execution.sql_metric_contract import validate_metrics, validate_semantic_metrics
from app.execution.sql_schema_contract import validate_schema_references

__all__ = [
    "SqlContractViolation",
    "extract_filter_literals",
    "extract_physical_tables",
    "parse_sql_ast",
    "validate_sql_contract",
]

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_sql_contract(
    confirmed_plan: Any | None,
    sql: str,
    *,
    schema_context: str = "",
    temporal_context: Any | None = None,
) -> str:
    """SQL 구문과 확인된 스키마를 검사한 뒤 계획의 지표·그룹·정렬·제한·필터·업무 조건을 검증한다.

    계획이 없으면 스키마 검사까지만 수행하며 통과 시 입력 SQL을 그대로 반환한다.
    각 검사 위반은 SqlContractViolation으로 호출자에게 전달한다.
    """

    tree = parse_sql_ast(sql)
    validate_join_roles(tree)
    if schema_context:
        validate_schema_references(tree, schema_context)
    plan = _as_mapping(confirmed_plan)
    if not plan:
        return sql
    compiled = compile_registered_metric(plan)
    if compiled is not None:
        if tree.sql(dialect='sqlite', normalize=True) != parse_sql_ast(compiled).sql(dialect='sqlite', normalize=True):
            raise SqlContractViolation('registered_metric_query', 'Use the compiled registered population/subset query without changing its filters, joins or denominator')
        return sql

    metrics = _plan_metrics(plan)
    validate_metrics(tree, metrics)
    validate_semantic_metrics(tree, metrics)
    _validate_grouping(tree, plan)
    _validate_sort_and_limit(tree, plan)
    _validate_explicit_filters(tree, plan)
    _validate_configured_predicates(tree, plan, temporal_context)
    return sql


def _as_mapping(value: Any | None) -> dict[str, Any]:
    """계획 또는 기간 모델을 JSON 호환 딕셔너리로 정리한다.

    None은 빈 딕셔너리로 처리하고 딕셔너리·Pydantic 모델 이외의 입력은 TypeError를 발생시킨다.
    """

    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
    elif isinstance(value, dict):
        payload = value
    else:
        raise TypeError("confirmed_plan must be a mapping or Pydantic model")
    return payload if isinstance(payload, dict) else {}


def _plan_metrics(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """대표 metric과 추가 metrics를 한 목록으로 합친다.

    동일한 지표를 중복 검사하지 않도록 정렬된 JSON 표현 기준으로 중복을 제거한다.
    """

    raw = []
    if isinstance(plan.get("metric"), dict):
        raw.append(plan["metric"])
    raw.extend(item for item in plan.get("metrics", []) if isinstance(item, dict))
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for metric in raw:
        key = json.dumps(metric, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            unique.append(metric)
            seen.add(key)
    return unique


def _validate_grouping(tree: exp.Query, plan: dict[str, Any]) -> None:
    """계획에 그룹 기준이 있으면 SQL에 GROUP BY가 있는지 확인한다.

    기준이 물리 필드처럼 표현된 경우 해당 필드의 포함 여부도 검사한다.
    """

    required = [str(field).strip() for field in plan.get("group_by", []) if str(field).strip()]
    if not required:
        return
    groups = [group for select in tree.find_all(exp.Select) for group in select.args.get("group", exp.Group()).expressions]
    if not groups:
        raise SqlContractViolation("missing_group_by", "confirmed plan requires GROUP BY")
    aliases = {p.alias: p.this for select in tree.find_all(exp.Select) for p in select.expressions if isinstance(p,exp.Alias)}
    for bucket, fmt in {'day':'%Y-%m-%d','month':'%Y-%m','year':'%Y'}.items():
        if bucket not in required: continue
        expressions = [aliases.get(g.name,g) if isinstance(g,exp.Column) and not g.table else g for g in groups]
        if not any(isinstance(f,exp.TimeToStr) and str(f.args.get('format').this) == fmt and list(f.find_all(exp.Column))
                   for g in expressions for f in g.find_all(exp.TimeToStr)):
            raise SqlContractViolation('temporal_group_mismatch',f'{bucket} grouping requires a real date bucket {fmt}')
    group_text = " ".join(group.sql(dialect="sqlite").casefold() for group in groups)
    for field in required:
        if _looks_physical_field(field) and field.casefold() not in group_text:
            raise SqlContractViolation("group_by_mismatch", f"GROUP BY is missing confirmed field {field!r}")


def _validate_sort_and_limit(tree: exp.Query, plan: dict[str, Any]) -> None:
    """최종 조회의 정렬 항목 수·방향·지원하는 물리 필드와 LIMIT가 계획과 맞는지 검사한다.

    명시된 개수 제한은 SQL의 정수 LIMIT 값과 정확히 같아야 한다.
    """

    sort_specs = [item for item in plan.get("sort", []) if isinstance(item, dict)]
    if sort_specs:
        order = tree.args.get("order")
        if not isinstance(order, exp.Order) or len(order.expressions) < len(sort_specs):
            raise SqlContractViolation("missing_sort", "confirmed plan requires ORDER BY")
        for expected, actual in zip(sort_specs, order.expressions):
            direction = str(expected.get("direction") or "desc").casefold()
            actual_direction = "desc" if bool(actual.args.get("desc")) else "asc"
            if direction != actual_direction:
                raise SqlContractViolation(
                    "sort_direction_mismatch",
                    f"confirmed sort direction is {direction.upper()}, not {actual_direction.upper()}",
                )
            field = str(expected.get("field") or "").strip()
            if _looks_physical_field(field) and field.casefold() not in actual.sql().casefold():
                raise SqlContractViolation("sort_field_mismatch", f"ORDER BY is missing confirmed field {field!r}")

    requested_limit = plan.get("limit")
    if isinstance(requested_limit, int):
        limit = tree.args.get("limit")
        literal = limit.expression if isinstance(limit, exp.Limit) else None
        actual_limit = int(literal.this) if isinstance(literal, exp.Literal) and literal.is_int else None
        if actual_limit != requested_limit:
            raise SqlContractViolation(
                "limit_mismatch",
                f"confirmed limit is {requested_limit}, but SQL limit is {actual_limit or 'missing'}",
            )


def _validate_explicit_filters(tree: exp.Query, plan: dict[str, Any]) -> None:
    """계획의 필터 중 물리 필드로 판단되는 항목이 SQL 조건식에 참조되는지 확인한다.

    여기서는 필드 존재를 검사하며 모든 연산자와 값의 완전한 의미 일치까지 검증하지 않는다.
    """

    predicates = list(tree.find_all(exp.Predicate))
    for filter_spec in plan.get("filters", []):
        if not isinstance(filter_spec, dict):
            continue
        field = str(filter_spec.get("field") or "").strip()
        if not _IDENTIFIER.fullmatch(field):
            continue
        matching = [
            predicate
            for predicate in predicates
            if any(column.name.casefold() == field.casefold() for column in predicate.find_all(exp.Column))
        ]
        if not matching:
            raise SqlContractViolation("missing_filter", f"SQL is missing confirmed filter field {field!r}")
        if not any(_matches_filter(predicate, filter_spec) for predicate in matching):
            raise SqlContractViolation('filter_value_mismatch', f'SQL must preserve the confirmed operator and value for {field!r}')


def _matches_filter(predicate, spec):
    """Match literal predicates; unsupported expressions fail closed."""
    field, operator, value = spec['field'], spec['operator'], spec.get('value')
    def column(node):
        return isinstance(node, exp.Column) and node.name.casefold() == field.casefold()
    def literal(node, expected):
        if not isinstance(node, (exp.Literal, exp.Boolean, exp.Null)):
            return False
        try:
            return node.to_py() == expected or (isinstance(expected,(int,float)) and float(node.to_py()) == expected)
        except (ValueError,TypeError):
            return False
    pairs = {'eq':exp.EQ,'neq':exp.NEQ,'gt':exp.GT,'gte':exp.GTE,'lt':exp.LT,'lte':exp.LTE}
    if operator in pairs and isinstance(predicate,pairs[operator]):
        if column(predicate.this) and literal(predicate.expression,value):
            return True
        return operator in {'eq','neq'} and column(predicate.expression) and literal(predicate.this,value)
    if operator in {'in','not_in'} and isinstance(predicate,exp.In) and column(predicate.this) and isinstance(value,list):
        negated=isinstance(predicate.parent,exp.Not)
        return negated == (operator=='not_in') and len(predicate.expressions)==len(value) and all(
            any(literal(node,wanted) for node in predicate.expressions) for wanted in value)
    if operator=='between' and isinstance(predicate,exp.Between) and column(predicate.this) and isinstance(value,list) and len(value)==2:
        return literal(predicate.args.get('low'),value[0]) and literal(predicate.args.get('high'),value[1])
    if operator=='contains' and isinstance(predicate,exp.Like) and column(predicate.this):
        return literal(predicate.expression,'%'+str(value)+'%')
    return False


def _validate_configured_predicates(
    tree: exp.Query,
    plan: dict[str, Any],
    temporal_context: Any | None,
) -> None:
    """업무 설정과 계획의 관계 범위가 요구하는 실제 AST 조건식을 검사한다.

    상대 기간의 생성 이벤트 조건, 지정 관계의 테이블·필드·한정 값, 직접 연결 범위를 확인한다.
    """

    semantics = load_analysis_semantics()
    semantic_text = json.dumps(plan, ensure_ascii=False).casefold()
    tables = {table.casefold() for table in physical_tables_from_tree(tree)}
    mode = _temporal_mode(plan, temporal_context)
    if mode in {"relative", "preset"}:
        for entity, raw in (semantics.get("entity_lifecycles") or {}).items():
            if not isinstance(raw, dict):
                continue
            terms = [str(entity), *[str(term) for term in raw.get("semantic_terms", [])]]
            table = str(raw.get("table") or "")
            field = str(raw.get("creation_field") or "")
            value = str(raw.get("creation_value") or "")
            if (
                table.casefold() in tables
                and any(_contains_term(semantic_text, term.casefold()) for term in terms)
                and not _has_equality_predicate(tree, field, value)
            ):
                raise SqlContractViolation(
                    "missing_creation_predicate",
                    f"relative {entity} population requires a real AST predicate {table}.{field} = {value!r}",
                )

    selected_scope = str(plan.get("relationship_scope") or "").strip().casefold()
    for edge in semantics.get("entity_relationships", []):
        if not isinstance(edge, dict) or str(edge.get("name") or "").strip().casefold() != selected_scope:
            continue
        table = str(edge.get("table") or "").strip()
        source_field = str(edge.get("source_field") or "").strip()
        target_field = str(edge.get("target_field") or "").strip()
        qualifier_field = str(edge.get("qualifier_field") or "").strip()
        qualifier_value = str(edge.get("qualifier_value") or "").strip()
        if table and table.casefold() not in tables:
            raise SqlContractViolation(
                "missing_configured_relationship",
                f"relationship scope {selected_scope!r} requires table {table}",
            )
        referenced_columns = {column.name.casefold() for column in tree.find_all(exp.Column)}
        missing_fields = [
            field for field in (source_field, target_field)
            if field and field.casefold() not in referenced_columns
        ]
        if missing_fields:
            raise SqlContractViolation(
                "missing_relationship_fields",
                f"relationship scope {selected_scope!r} requires fields {', '.join(missing_fields)}",
            )
        if qualifier_field and qualifier_value and not _has_equality_predicate(
            tree, qualifier_field, qualifier_value
        ):
            raise SqlContractViolation(
                "missing_relationship_predicate",
                f"relationship scope {selected_scope!r} requires "
                f"{table}.{qualifier_field} = {qualifier_value!r}",
            )
        break

    direct_terms = [str(value).casefold() for value in semantics.get("direct_scope_terms", [])]
    if not any(_contains_term(semantic_text, term) for term in direct_terms):
        return
    for scope in semantics.get("relationship_scopes", []):
        if not isinstance(scope, dict):
            continue
        required = (
            (str(scope.get("event_object_table") or ""), str(scope.get("object_qualifier_field") or ""), str(scope.get("object_qualifier_value") or "")),
            (str(scope.get("membership_table") or ""), str(scope.get("membership_qualifier_field") or ""), str(scope.get("membership_qualifier_value") or "")),
        )
        for table, field, value in required:
            if table and table.casefold() not in tables:
                raise SqlContractViolation("missing_relationship_scope", f"direct relationship requires table {table}")
            if field and value and not _has_equality_predicate(tree, field, value):
                raise SqlContractViolation(
                    "missing_relationship_predicate",
                    f"direct relationship requires a real AST predicate {table}.{field} = {value!r}",
                )


def _has_equality_predicate(tree: exp.Query, field: str, value: str) -> bool:
    """구문 트리에 지정 컬럼과 문자열 값이 함께 참여하는 동등 비교식이 있는지 확인한다.

    대소문자를 무시하며 업무 설정의 실제 조건식 존재를 판단하는 데 사용한다.
    """

    for equality in tree.find_all(exp.EQ):
        columns = list(equality.find_all(exp.Column))
        literals = [literal for literal in equality.find_all(exp.Literal) if literal.is_string]
        if (
            any(column.name.casefold() == field.casefold() for column in columns)
            and any(str(literal.this).casefold() == value.casefold() for literal in literals)
        ):
            return True
    return False


def _temporal_mode(plan: dict[str, Any], temporal_context: Any | None) -> str | None:
    """기간 문맥의 mode를 우선 읽고 없으면 계획의 date_range.mode를 사용한다.

    두 위치 모두 기간 정보가 없으면 None을 반환한다.
    """

    context = _as_mapping(temporal_context)
    if context.get("mode"):
        return str(context["mode"])
    date_range = plan.get("date_range")
    return str(date_range.get("mode")) if isinstance(date_range, dict) else None


def _contains_term(text: str, term: str) -> bool:
    """비어 있지 않은 의미 용어가 단어 경계로 등장하는지 확인한다.

    다른 단어 일부가 우연히 일치해 업무 규칙이 적용되는 것을 줄인다.
    """

    return bool(term and re.search(rf"\b{re.escape(term)}\b", text))


def _looks_physical_field(field: str) -> bool:
    """단순 SQL 식별자 형식이면서 언더스코어를 포함하거나 id인 이름인지 판별한다.

    의미 라벨 전체를 물리 컬럼으로 강제하지 않기 위한 제한적인 휴리스틱이다.
    """

    return bool(_IDENTIFIER.fullmatch(field) and ("_" in field or field == "id"))
