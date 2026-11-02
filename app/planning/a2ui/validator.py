"""A2UI 전용 계획 확정 검증과 서버가 허용한 편집 범위 검사.

주요 기능:
    - 확인 요청의 질문이 계획과 일치하는지 확인한다.
    - 필수 입력·미해결 조건·조회 불가 사유·비율 지표·선택값을 검증한다.
    - 서버가 발급한 편집 경로와 실제 변경 경로를 비교한다.
    - 하위 필드 편집 권한만으로 상위 객체를 삭제하는 변경을 차단한다.
"""

from __future__ import annotations

import re
from typing import Any

from app.planning.analysis_models import AnalysisPlan
from app.planning.ui_models import UiBlock, UiPlan
from app.planning.validator import compute_missing_fields, value_at_path, condition_matches


def validate_ui_plan(plan: UiPlan, question: str) -> AnalysisPlan:
    """질문 일치·필수값·미해결 조건·조회 불가 사유·비율 지표·선택값을 검사해 실행할 계획을 반환한다."""

    analysis = AnalysisPlan.model_validate(plan.analysis_plan.model_dump(mode="json"))
    if plan.ui_state.get("semantic_catalog"):
        validate_dynamic_semantics(analysis, plan.ui_state["semantic_catalog"])
    if analysis.original_question.strip() != question.strip():
        raise ValueError("review plan question does not match the confirmation request")
    missing = compute_missing_fields(analysis, plan.ui_blocks)
    plan.missing_fields = missing
    if missing:
        labels = {
            (block.field_path or block.key): (block.label or block.field_path or block.key)
            for block in plan.ui_blocks
        }
        raise ValueError("required analysis fields are missing: " + ", ".join(labels.get(path, path) for path in missing))
    if analysis.unresolved_constraints:
        raise ValueError("unresolved constraints must be resolved before execution: " + "; ".join(analysis.unresolved_constraints))
    if plan.infeasible:
        raise ValueError(
            "검색할 수 없는 조건을 먼저 해결해 주세요: "
            + "; ".join(item.reason for item in plan.infeasible)
        )
    for metric in [analysis.metric, *analysis.metrics]:
        if metric and metric.kind == "ratio" and (not metric.numerator or not metric.denominator):
            raise ValueError("ratio metric requires numerator and denominator")
    if analysis.comparison == "event_vs_event" and len(analysis.event_types) < 2:
        raise ValueError("이벤트 비교에는 두 개 이상의 이벤트가 필요합니다.")
    validate_choice_values(analysis, plan.ui_blocks)
    return analysis


def validate_editable_analysis_plan(
    authoritative: AnalysisPlan,
    candidate: AnalysisPlan,
    ui_blocks: list[UiBlock],
) -> None:
    """원본과 수정 계획을 비교해 서버가 허용한 편집 필드 밖의 변경이나 상위 객체 삭제를 거부한다."""

    allowed = {block.field_path for block in ui_blocks if block.field_path}
    allowed.add("field_metadata")
    if "metric.kind" in allowed and candidate.metric and candidate.metric.kind == "count":
        allowed.add("metric.distinct")  # MetricSpec derives this from count semantics.
    if "date_range" in allowed:
        allowed.add("date_anchor")
    before = authoritative.model_dump(mode="json")
    after = candidate.model_dump(mode="json")
    forbidden = [
        path
        for path in _changed_paths(before, after)
        if not _path_is_allowed(path, allowed)
    ]
    if forbidden:
        raise ValueError("analysis plan contains changes outside editable fields: " + ", ".join(forbidden))


def _changed_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    """딕셔너리와 목록을 재귀 비교해 추가·삭제·값 변경이 발생한 필드 경로를 반환한다."""

    if before is None and isinstance(after, dict):
        before = {}
    if isinstance(before, dict) and isinstance(after, dict):
        paths: list[str] = []
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_changed_paths(before.get(key), after.get(key), path))
        return paths
    if isinstance(before, list) and isinstance(after, list):
        paths = []
        for index in range(max(len(before), len(after))):
            path = f"{prefix}.{index}"
            left = before[index] if index < len(before) else None
            right = after[index] if index < len(after) else None
            paths.extend(_changed_paths(left, right, path))
        return paths
    return [] if before == after else [prefix]


