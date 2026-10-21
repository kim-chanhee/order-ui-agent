"""A2UI 전용 검토 계획을 화면 데이터로 변환하고 저장한다."""

from __future__ import annotations

from uuid import uuid4

from app.a2ui.adapter import _supported_set, _supported_type
from app.a2ui.models import A2UIAction, A2UIClientCapabilities, A2UIComponent, A2UISurface
from app.planning.ui_models import UiPlan
from app.runtime.a2ui.surfaces import save_plan_surface


def schema_review_surface(
    plan: UiPlan,
    *,
    capabilities: A2UIClientCapabilities | None = None,
    surface_id: str | None = None,
    plan_id: str | None = None,
    revision: int = 1,
) -> A2UISurface:
    supported = _supported_set(capabilities)
    fallbacks: list[dict[str, str]] = []
    data_model = {
        "analysis_plan": plan.analysis_plan.model_dump(mode="json"),
        "original_question": plan.analysis_plan.original_question,
        "summary": plan.summary,
        "ui_state": {
            "selected_suggestion_id": None,
            "refinement_count": 0,
            **plan.ui_state,
        },
        "missing_fields": list(plan.missing_fields),
        "field_metadata": {
            key: value.model_dump(mode="json") for key, value in plan.analysis_plan.field_metadata.items()
        },
        "suggested_constraints": [item.model_dump(mode="json") for item in plan.suggested_constraints],
        "infeasible": [item.model_dump(mode="json") for item in plan.infeasible],
        "warnings": list(plan.warnings),
        "requires_confirmation": plan.requires_confirmation,
    }
    components = []
    for block in plan.ui_blocks:
        component_type = _supported_type(block.type, supported, fallbacks)
        components.append(
            A2UIComponent(
                component_id=block.key,
                component_type=component_type,
                data_model=block.model_dump(mode="json"),
                actions=[
                    A2UIAction(
                        action_id=f"update_{block.key}",
                        action_type="update_field",
                        label=block.label,
                        target=block.field_path or block.key,
                    )
                ] if block.field_path else [],
            )
        )
    return A2UISurface(
        surface_id=surface_id or str(uuid4()),
        plan_id=plan_id or str(uuid4()),
        revision=revision,
        surface_type="plan",
        data_model=data_model,
        components=components,
        actions=[
            A2UIAction(action_id="confirm_plan", action_type="confirm_plan", label="이 질문으로 실행"),
            A2UIAction(action_id="refine_plan", action_type="refine_plan", label="추가 조건 적용"),
            A2UIAction(action_id="cancel_run", action_type="cancel_run", label="취소"),
        ],
        compatibility={"fallbacks": fallbacks, "supported_components": sorted(supported)},
    )


def review_answer(_plan: UiPlan) -> str:
    return "Answer: 분석 조건과 검토 UI를 만들었습니다. 확인하거나 필요한 값을 수정한 뒤 실행해 주세요."


def surface_for_plan(
    plan: UiPlan,
    supported_components: list[str],
    *,
    participant_id: str | None,
    thread_id: str,
    surface_id: str | None = None,
    plan_id: str | None = None,
    revision: int = 1,
) -> dict:
    """Create a review surface and persist the exact plan shown to the user."""

    surface = schema_review_surface(
        plan,
        capabilities=A2UIClientCapabilities(supported_components=supported_components),
        surface_id=surface_id,
        plan_id=plan_id,
        revision=revision,
    )
    payload = surface.model_dump(mode="json")
    save_plan_surface(
        surface_id=surface.surface_id,
        plan_id=surface.plan_id or surface.surface_id,
        revision=surface.revision,
        plan=plan.model_dump(mode="json"),
        surface=payload,
        participant_id=participant_id,
        thread_id=thread_id,
    )
    return payload
