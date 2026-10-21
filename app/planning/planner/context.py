"""후속 분석의 참조 후보 선택·조건 상속·식별자 필터 근거를 처리한다."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.planning.analysis_models import AnalysisPlan, ContextReferenceSpec, FieldMetadata, FilterSpec
from app.planning.planner.models import ContextField, PlannerContextCandidate, PlannerContextResolution
from app.planning.ui_models import DynamicPlannerOutput


def _inherit_followup_scope(
    output: DynamicPlannerOutput,
    context_candidates: list[PlannerContextCandidate],
    resolution: PlannerContextResolution,
) -> tuple[DynamicPlannerOutput, list[str]]:
    """후속 질문이 선택한 이전 분석의 생략된 조건을 상속하고 출처와 참조 정보를 기록한다."""

    if not resolution.is_followup:
        output.analysis_plan.context_reference = None
        return output, []
    candidate = _selected_context_candidate(context_candidates, resolution)
    previous_plan = candidate.analysis_plan
    plan = output.analysis_plan
    plan.context_reference = ContextReferenceSpec(
        scope_id=candidate.context_id,
        source_question=candidate.question,
        evidence=resolution.reference_evidence,
        confidence=resolution.confidence,
        needs_confirmation=resolution.needs_confirmation,
    )
    plan.filters = _ground_followup_identifier_filters(plan, candidate)
    inherited: list[str] = []
    requested = set(resolution.inherit_fields) - set(resolution.override_fields)

    if (
        "date_range" in requested
        and previous_plan.date_range is not None
        and not _field_is_explicit(plan, "date_range", resolution)
    ):
        plan.date_range = previous_plan.date_range.model_copy(deep=True)
        plan.date_anchor = previous_plan.date_anchor.model_copy(deep=True) if previous_plan.date_anchor else None
        plan.field_metadata["date_range"] = FieldMetadata(
            status="inferred", confidence=1.0, source="inherited_context",
            label="조회 기간", description="같은 스레드의 이전 질문에서 유지한 기간입니다.",
        )
        inherited.append("date_range")

    if (
        "target_conditions" in requested
        and not plan.target_conditions
        and previous_plan.target_conditions
        and not _field_is_explicit(plan, "target_conditions", resolution)
    ):
        plan.target_conditions = list(previous_plan.target_conditions)
        plan.field_metadata["target_conditions"] = FieldMetadata(
            status="inferred", confidence=0.95, source="inherited_context",
            label="대상 조건", description="같은 스레드의 이전 질문에서 유지한 대상입니다.",
        )
        inherited.append("target_conditions")

    if (
        "filters" in requested
        and not plan.filters
        and previous_plan.filters
        and not _field_is_explicit(plan, "filters", resolution)
    ):
        plan.filters = [item.model_copy(deep=True, update={"source": "inherited_context"}) for item in previous_plan.filters]
        plan.field_metadata["filters"] = FieldMetadata(
            status="inferred", confidence=0.95, source="inherited_context",
            label="필터", description="같은 스레드의 이전 질문에서 유지한 필터입니다.",
        )
        inherited.append("filters")

    if (
        "event_types" in requested
        and not plan.event_types
        and previous_plan.event_types
        and not _field_is_explicit(plan, "event_types", resolution)
    ):
        plan.event_types = list(previous_plan.event_types)
        plan.field_metadata["event_types"] = FieldMetadata(
            status="inferred", confidence=0.95, source="inherited_context",
            label="대상 이벤트", description="같은 스레드의 이전 질문에서 유지한 이벤트입니다.",
        )
        inherited.append("event_types")

    if (
        "target_entity" in requested
        and plan.target_entity is None
        and previous_plan.target_entity is not None
        and not _field_is_explicit(plan, "target_entity", resolution)
    ):
        plan.target_entity = previous_plan.target_entity
        plan.field_metadata["target_entity"] = FieldMetadata(
            status="inferred", confidence=0.95, source="inherited_context",
            label="결과 대상", description="같은 스레드의 이전 질문에서 유지한 결과 대상입니다.",
        )
        inherited.append("target_entity")

    if (
        "requested_attributes" in requested
        and not plan.requested_attributes
        and previous_plan.requested_attributes
        and not _field_is_explicit(plan, "requested_attributes", resolution)
    ):
        plan.requested_attributes = list(previous_plan.requested_attributes)
        plan.field_metadata["requested_attributes"] = FieldMetadata(
            status="inferred", confidence=0.95, source="inherited_context",
            label="요청 속성", description="같은 스레드의 이전 질문에서 유지한 출력 속성입니다.",
        )
        inherited.append("requested_attributes")

    if (
        "result_grain" in requested
        and plan.result_grain is None
        and previous_plan.result_grain is not None
        and not _field_is_explicit(plan, "result_grain", resolution)
    ):
        plan.result_grain = previous_plan.result_grain
        plan.field_metadata["result_grain"] = FieldMetadata(
            status="inferred", confidence=0.95, source="inherited_context",
            label="결과 단위", description="같은 스레드의 이전 질문에서 유지한 결과 행 단위입니다.",
        )
        inherited.append("result_grain")

    if (
        "relationship_scope" in requested
        and plan.relationship_scope is None
        and previous_plan.relationship_scope is not None
        and not _field_is_explicit(plan, "relationship_scope", resolution)
    ):
        plan.relationship_scope = previous_plan.relationship_scope
        plan.field_metadata["relationship_scope"] = FieldMetadata(
            status="inferred", confidence=0.95, source="inherited_context",
            label="관계 범위", description="같은 스레드의 이전 질문에서 유지한 엔터티 관계입니다.",
        )
        inherited.append("relationship_scope")

    if (
        "excluded_attributes" in requested
        and not plan.excluded_attributes
        and previous_plan.excluded_attributes
        and not _field_is_explicit(plan, "excluded_attributes", resolution)
    ):
        plan.excluded_attributes = list(previous_plan.excluded_attributes)
        plan.field_metadata["excluded_attributes"] = FieldMetadata(
            status="inferred", confidence=0.95, source="inherited_context",
            label="제외 속성", description="같은 스레드의 이전 질문에서 유지한 제외 속성입니다.",
        )
        inherited.append("excluded_attributes")

    output.analysis_plan = plan
    return output, inherited


def _ground_followup_identifier_filters(
    plan: AnalysisPlan,
    candidate: PlannerContextCandidate,
) -> list[FilterSpec]:
    """사용자가 명시하지 않았고 질문·이전 결과에도 근거가 없는 추정 ID 필터를 제거한다."""

    grounded = plan.original_question.casefold()
    grounded_values = {
        str(value).casefold()
        for values in candidate.identity_values.values()
        for value in values
    }
    for row in candidate.rows:
        grounded_values.update(str(value).casefold() for value in row.values() if value is not None)

    kept: list[FilterSpec] = []
    for item in plan.filters:
        field = item.field.strip().casefold()
        metadata = plan.field_metadata.get(item.field) or plan.field_metadata.get("filters")
        explicitly_grounded = bool(
            item.source in {"user_text", "user_selected", "user_additional_constraint"}
            or (metadata and metadata.status in {"explicit", "user_modified"})
        )
        values = item.value if isinstance(item.value, list) else [item.value]
        candidate_ids = [str(value).strip().casefold() for value in values if value is not None]
        is_identifier_filter = field == "id" or field.endswith("_id") or field.endswith("_ids")
        has_evidence = all(value in grounded or value in grounded_values for value in candidate_ids)
        if is_identifier_filter and candidate_ids and not explicitly_grounded and not has_evidence:
            continue
        kept.append(item)
    return kept


def _normalize_context_candidates(
    previous_plan: AnalysisPlan | None,
    context_candidates: list[PlannerContextCandidate] | None,
) -> list[PlannerContextCandidate]:
    """분석 후보를 깊은 복사로 정리하고 후보가 없으면 이전 계획을 단일 후보로 변환한다."""

    if context_candidates:
        return [candidate.model_copy(deep=True) for candidate in context_candidates]
    if previous_plan is None:
        return []
    return [
        PlannerContextCandidate(
            context_id="previous_context",
            question=previous_plan.original_question,
            analysis_plan=previous_plan.model_copy(deep=True),
        )
    ]


def _selected_context_candidate(
    candidates: list[PlannerContextCandidate],
    resolution: PlannerContextResolution,
) -> PlannerContextCandidate:
    """선택된 ID의 이전 분석 후보를 반환하고 후보가 없거나 참조가 일치하지 않으면 오류를 발생시킨다."""

    if not candidates:
        raise ValueError("follow-up context was requested but no prior analysis scopes are available")
    selected_id = resolution.selected_context_id
    if selected_id is None and len(candidates) == 1:
        return candidates[0]
    for candidate in candidates:
        if candidate.context_id == selected_id:
            return candidate
    raise ValueError("follow-up context must select exactly one supplied context_id")


def _context_resolution_from_result(result: Any) -> PlannerContextResolution:
    """LLM 응답에서 후속 질문의 참조·상속 결정을 추출해 모델로 검증한다."""

    if isinstance(result, BaseModel):
        payload = result.model_dump(mode="json", exclude_none=True)
    elif isinstance(result, dict):
        payload = result
    else:
        raise TypeError("planner response must be an object")
    return PlannerContextResolution.model_validate(payload.get("context_resolution") or {})


def _field_is_explicit(
    plan: AnalysisPlan,
    field: ContextField,
    resolution: PlannerContextResolution,
) -> bool:
    """덮어쓰기 결정이나 메타데이터를 확인해 현재 질문에서 명시적으로 정한 필드인지 판단한다."""

    if field in resolution.override_fields:
        return True
    metadata = plan.field_metadata.get(field)
    if metadata is None:
        return False
    return metadata.source in {"user_text", "user_selected"} or metadata.status in {"explicit", "user_modified"}


def _inherited_field_label(field: str) -> str:
    """상속한 계획 필드 이름을 안내 메시지에 사용할 한국어 이름으로 변환한다."""

    return {
        "date_range": "기간",
        "target_conditions": "대상",
        "filters": "필터",
        "event_types": "이벤트",
        "target_entity": "결과 대상",
        "requested_attributes": "요청 속성",
        "result_grain": "결과 단위",
        "relationship_scope": "관계 범위",
        "excluded_attributes": "제외 속성",
    }.get(field, field)
