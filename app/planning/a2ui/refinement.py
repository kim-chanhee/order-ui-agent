"""A2UI 전용 자연어 추가 조건을 제한된 필터 수정 패치로 반영한다.

주요 기능:
    - 기존 계획·안정적인 필터 ID·스키마·추가 조건을 LLM에 전달한다.
    - 필터 추가·삭제와 미해결 조건만 반영하고 다른 분석 의미는 보존한다.
    - 이전 응답 형식도 수정 패치로 변환해 처리한다.
    - 해석 실패 시 원래 계획을 유지하고 추가 확인이 필요한 조건을 기록한다.
"""

from __future__ import annotations

import json
from typing import Any

from app.planning.analysis_models import AnalysisPlan
from app.planning.a2ui.models import RefinementPatch
from app.planning.planner.dynamic_planner import _planner_llm, planner_enabled
from app.planning.schema_context import PlannerSchemaContext, build_planner_schema_context
from app.planning.ui_models import DynamicPlannerOutput, UiBlock
from app.planning.validator import compute_missing_fields


def refine_dynamic_analysis(
    question: str,
    plan: AnalysisPlan,
    ui_blocks: list[UiBlock],
    additional_constraint: str,
    *,
    schema_context: PlannerSchemaContext | None = None,
    llm: Any | None = None,
) -> DynamicPlannerOutput:
    """추가 조건을 제한된 수정 패치로 생성해 기존 계획에 병합하고 실패 시 미해결 조건으로 남긴다."""

    context = schema_context or build_planner_schema_context(f"{question}\n{additional_constraint}")
    if not planner_enabled() and llm is None:
        return _unresolved_refinement(plan, ui_blocks, additional_constraint)
    model = llm or _planner_llm()
    structured = model.with_structured_output(RefinementPatch, method="function_calling")
    prompt = _refinement_prompt(question, plan, ui_blocks, additional_constraint, context)
    try:
        result = structured.invoke(prompt)
        if isinstance(result, DynamicPlannerOutput):
            patch = _patch_from_legacy_output(plan, result)
        elif isinstance(result, dict) and "analysis_plan" in result:
            patch = _patch_from_legacy_output(plan, DynamicPlannerOutput.model_validate(result))
        else:
            patch = result if isinstance(result, RefinementPatch) else RefinementPatch.model_validate(result)
        return _merge_refinement_patch(plan, ui_blocks, patch, question=question)
    except Exception:
        return _unresolved_refinement(plan, ui_blocks, additional_constraint)


def _refinement_prompt(
    question: str,
    plan: AnalysisPlan,
    ui_blocks: list[UiBlock],
    additional_constraint: str,
    context: PlannerSchemaContext,
) -> str:
    """기존 계획·필터 ID·스키마·추가 조건을 묶어 허용된 수정 패치만 요청하는 프롬프트를 만든다."""

    return f"""
Refine the existing semantic analysis plan using the user's additional constraint. Return only a
RefinementPatch. You may add semantic filters, remove an existing filter by the supplied stable filter ID,
or append unresolved constraints. You may not change analysis_type, date_range, date_anchor, event_types,
target_conditions, metric, group_by, comparison, sort, limit, output, or execution_policy. Convert the new
text to semantic filters only when the bounded schema context supports it. Never invent a physical column.
If it cannot be safely structured, add a specific Korean explanation to unresolved_constraints. Never output
SQL, HTML, JavaScript, or a complete AnalysisPlan.

Question: {question}
Additional constraint: {additional_constraint}
Existing plan: {json.dumps(plan.model_dump(mode='json'), ensure_ascii=False)}
Existing filter IDs: {json.dumps([{'id': _filter_id(item), 'filter': item.model_dump(mode='json')} for item in plan.filters], ensure_ascii=False)}
Existing UI blocks: {json.dumps([block.model_dump(mode='json') for block in ui_blocks], ensure_ascii=False)}
Schema context: {context.text}
""".strip()


def _unresolved_refinement(plan: AnalysisPlan, ui_blocks: list[UiBlock], text: str) -> DynamicPlannerOutput:
    """해석하지 못한 추가 조건을 기존 계획의 미해결 항목으로 기록해 확인용 응답을 반환한다."""

    updated = plan.model_copy(deep=True)
    message = f"추가 조건 '{text}'의 구체적인 기준을 확인해야 합니다."
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
    import hashlib

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _patch_from_legacy_output(plan: AnalysisPlan, output: DynamicPlannerOutput) -> RefinementPatch:
    """이전 형식의 전체 계획 응답에서 새 필터와 미해결 조건만 추출해 제한된 수정 패치로 변환한다."""

    existing = {_filter_id(item) for item in plan.filters}
    additions = [item for item in output.analysis_plan.filters if _filter_id(item) not in existing]
    unresolved = [
        item
        for item in output.analysis_plan.unresolved_constraints
        if item not in plan.unresolved_constraints
    ]
    return RefinementPatch(
        add_filters=additions,
        unresolved_constraints=unresolved,
        summary=output.summary,
        warnings=output.warnings,
    )


def _merge_refinement_patch(
    plan: AnalysisPlan,
    ui_blocks: list[UiBlock],
    patch: RefinementPatch,
    *,
    question: str,
) -> DynamicPlannerOutput:
    """보호 필드를 유지하면서 필터 추가·삭제와 미해결 조건을 반영하고 계획을 다시 검증한다."""

    updated = plan.model_copy(deep=True)
    removals = set(patch.remove_filter_ids)
    updated.filters = [item for item in updated.filters if _filter_id(item) not in removals]
    known = {_filter_id(item) for item in updated.filters}
    for filter_spec in patch.add_filters:
        candidate = filter_spec.model_copy(update={"source": "user_additional_constraint"})
        identifier = _filter_id(candidate)
        if identifier not in known:
            updated.filters.append(candidate)
            known.add(identifier)
    updated.unresolved_constraints = list(dict.fromkeys([
        *updated.unresolved_constraints,
        *(item.strip() for item in patch.unresolved_constraints if item.strip()),
    ]))
    updated.original_question = question.strip()
    updated.source = "llm_dynamic_refinement"
    updated = AnalysisPlan.model_validate(updated.model_dump(mode="json"))
    return DynamicPlannerOutput(
        analysis_plan=updated,
        ui_blocks=ui_blocks,
        missing_fields=compute_missing_fields(updated, ui_blocks),
        field_metadata=updated.field_metadata,
        summary=patch.summary or "추가 조건을 분석 계획에 반영했습니다.",
        warnings=patch.warnings,
    )
