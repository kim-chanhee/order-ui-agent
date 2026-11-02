"""자연어 요청을 서버 발급 편집 경로와 선택지로 검증한 수정 패치로 반영한다."""

from __future__ import annotations
from app.core.llm_usage import track_llm_request


from app.core.llm_settings import structured_output_options

import hashlib
import json
from typing import Any
from app.core.model_errors import invoke_with_retry, quota_exhausted

from app.planning.analysis_models import AnalysisPlan
from app.planning.a2ui.validator import apply_plan_update, set_plan_path
from app.planning.a2ui.models import RefinementPatch
from app.planning.planner.dynamic_planner import _planner_llm, planner_enabled
from app.planning.schema_context import PlannerSchemaContext, build_planner_schema_context
from app.planning.ui_models import DynamicPlannerOutput, UiBlock
from app.planning.validator import compute_missing_fields
from app.planning.option_catalog import build_plan_option_catalog, catalog_snapshot


@track_llm_request
def refine_dynamic_analysis(
    question: str,
    plan: AnalysisPlan,
    ui_blocks: list[UiBlock],
    additional_constraint: str,
    *,
    schema_context: PlannerSchemaContext | None = None,
    llm: Any | None = None,
    catalog: dict | None = None,
) -> DynamicPlannerOutput:
    """추가 조건을 제한된 수정 패치로 생성해 기존 계획에 병합하고 실패 시 미해결 조건으로 남긴다."""

    context = schema_context or build_planner_schema_context(f"{question}\n{additional_constraint}")
    if not planner_enabled() and llm is None:
        return _unresolved_refinement(plan, ui_blocks, additional_constraint)
    model = llm or _planner_llm()
    structured = model.with_structured_output(RefinementPatch, **structured_output_options())
    prompt = _refinement_prompt(question, plan, ui_blocks, additional_constraint, context, catalog=catalog)
    try:
        result = invoke_with_retry(structured,prompt)
        patch = result if isinstance(result, RefinementPatch) else RefinementPatch.model_validate(result)
        return _merge_refinement_patch(plan, ui_blocks, patch, question=question, catalog=catalog, schema_context=context)
    except Exception as exc:
        if quota_exhausted(exc) or not isinstance(exc, ValueError):
            raise RuntimeError('분석 조건 수정 중 모델 연결 오류가 발생했습니다. 기존 계획은 유지됩니다.') from exc
        return _unresolved_refinement(plan, ui_blocks, additional_constraint, reason=str(exc) if isinstance(exc, ValueError) else None)


def _refinement_prompt(
    question: str,
    plan: AnalysisPlan,
    ui_blocks: list[UiBlock],
    additional_constraint: str,
    context: PlannerSchemaContext,
    *,
    catalog: dict | None = None,
) -> str:
    """기존 계획·필터 ID·스키마·추가 조건을 묶어 허용된 수정 패치만 요청하는 프롬프트를 만든다."""

    return f"""
Refine the existing semantic analysis plan using the user's additional constraint. Return only a
RefinementPatch. Use updates to change declared editable AnalysisPlan paths, including a hidden field when the schema supports it, and only when
explicitly requested by the user. Use server-issued option values exactly, never display labels.
For a period change replace date_range as a whole (e.g. {{"mode":"relative","relative_days":30}}).
Do not turn a period, grouping, metric or limit change into a filter. Preserve unrelated fields.
You may add semantic filters supported by the schema, or remove a filter using its supplied stable ID.
You may resolve an existing constraint beginning with "추가 조건 '" only if this request actually resolves
that issue. Other unresolved conditions must remain. Unknown or unsupported requests must be reported in
unresolved_constraints. Never emit SQL, HTML, JavaScript, a complete AnalysisPlan or execution_policy.
Preserve the existing blueprint for simple changes. For a metric/dependency change you may propose ui_blocks
as a complete replacement blueprint from the component catalog, never a fixed default set. Use only grounded
semantic metric definitions; do not invent ratio populations or elapsed-time measures.

Question: {question}
Additional constraint: {additional_constraint}
Existing plan: {json.dumps(plan.model_dump(mode='json'), ensure_ascii=False)}
Existing filter IDs: {json.dumps([{'id': _filter_id(item), 'filter': item.model_dump(mode='json')} for item in plan.filters], ensure_ascii=False)}
Existing UI blocks: {json.dumps([block.model_dump(mode='json') for block in ui_blocks], ensure_ascii=False)}
Schema context: {context.text}
Authoritative semantic and component choices: {json.dumps(catalog or catalog_snapshot(build_plan_option_catalog(context.text, plan)), ensure_ascii=False)}
All selected values belong only in updates to AnalysisPlan. Never put default/defaultValue/selected
in ui_blocks, props or options. Use registered component types, not field names as types.
""".strip()


