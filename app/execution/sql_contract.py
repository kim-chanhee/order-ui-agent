"""분석 계획과 생성 SQL이 맞는지 SQL 구문 트리(AST)로 검사한다.

sqlglot으로 단일 SQLite 조회문을 파싱하고 물리 테이블·조건 값·집계 구조를 추출한다.
검사 대상은 확인된 테이블·컬럼, 지표 종류·건수 단위·비율 나눗셈,
그룹화·정렬·개수 제한·필터 필드·설정된 업무 조건이다.
의미 이름을 모든 SQL 표현식에 완전히 대응시키는 검증기는 아니며,
명시적인 물리 필드와 지원하는 구조·설정에 근거한 검사만 수행한다.
위반하면 SqlContractViolation의 코드와 상세 사유로 SQL 수정을 유도한다.
DB 조회와 변경 차단은 각각 sql_builder와 sql_safety가 담당한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.execution.analysis_semantics import load_analysis_semantics


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TEMPORAL_MODIFIER = re.compile(
    r"^[+-]?\d+\s+(?:day|days|week|weeks|month|months|year|years)$",
    re.IGNORECASE,
)
_SCHEMA_HEADER = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\((.*)\)$")


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
    if schema_context:
        _validate_schema_references(tree, schema_context)
    plan = _as_mapping(confirmed_plan)
    if not plan:
        return sql

    metrics = _plan_metrics(plan)
    _validate_metrics(tree, metrics)
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


def _validate_metrics(tree: exp.Query, metrics: list[dict[str, Any]]) -> None:
    """최종 출력 표현식에 계획이 요구하는 집계 종류·개수·DISTINCT·건수 단위가 있는지 검사한다.

    비율 지표에는 나눗셈 표현식을 요구하고, 유틸리티 CTE 안의 집계만으로 출력 지표를 충족했다고 보지 않는다.
    """

    aggregate_types: dict[str, type[exp.AggFunc]] = {
        "count": exp.Count,
        "sum": exp.Sum,
        "avg": exp.Avg,
        "min": exp.Min,
        "max": exp.Max,
    }
    # Only aggregates reachable from the final projection satisfy an output
    # metric. Anchor/utility CTE aggregates must not count as requested results.
    output_projections = list(tree.selects)
    aggregate_nodes = [
        node
        for projection in output_projections
        for node in projection.find_all(exp.AggFunc)
    ]
    required_aggregates = [metric for metric in metrics if metric.get("kind") in aggregate_types]
    if len(aggregate_nodes) < len(required_aggregates):
        raise SqlContractViolation(
            "metric_projection_mismatch",
            f"confirmed plan requires {len(required_aggregates)} aggregate projection(s), but SQL has {len(aggregate_nodes)}",
        )

    used: set[int] = set()
    for metric in required_aggregates:
        kind = str(metric.get("kind"))
        candidates = [
            node
            for node in aggregate_nodes
            if isinstance(node, aggregate_types[kind]) and id(node) not in used
        ]
        if kind == "count" and metric.get("distinct") is True:
            candidates = [node for node in candidates if isinstance(node.this, exp.Distinct)]
        expected_fields = _expected_metric_fields(metric)
        if expected_fields:
            field_bound = [node for node in candidates if _aggregate_matches_any_field(node, expected_fields)]
            if field_bound:
                candidates = field_bound
            elif kind == "count":
                rendered = ", ".join(sorted(expected_fields))
                raise SqlContractViolation(
                    "count_unit_mismatch",
                    f"confirmed count unit must use COUNT(DISTINCT {rendered}); a generic event/row id is not equivalent",
                )
        if not candidates:
            distinct = "DISTINCT " if metric.get("distinct") is True else ""
            raise SqlContractViolation(
                "missing_metric",
                f"confirmed metric requires {kind.upper()}({distinct}...) in the SQL AST",
            )
        used.add(id(candidates[0]))

    for metric in metrics:
        if metric.get("kind") == "ratio" and not any(
            projection.find(exp.Div) for projection in output_projections
        ):
            raise SqlContractViolation(
                "missing_ratio",
                "confirmed ratio metric requires an explicit numerator/denominator division",
            )


def _expected_metric_fields(metric: dict[str, Any]) -> set[str]:
    """지표의 field·unit에서 집계에 사용할 것으로 기대되는 식별자 후보를 만든다.

    명시된 ID를 우선하고 업무 의미 설정·일반 엔터티 명칭·영문 토큰 규칙으로 후보를 보충한다.
    반환값은 스키마 존재를 증명하는 값이 아니라 집계 단위 검사에 쓰는 기대 필드 집합이다.
    """

    field = str(metric.get("field") or "").strip().casefold()
    unit = str(metric.get("unit") or "").strip().casefold()
    if _IDENTIFIER.fullmatch(field) and (field == "id" or field.endswith("_id")):
        return {field}

    text = f"{field} {unit}"
    expected: set[str] = set()
    semantics = load_analysis_semantics()
    for entity, raw in (semantics.get("entity_lifecycles") or {}).items():
        if not isinstance(raw, dict):
            continue
        terms = [str(entity), *[str(term) for term in raw.get("semantic_terms", [])]]
        if any(_contains_term(text, term.casefold()) for term in terms):
            identifier = str(raw.get("id_field") or "").casefold()
            if _IDENTIFIER.fullmatch(identifier):
                expected.add(identifier)

    common_entities = {
        "order": ("order", "orders", "주문"),
        "customer": ("customer", "customers", "고객"),
        "event": ("event", "events", "이벤트", "건"),
        "item": ("item", "items", "물품", "상품"),
        "product": ("product", "products", "제품"),
        "shipment": ("shipment", "shipments", "배송"),
    }
    for physical, terms in common_entities.items():
        if any(_contains_term(text, term) for term in terms):
            expected.add(f"{physical}_id")
    if not expected and field:
        words = re.findall(r"[a-z][a-z0-9_]*", field)
        if words:
            token = words[-1].removesuffix("s")
            expected.add(f"{token}_id")
    return expected


def _aggregate_matches_any_field(node: exp.AggFunc, fields: set[str]) -> bool:
    """집계 표현식이 기대 식별자 집합 중 하나를 참조하는지 확인한다.

    컬럼 이름의 대소문자를 무시해 비교한다.
    """

    return any(column.name.casefold() in fields for column in node.find_all(exp.Column))


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
        if not _looks_physical_field(field):
            continue
        matching = [
            predicate
            for predicate in predicates
            if any(column.name.casefold() == field.casefold() for column in predicate.find_all(exp.Column))
        ]
        if not matching:
            raise SqlContractViolation("missing_filter", f"SQL is missing confirmed filter field {field!r}")


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
    tables = {table.casefold() for table in _physical_tables_from_tree(tree)}
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


def _validate_schema_references(tree: exp.Query, schema_context: str) -> None:
    """조회에 쓰인 테이블·컬럼을 도구가 확인한 라이브 스키마 설명과 대조한다.

    CTE와 출력 별칭은 구분하고 존재하지 않는 물리 이름은 계약 오류로 보고한다.
    """

    schema = _schema_from_context(schema_context)
    if not schema:
        return
    cte_names = {cte.alias_or_name.casefold() for cte in tree.find_all(exp.CTE)}
    aliases: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        if table.name.casefold() in cte_names:
            continue
        name = table.name.casefold()
        aliases[(table.alias_or_name or table.name).casefold()] = name
        if name not in schema:
            raise SqlContractViolation("unknown_table", f"table {table.name!r} was not found in inspected live schema")
    projection_aliases = {
        projection.alias.casefold()
        for select in tree.find_all(exp.Select)
        for projection in select.expressions
        if projection.alias
    }
    all_columns = set().union(*schema.values()) if schema else set()
    for column in tree.find_all(exp.Column):
        name = column.name.casefold()
        qualifier = column.table.casefold()
        if qualifier in cte_names or name in projection_aliases:
            continue
        if qualifier and qualifier in aliases:
            if name not in schema[aliases[qualifier]]:
                raise SqlContractViolation("unknown_column", f"column {column.sql()!r} was not found in inspected live schema")
        elif not qualifier and name not in all_columns:
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


def _physical_tables_from_tree(tree: exp.Query) -> set[str]:
    """이미 파싱한 구문 트리에서 CTE를 제외한 물리 테이블 집합을 반환한다.

    업무 관계가 요구하는 테이블의 포함 여부를 검사할 때 재사용한다.
    """

    cte_names = {cte.alias_or_name.casefold() for cte in tree.find_all(exp.CTE)}
    return {table.name for table in tree.find_all(exp.Table) if table.name.casefold() not in cte_names}


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
