"""검토용 UI의 선택지·기본 입력·중복·배치와 스키마 근거를 정리한다."""

from __future__ import annotations

from typing import Any

from app.planning.option_catalog import OUTPUT_VIEW_OPTIONS, build_plan_option_catalog, catalog_snapshot
from app.planning.schema_context import PlannerSchemaContext
from app.planning.ui_models import DynamicPlannerOutput, UiBlock, UiOption
from app.planning.validator import compute_missing_fields


_CHOICE_BLOCK_TYPES = {"select", "option_cards", "multi_select", "choice"}


_FIELD_PATH_PREFIX = "analysis_plan."


def _normalize_ui_blocks(blocks: list[UiBlock]) -> list[UiBlock]:
    """UI 경로 접두사를 정리하고 props에 들어간 선택지를 복구한 뒤 빈 선택형 블록을 보정한다."""

    normalized: list[UiBlock] = []
    for block in blocks:
        updates: dict[str, Any] = {}
        if block.field_path and block.field_path.startswith(_FIELD_PATH_PREFIX):
            updates["field_path"] = block.field_path[len(_FIELD_PATH_PREFIX):]
        target_path = updates.get("field_path", block.field_path) or block.key
        if block.type in _CHOICE_BLOCK_TYPES and not block.options:
            recovered = _options_from_props(block.props)
            if recovered:
                updates['options'] = recovered
        if updates:
            block = block.model_copy(update=updates)
        normalized.append(block)
    return normalized


def _options_from_props(props: dict[str, Any]) -> list[UiOption]:
    """props의 options 목록에서 유효한 값·이름·설명을 읽어 UiOption 목록으로 복구한다."""

    raw = props.get("options") if isinstance(props, dict) else None
    if not isinstance(raw, list):
        return []
    options: list[UiOption] = []
    for item in raw:
        if not isinstance(item, dict) or "value" not in item:
            continue
        try:
            options.append(
                UiOption(
                    value=str(item["value"]),
                    label=str(item.get("label") or item["value"]),
                    description=item.get("description"),
                )
            )
        except Exception:
            continue
    return options


def _ensure_plan_controls(
    output: DynamicPlannerOutput,
    schema_context: PlannerSchemaContext,
    *, include_ui: bool = True,
) -> DynamicPlannerOutput:
    """Validate the LLM blueprint; never inject a fixed set or reorder its blocks."""
    if not output.requires_confirmation or output.analysis_plan.source == 'safe_fallback':
        return output
    from app.planning.a2ui.validator import normalize_metric_dependencies, validate_dynamic_semantics, validate_choice_values
    plan = output.analysis_plan
    catalog = build_plan_option_catalog(schema_context.text, plan)
    plan = normalize_metric_dependencies(plan, plan, catalog_snapshot(catalog))
    output.analysis_plan = plan
    catalog = build_plan_option_catalog(schema_context.text, plan)
    snapshot = catalog_snapshot(catalog)
    validate_dynamic_semantics(plan, snapshot, allow_incomplete=True)
    if not include_ui:
        output.ui_blocks = []
        output.ui_state = {'semantic_catalog': snapshot}
        output.missing_fields = compute_missing_fields(plan, [])
        if plan.metric and plan.metric.kind in {'count','sum','avg','min','max'} and not plan.metric.field:
            output.missing_fields.append('metric.field')
        return output
    if not output.ui_blocks:
        raise ValueError('분석 목적에 필요한 UI Block을 하나 이상 제안해 주세요.')
    paths, keys = set(), set()
    blocks = []
    for block in output.ui_blocks:
        if block.key in keys or (block.field_path and block.field_path in paths):
            raise ValueError('UI Block key와 field_path는 중복될 수 없습니다.')
        keys.add(block.key)
        paths.add(block.field_path)
        blocks.append(_hydrate_block_options(block, catalog, metric_kind=plan.metric.kind if plan.metric else None))
    validate_choice_values(plan, blocks)
    if plan.metric and plan.metric.kind in {"count","sum","avg","min","max"} and not plan.metric.field and "metric.field" not in paths:
        raise ValueError("지표의 집계 대상이 없으면 metric.field 입력 Block이 필요합니다.")
    output.ui_blocks = blocks
    output.ui_state = {'dynamic_ui_version':1, 'semantic_catalog':snapshot}
    output.missing_fields = compute_missing_fields(plan, blocks)
    return output


def _hydrate_block_options(block: UiBlock, catalog: Any, *, metric_kind: str | None = None) -> UiBlock:
    """Keep the model's labels/order/section, but issue only grounded option values."""
    path = block.field_path or block.key
    available = None
    if path == 'event_types': available = catalog.event_types
    elif path == 'group_by': available = catalog.group_by
    elif path == 'metric.kind': available = catalog.metric_kinds
    elif path == 'metric.semantic_id':
        available = [UiOption(value=k,label=v['label'],description=v.get('description')) for k,v in catalog.semantic_metrics.items()
                     if metric_kind is None or v['kind'] == metric_kind]
    elif path == 'metric.field':
        available = catalog.count_fields if not catalog.numeric_fields else [*catalog.count_fields,*catalog.numeric_fields]
    elif path in {'metric.numerator','metric.denominator'}:
        key = path.split('.')[-1]
        available = [UiOption(value=v[key],label=v['label']+' '+('분자' if key=='numerator' else '분모')) for v in catalog.semantic_metrics.values()]
    elif path == 'comparison': available = catalog.comparisons
    elif path == 'output.view': available = OUTPUT_VIEW_OPTIONS
    elif path.endswith('.direction'):
        available = [UiOption(value='asc',label='오름차순'),UiOption(value='desc',label='내림차순')]
    elif path.endswith('.field') and path.startswith('sort'):
        available = [UiOption(value='metric',label='결과 지표'), *[UiOption(value=c,label=c) for fields in catalog.schema.values() for c in fields]]
    if available is not None:
        allowed = {option.value:option for option in available}
        invalid = [option.value for option in block.options if option.value not in allowed]
        if invalid:
            raise ValueError(f'{block.label}: 허용되지 않는 선택값 {invalid}')
        if block.type in _CHOICE_BLOCK_TYPES:
            # The model can curate a subset and write labels; it cannot expand the catalog.
            chosen = block.options or list(allowed.values())
            if not chosen: raise ValueError(f'{block.label}: 현재 스키마에서 지원하는 선택지가 없습니다.')
            return block.model_copy(update={'options':chosen})
    elif block.type in _CHOICE_BLOCK_TYPES:
        raise ValueError(f'{block.label}: {path} 필드의 선택지 검증 규칙이 Catalog에 없습니다. Use a supported scalar field_path such as metric.kind or output.view.')
    return block