def _path_is_allowed(path: str, allowed: set[str]) -> bool:
    """인덱스 표기를 통일하고 변경 경로가 편집 허용 경로 또는 그 하위 경로인지 판단한다."""

    normalized_path = re.sub(r"\.(\d+)(?=\.|$)", r"[\1]", path)
    for editable in allowed:
        normalized_editable = re.sub(r"\.(\d+)(?=\.|$)", r"[\1]", editable)
        if (
            normalized_path == normalized_editable
            # 편집 허용 필드 안의 하위 경로 변경은 허용한다.
            # 예: metric 편집이 허용되면 metric.kind도 변경할 수 있다.
            or normalized_path.startswith(normalized_editable + ".")
            or normalized_path.startswith(normalized_editable + "[")

        ):
            return True
    return False


def validate_choice_values(plan: AnalysisPlan, ui_blocks: list[UiBlock]) -> None:
    """선택형 UI의 현재 값이 서버가 제공한 선택지에 포함되는지 검사한다."""

    for block in ui_blocks:
        if not condition_matches(block.visible_if, plan):
            continue
        if block.type not in {"select", "option_cards", "multi_select", "choice"} or not block.options:
            continue
        path = block.field_path or block.key
        current = value_at_path(plan.model_dump(mode="json"), path)
        if current in (None, "", []):
            continue
        allowed = {option.value for option in block.options}
        values = current if isinstance(current, list) else [current]
        invalid = [str(value) for value in values if str(value) not in allowed]
        if invalid:
            raise ValueError(f"{block.label or path} contains values outside the server-issued options: {', '.join(invalid)}")


def normalize_metric_dependencies(before: AnalysisPlan, candidate: AnalysisPlan, catalog: dict) -> AnalysisPlan:
    """Derive only metric-dependent values; preserve genuine additional metrics and scope."""
    from app.planning.analysis_models import MetricSpec
    updated = candidate.model_copy(deep=True)
    old, metric = before.metric, updated.metric
    if metric is None:
        if old:
            updated.metrics = [m for m in updated.metrics if m != old]
        return updated
    definitions = catalog.get('semantic_metrics', {})
    changed_kind = bool(old and old.kind != metric.kind)
    if metric.kind == 'ratio':
        definition = definitions.get(metric.semantic_id)
        if definition is None:
            matches = [(key,d) for key,d in definitions.items()
                       if (metric.unit == d['label'] or (metric.numerator == d['numerator'] and metric.denominator == d['denominator'])
                           or (changed_kind and len(definitions) == 1))]
            if len(matches) == 1:
                metric.semantic_id, definition = matches[0]
        if definition:
            semantic_changed = bool(old and old != candidate.metric and old.semantic_id != candidate.metric.semantic_id)
            if not changed_kind and not semantic_changed:
                for key in ('field','numerator','denominator'):
                    if getattr(metric,key) not in (None,definition[key]):
                        raise ValueError(f'{definition["label"]}: {key} 정의가 Catalog와 다릅니다.')
            if (changed_kind or semantic_changed) and updated.event_types == before.event_types == [definition['numerator_event']]:
                updated.event_types = list(definition['population_events'])
            metric = MetricSpec(kind='ratio', semantic_id=metric.semantic_id, field=definition['field'],
                                numerator=definition['numerator'],denominator=definition['denominator'],
                                unit=definition['label'],distinct=True,minimum_sample_size=metric.minimum_sample_size)
    elif metric.kind == 'count':
        if changed_kind:
            metric.semantic_id = metric.numerator = metric.denominator = None
        if metric.field and (not old or old.field != metric.field or changed_kind):
            labels = {'order_id':'order','customer_id':'customer','product_id':'product','item_id':'item',
                      'courier_id':'courier','employee_id':'employee','package_id':'package','event_id':'event'}
            metric.unit = labels.get(metric.field, metric.unit)
        metric.distinct = True
    elif changed_kind:
        metric.semantic_id = metric.numerator = metric.denominator = None
        metric.distinct = None
        if metric.kind == 'rows':
            metric.field = metric.unit = None
        elif metric.field not in {o['value'] for o in catalog.get('numeric_fields',[])}:
            metric.field = None
            metric.unit = None
    updated.metric = metric
    # Replace only the old headline's duplicate. Independent metrics are never discarded.
    if old:
        updated.metrics = [metric.model_copy(deep=True) if m == old else m for m in updated.metrics]
    return AnalysisPlan.model_validate(updated.model_dump(mode='json'))