def _unresolved_refinement(plan: AnalysisPlan, ui_blocks: list[UiBlock], text: str, reason: str | None = None) -> DynamicPlannerOutput:
    """해석하지 못한 추가 조건을 기존 계획의 미해결 항목으로 기록해 확인용 응답을 반환한다."""

    updated = plan.model_copy(deep=True)
    message = f"추가 조건 '{text}'의 구체적인 기준을 확인해야 합니다."
    if reason:
        message += " " + reason[:400]
    if message not in updated.unresolved_constraints:
        updated.unresolved_constraints.append(message)
    return DynamicPlannerOutput(
        analysis_plan=updated,
        ui_blocks=ui_blocks,
        missing_fields=compute_missing_fields(updated, ui_blocks),
        field_metadata=updated.field_metadata,
        summary="추가 조건을 더 구체적으로 지정해 주세요.",
        warnings=[message],
    )


def _filter_id(filter_spec: Any) -> str:
    """필터 출처를 제외한 내용을 정렬해 해시하고 필터 비교·삭제에 쓸 안정적인 ID를 만든다."""

    payload = filter_spec.model_dump(mode="json") if hasattr(filter_spec, "model_dump") else filter_spec
    payload = dict(payload)
    payload.pop("source", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _merge_refinement_patch(
    plan: AnalysisPlan,
    ui_blocks: list[UiBlock],
    patch: RefinementPatch,
    *,
    question: str,
    catalog: dict | None = None,
    schema_context: PlannerSchemaContext | None = None,
) -> DynamicPlannerOutput:
    """보호 필드를 유지하면서 필터 추가·삭제와 미해결 조건을 반영하고 계획을 다시 검증한다."""

    data = plan.model_dump(mode="json")
    for change in patch.updates:
        _set_path(data, change.path, change.value)
    if any(change.path == "date_range" or change.path.startswith("date_range.") for change in patch.updates):
        mode = (data.get("date_range") or {}).get("mode")
        data["date_anchor"] = {"strategy": "dataset_max"} if mode in {"relative", "preset"} else None
    updated = AnalysisPlan.model_validate(data)
    editable_blocks = list(ui_blocks)
    if catalog:
        # Chat patches may change a valid hidden field; direct UI payloads may not.
        from app.planning.ui_models import UiOption
        issued = {b.field_path for b in editable_blocks}
        for change in patch.updates:
            if change.path not in issued:
                editable_blocks.append(UiBlock(type='text',key='patch_'+str(len(editable_blocks)),field_path=change.path,label=change.path))
    updated = apply_plan_update(plan, updated, editable_blocks, catalog)
    removals = set(patch.remove_filter_ids)
    existing = {_filter_id(item) for item in updated.filters}
    if not removals <= existing:
        raise ValueError("삭제할 필터를 찾을 수 없습니다.")
    updated.filters = [item for item in updated.filters if _filter_id(item) not in removals]
    known = {_filter_id(item) for item in updated.filters}
    for filter_spec in patch.add_filters:
        candidate = filter_spec.model_copy(update={"source": "user_additional_constraint"})
        identifier = _filter_id(candidate)
        if identifier not in known:
            updated.filters.append(candidate)
            known.add(identifier)
    resolved = set(patch.resolve_constraints)
    resolvable = {item for item in plan.unresolved_constraints if item.startswith("추가 조건 '")}
    if not resolved <= resolvable:
        raise ValueError("기존의 미해결 추가 조건만 해제할 수 있습니다.")
    updated.unresolved_constraints = list(dict.fromkeys([
        *(item for item in updated.unresolved_constraints if item not in resolved),
        *(item.strip() for item in patch.unresolved_constraints if item.strip()),
    ]))
    updated.original_question = question.strip()
    updated.source = "llm_dynamic_refinement"
    updated = AnalysisPlan.model_validate(updated.model_dump(mode="json"))
    output = DynamicPlannerOutput(
        analysis_plan=updated,
        ui_blocks=patch.ui_blocks if patch.ui_blocks is not None else ui_blocks,
        missing_fields=compute_missing_fields(updated, ui_blocks),
        field_metadata=updated.field_metadata,
        summary=patch.summary or "추가 조건을 분석 계획에 반영했습니다.",
        warnings=patch.warnings,
    )
    if catalog and schema_context:
        from app.planning.planner.controls import _ensure_plan_controls
        return _ensure_plan_controls(output, schema_context)
    return output


def _set_path(data: dict, path: str, value: Any) -> None:
    """검증된 필드 경로에만 대입한다. 배열의 임의 확장이나 잘못된 부모 타입은 거부한다."""
    set_plan_path(data, path, value)
