"""A2UI 전용 검토 화면 응답 조립과 추가 조건 반영을 담당한다.

주요 기능:
    - 확인 화면을 생성·저장하고 답변·계획·화면 데이터를 함께 반환한다.
    - 추가 조건의 중복을 확인하고 실제 필터가 바뀐 경우 조건 이력에 반영한다.
    - 수정 결과의 필수 입력과 조회 불가 사유를 현재 계획에 맞춰 갱신한다.
"""

from app.a2ui.review import review_answer, surface_for_plan
from app.planning.a2ui.refinement import refine_dynamic_analysis
from app.planning.ui_models import UiPlan
from app.planning.validator import compute_missing_fields
from app.routes.schemas import ChatRequest


def plan_response_parts(plan: UiPlan, payload: ChatRequest, thread_id: str) -> tuple[str, dict, dict]:
    """클라이언트 지원 컴포넌트로 확인 화면을 만들고 안내 답변·식별 정보가 포함된 계획·화면을 반환한다."""

    surface = surface_for_plan(
        plan,
        payload.supported_components,
        participant_id=payload.participant_id,
        thread_id=thread_id,
    )
    plan_payload = plan.model_dump(mode="json")
    plan_payload.update(
        surface_id=surface["surface_id"],
        plan_id=surface["plan_id"],
        revision=surface["revision"],
    )
    return review_answer(plan), plan_payload, surface


def refine_review_plan(
    plan: UiPlan,
    *,
    question: str,
    additional_constraint: str,
) -> UiPlan:
    """추가 조건의 중복을 확인하고 계획 수정 결과와 조건 이력·필수 입력·조회 불가 사유를 갱신한다."""

    constraint = " ".join(additional_constraint.split())
    prior_constraints = _normalized_constraints(plan.ui_state.get("additional_constraints", []))
    if constraint.casefold() in {item.casefold() for item in prior_constraints}:
        return UiPlan(
            summary="이미 적용된 추가 조건입니다.",
            analysis_plan=plan.analysis_plan.model_copy(deep=True),
            ui_state={**plan.ui_state, "additional_constraint": "", "additional_constraints": prior_constraints},
            ui_blocks=plan.ui_blocks,
            missing_fields=compute_missing_fields(plan.analysis_plan, plan.ui_blocks),
            suggested_constraints=plan.suggested_constraints,
            infeasible=_carry_infeasible(plan.infeasible, plan.analysis_plan.unresolved_constraints),
            warnings=plan.warnings,
        )
    output = refine_dynamic_analysis(
        question,
        plan.analysis_plan,
        plan.ui_blocks,
        constraint,
    )
    ui_blocks = output.ui_blocks or plan.ui_blocks
    analysis_plan = output.analysis_plan
    filters_changed = (
        [item.model_dump(mode="json") for item in analysis_plan.filters]
        != [item.model_dump(mode="json") for item in plan.analysis_plan.filters]
    )
    constraints = _normalized_constraints([*prior_constraints, constraint] if filters_changed else prior_constraints)
    return UiPlan(
        summary=output.summary,
        analysis_plan=analysis_plan,
        ui_state={
            **plan.ui_state,
            "additional_constraint": "" if filters_changed else constraint,
            "additional_constraints": constraints,
        },
        ui_blocks=ui_blocks,
        missing_fields=compute_missing_fields(analysis_plan, ui_blocks),
        suggested_constraints=output.suggested_constraints or plan.suggested_constraints,
        infeasible=output.infeasible or _carry_infeasible(plan.infeasible, analysis_plan.unresolved_constraints),
        warnings=output.warnings,
    )


def _carry_infeasible(prior, unresolved_constraints):
    """이전 조회 불가 사유 중 현재도 미해결 조건으로 남아 있는 항목만 유지한다."""

    active = {str(item).strip() for item in unresolved_constraints}
    return [item for item in (prior or []) if item.reason.strip() in active]


def _normalized_constraints(value: object) -> list[str]:
    """추가 조건을 목록으로 변환하고 공백·빈 항목·대소문자 기준 중복을 정리한다."""

    values = value if isinstance(value, list) else ([value] if value else [])
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = " ".join(str(item).split())
        key = text.casefold()
        if text and key not in seen:
            normalized.append(text)
            seen.add(key)
    return normalized