def validate_dynamic_semantics(plan: AnalysisPlan, catalog: dict, *, allow_incomplete: bool = False) -> None:
    """Validate a dynamic plan against server-issued schema and semantic metric definitions."""
    groups = {o['value'] for o in catalog.get('group_by',[])}
    columns = {c for fields in catalog.get('schema',{}).values() for c in fields}
    numeric = {o['value'] for o in catalog.get('numeric_fields',[])}
    kinds = {o['value'] for o in catalog.get('metric_kinds',[])}
    events = {o['value'] for o in catalog.get('event_types',[])}
    if set(plan.group_by) - groups:
        raise ValueError('지원되지 않는 집계 기준: ' + ', '.join(set(plan.group_by)-groups))
    if set(plan.event_types) - events:
        raise ValueError('스키마에서 확인되지 않은 이벤트: ' + ', '.join(set(plan.event_types)-events))
    for metric in [plan.metric,*plan.metrics]:
        if not metric: continue
        if metric.kind not in kinds:
            raise ValueError(f'현재 스키마에서 분석할 수 없는 지표: {metric.kind}')
        if metric.field and metric.field not in columns:
            raise ValueError(f'스키마에 없는 집계 필드: {metric.field}')
        if metric.kind == 'count':
            units = {'order_id':{'order','orders','order_id','주문'},'customer_id':{'customer','customers','customer_id','고객'},'courier_id':{'courier','couriers','courier_id','배송 기사','배달원'},'item_id':{'item','items','item_id','물품'},'product_id':{'product','products','product_id','상품'},'event_id':{'event','events','event_id','이벤트'}}
            if metric.unit and metric.field in units and metric.unit not in units[metric.field]:
                raise ValueError('건수 단위와 중복 제거 대상이 일치하지 않습니다.')
            if not metric.field and not allow_incomplete:
                raise ValueError('중복 제거 기준을 선택해 주세요.')
            if metric.field and metric.field not in {o['value'] for o in catalog.get('count_fields',[])}:
                raise ValueError('건수 지표에는 검증된 식별자 필드가 필요합니다.')
            if metric.distinct is not True:
                raise ValueError('대상 건수는 중복을 제거해야 합니다.')
        if metric.kind in {'sum','avg','min','max'}:
            if re.search(r'(배송|배달).*시간|delivery.*(time|duration)|duration', metric.unit or '', re.I):
                raise ValueError('평균 배송 시간은 검증된 기간 계산 정의와 시간 관계가 필요합니다.')
            if metric.field not in numeric and not (allow_incomplete and not metric.field):
                raise ValueError('수치 집계에는 스키마에서 확인된 수치 필드가 필요합니다.')
        if metric.kind == 'ratio':
            definition = catalog.get('semantic_metrics',{}).get(metric.semantic_id)
            if not definition:
                raise ValueError('검증된 Semantic Metric 정의를 선택해 주세요.')
            for key in ('field','numerator','denominator'):
                if getattr(metric,key) != definition[key]:
                    raise ValueError(f'{definition["label"]}: {key} 정의가 일치하지 않습니다.')
            if set(plan.group_by) - set(definition.get('group_by',[])):
                raise ValueError(f'{definition["label"]}에서 지원하지 않는 집계 기준입니다.')
            # A ratio population must not be narrowed to its numerator event.
            if not definition.get('population') and plan.event_types and set(plan.event_types) != set(definition['population_events']):
                raise ValueError('비율의 분모 모집단을 단일 이벤트로 제한할 수 없습니다.')
    for item in plan.filters:
        if item.field not in columns:
            raise ValueError('스키마에 없는 필터 필드: '+item.field)
    if plan.relationship_scope:
        from app.execution.analysis_semantics import allowed_relationship_scopes
        if plan.relationship_scope not in allowed_relationship_scopes():
            raise ValueError('검증되지 않은 엔터티 연결 관계입니다: '+plan.relationship_scope)


