"""계획의 집계 종류·필드·건수 단위와 등록된 비율 지표를 검증한다."""

from __future__ import annotations

import re
from typing import Any

from sqlglot import exp

from app.execution.analysis_semantics import load_analysis_semantics
from app.execution.sql_ast import SqlContractViolation

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_metrics(tree: exp.Query, metrics: list[dict[str, Any]]) -> None:
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
        if kind == 'count' and metric.get('distinct') is True and not expected_fields:
            configured = {field for entity in load_analysis_semantics().get('entity_roles', {}).values()
                          for field in entity.get('identifier_fields', [])}
            candidates = [node for node in candidates if any(
                c.name == 'id' or c.name.endswith('_id') or c.name in configured
                for c in node.find_all(exp.Column))]
            if not candidates:
                raise SqlContractViolation('count_unit_mismatch', 'Distinct entity counts require a stable *_id or profile-declared identifier')
        if expected_fields:
            field_bound = [node for node in candidates if _aggregate_matches_any_field(node, expected_fields)]
            if field_bound:
                candidates = field_bound
            else:
                rendered = ", ".join(sorted(expected_fields))
                raise SqlContractViolation(
                    "count_unit_mismatch" if kind == 'count' else 'metric_field_mismatch',
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
    if metric.get('kind') in {'sum','avg','min','max'} and _IDENTIFIER.fullmatch(field):
        return {field}
    if _IDENTIFIER.fullmatch(field) and (field == "id" or field.endswith("_id")):
        return {field}

    text = f"{field} {unit}"
    expected: set[str] = set()
    semantics = load_analysis_semantics()
    configured = {name for definition in semantics.get('entity_roles', {}).values()
                  for name in definition.get('identifier_fields', [])}
    configured |= {role['field'] for role in semantics.get('column_roles', []) if role.get('field')}
    if field in configured:
        return {field}
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


def validate_semantic_metrics(tree: exp.Query, metrics: list[dict]) -> None:
    """Verify registered ratio populations using conditional DISTINCT aggregation.

    Unknown algebra/CTE ratio forms fail closed and must be rewritten by the SQL agent.
    """
    definitions = load_analysis_semantics().get('semantic_metrics',{})
    for metric in metrics:
        identifier = metric.get('semantic_id')
        if not identifier: continue
        definition = definitions.get(identifier)
        if not definition:
            raise SqlContractViolation('unknown_semantic_metric',f'Unknown registered metric {identifier}')
        if definition.get('population'):
            raise SqlContractViolation('registered_metric_query', 'A population metric must be the primary compiled metric')
        for key in ('field','numerator','denominator'):
            if metric.get(key) != definition[key]:
                raise SqlContractViolation('semantic_metric_mismatch',f'{identifier}: invalid {key}')
        matched = False
        for division in tree.find_all(exp.Div):
            select = division.find_ancestor(exp.Select)
            if not select: continue
            physical = [t for t in select.find_all(exp.Table) if t.find_ancestor(exp.Select) is select]
            tables = {t.name for t in physical}
            if definition['table'] not in tables: continue
            source_aliases = {t.alias_or_name for t in physical if t.name == definition['table']}
            def source_column(node, field):
                return isinstance(node,exp.Column) and node.name == field and (node.table in source_aliases or (not node.table and len(physical)==1))
            numerator = division.this
            floating = False
            if isinstance(numerator,exp.Mul):
                sides = (numerator.this,numerator.expression)
                if isinstance(sides[0],exp.Literal) and sides[0].this == '1.0':
                    numerator, floating = sides[1], True
                elif isinstance(sides[1],exp.Literal) and sides[1].this == '1.0':
                    numerator, floating = sides[0], True
            if isinstance(numerator,exp.Cast) and str(numerator.args.get('to')).upper() in {'FLOAT','DOUBLE','REAL'}:
                numerator, floating = numerator.this, True
            denominator = division.expression
            if not isinstance(denominator,exp.Nullif) or not isinstance(denominator.expression,exp.Literal) or denominator.expression.this != '0': continue
            denominator = denominator.this
            if not floating or not isinstance(numerator,exp.Count) or not isinstance(denominator,exp.Count): continue
            if not isinstance(numerator.this,exp.Distinct) or not isinstance(denominator.this,exp.Distinct): continue
            if len(numerator.this.expressions)!=1 or len(denominator.this.expressions)!=1: continue
            if not source_column(denominator.this.expressions[0],definition['field']): continue
            case = numerator.this.expressions[0]
            if not isinstance(case,exp.Case) or len(case.args.get('ifs',[]))!=1: continue
            if case.args.get('default') is not None and not isinstance(case.args['default'],exp.Null): continue
            branch = case.args['ifs'][0]
            predicate = branch.this
            if not isinstance(predicate,exp.EQ) or not source_column(branch.args.get('true'),definition['field']): continue
            pairs = [(predicate.this,predicate.expression),(predicate.expression,predicate.this)]
            if not any(source_column(c,definition['event_field']) and isinstance(v,exp.Literal) and v.is_string and v.this==definition['numerator_event'] for c,v in pairs): continue
            # Reject denominator narrowing, including an event predicate hidden in a subquery.
            allowed_population = set(definition['population_events'])
            bad_population = False
            for where in tree.find_all(exp.Where):
                for predicate in where.find_all(exp.Predicate):
                    if any(c.name == definition['event_field'] for c in predicate.find_all(exp.Column)):
                        literals = {v.this for v in predicate.find_all(exp.Literal) if v.is_string}
                        if not isinstance(predicate,exp.In) or literals != allowed_population:
                            bad_population = True
            if bad_population: continue
            matched = True
            break
        if not matched:
            raise SqlContractViolation('semantic_ratio_population',
                f'{identifier} requires 1.0 * COUNT(DISTINCT CASE WHEN {definition["event_field"]} = '
                f'{definition["numerator_event"]!r} THEN {definition["field"]} END) / '
                f'NULLIF(COUNT(DISTINCT {definition["field"]}), 0) on {definition["table"]}; '
                'do not narrow the denominator to failures')


def _contains_term(text: str, term: str) -> bool:
    """비어 있지 않은 의미 용어가 단어 경계로 등장하는지 확인한다.

    다른 단어 일부가 우연히 일치해 업무 규칙이 적용되는 것을 줄인다.
    """

    return bool(term and re.search(rf"\b{re.escape(term)}\b", text))