def apply_plan_update(original: AnalysisPlan, candidate: AnalysisPlan, blocks: list[UiBlock],
                      catalog: dict | None = None) -> AnalysisPlan:
    """Shared, transactional edit path for UI and structured chat patches (no SQL)."""
    if not catalog:
        updated = normalize_metric_dependencies(original,candidate,{})
        # Existing UIs keep their issued permissions; permit only exact derived mirrors/labels.
    else:
        updated = normalize_metric_dependencies(original,candidate,catalog)
    paths = {b.field_path for b in blocks if b.field_path} | {'field_metadata'}
    if 'date_range' in paths: paths.add('date_anchor')
    raw = candidate.model_dump(mode='json')
    initial = original.model_dump(mode='json')
    # Project requested writable changes onto the original, then derive dependencies.
    projected = original.model_dump(mode='json')
    changes = _changed_paths(initial,raw)
    for issued in sorted(paths,key=len):
        if any(_path_is_allowed(path,{issued}) for path in changes):
            set_plan_path(projected,issued,value_at_path(raw,issued))
    if 'metric.kind' in paths and candidate.metric is None:
        projected['metric'] = None
    projected = normalize_metric_dependencies(original,AnalysisPlan.model_validate(projected),catalog or {})
    expected = projected.model_dump(mode='json')
    forbidden = [path for path in _changed_paths(initial,raw)
                 if not _path_is_allowed(path,paths) and value_at_path(raw,path) != value_at_path(expected,path)]
    if forbidden:
        raise ValueError('analysis plan contains changes outside editable fields: '+', '.join(forbidden))
    if not catalog:
        validate_choice_values(updated,blocks)
    else:
        stable = [b for b in blocks if b.field_path not in {"metric.field","metric.numerator","metric.denominator","metric.semantic_id","group_by"} and not (b.field_path == "event_types" and original.metric != updated.metric)]
        validate_choice_values(updated,stable)
    if catalog:
        from app.planning.option_catalog import build_plan_option_catalog, catalog_snapshot
        schema_text = '\n'.join(f"{name}({', '.join(f'{c} {t}' for c,t in fields.items())})" for name,fields in catalog['schema'].items())
        refreshed = catalog_snapshot(build_plan_option_catalog(schema_text,updated))
        # Signatures don't contain event profiles; preserve server-verified event values.
        refreshed['event_types'] = catalog['event_types']
        validate_dynamic_semantics(updated,refreshed,allow_incomplete=True)
    if catalog:
        from app.execution.confirmed_context import resolve_plan_temporal_preview
        updated = resolve_plan_temporal_preview(updated)
    return updated


def set_plan_path(data: dict, path: str, value: Any) -> None:
    """Set a declared plan path without inventing arbitrary array members."""
    parts = re.sub(r'\[(\d+)\]',r'.\1',path).split('.')
    current = data
    for index, part in enumerate(parts[:-1]):
        if isinstance(current,list):
            current = current[int(part)]
        elif isinstance(current,dict):
            if current.get(part) is None:
                current[part] = [] if parts[index+1].isdigit() else {}
            current = current[part]
        else: raise ValueError('수정 경로의 상위 값이 올바르지 않습니다.')
    if isinstance(current,list): current[int(parts[-1])] = value
    elif isinstance(current,dict): current[parts[-1]] = value
    else: raise ValueError('수정할 조건을 찾을 수 없습니다.')


def refresh_dynamic_plan(ui_plan: UiPlan) -> UiPlan:
    """Reissue dependent options from the trusted catalog, retaining blueprint layout/text."""
    catalog = ui_plan.ui_state.get('semantic_catalog')
    if not catalog: return ui_plan
    from app.planning.option_catalog import build_plan_option_catalog, catalog_snapshot
    from app.planning.planner.controls import _hydrate_block_options
    schema_text = '\n'.join(f"{name}({', '.join(f'{c} {t}' for c,t in fields.items())})" for name,fields in catalog['schema'].items())
    fresh = build_plan_option_catalog(schema_text,ui_plan.analysis_plan)
    from app.planning.ui_models import UiOption
    fresh.event_types[:] = [UiOption.model_validate(o) for o in catalog['event_types']]
    dependent = {'metric.field','metric.numerator','metric.denominator','metric.semantic_id','group_by'}
    ui_plan.ui_blocks = [_hydrate_block_options(b.model_copy(update={'options':[]}) if b.field_path in dependent else b,fresh) for b in ui_plan.ui_blocks]
    ui_plan.ui_state['semantic_catalog'] = catalog_snapshot(fresh)
    validate_dynamic_semantics(ui_plan.analysis_plan,ui_plan.ui_state['semantic_catalog'],allow_incomplete=True)
    ui_plan.missing_fields = compute_missing_fields(ui_plan.analysis_plan,ui_plan.ui_blocks)
    return ui_plan
