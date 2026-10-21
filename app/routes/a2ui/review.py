"""A2UI 전용 분석 계획 확정·수정과 서버 발급 화면 검증 HTTP 라우터."""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from fastapi import APIRouter, HTTPException

from app.a2ui.review import surface_for_plan
from app.chat.thread_context import remember_execution_context
from app.execution.a2ui.service import confirm_response_payload
from app.experiment.context import experiment_context
from app.experiment.a2ui.interactions import record_confirm_interaction
from app.experiment.log import append_experiment_csv
from app.planning.a2ui.review import refine_review_plan
from app.planning.ui_models import UiPlan
from app.routes.errors import (
    INTERNAL_ERROR, INVALID_EXPERIMENT_STEP, PLAN_REVISION_CONFLICT,
    PLAN_VALIDATION_ERROR, raise_api_error,
)
from app.routes.a2ui.schemas import ConfirmDraftRequest, ConfirmDraftResponse, RefineDraftRequest, RefineDraftResponse
from app.runtime.chat_log import append_chat_csv
from app.runtime.run_manager import run_cancelable
from app.runtime.a2ui.surfaces import get_plan_surface
from app.runtime.state_store import record_execution_result


router = APIRouter()


@router.post("/api/review/confirm", response_model=ConfirmDraftResponse)
def confirm_review(payload: ConfirmDraftRequest) -> ConfirmDraftResponse:
    """사용자가 확인한 계획을 실행한다. 오래된 화면 revision이면 409."""

    try:
        started_at = perf_counter()
        started_iso = datetime.now(timezone.utc).isoformat()
        experiment = experiment_context(payload.participant_id, payload.input_source)
        if experiment:
            session, condition, task_id, thread_id = experiment
            if condition != "agent2ui":
                raise ValueError("confirm is only allowed in the Agent2UI experiment condition")
            payload = payload.model_copy(update={"thread_id": thread_id, "task_id": task_id})
        stored_surface = _validate_surface_revision(payload)
        payload = _with_authoritative_ui_schema(payload, stored_surface)
        if payload.run_id:
            result = run_cancelable("confirm", payload.model_dump(mode="json"), payload.run_id)
        else:
            result = confirm_response_payload(payload)
        duration_ms = round((perf_counter() - started_at) * 1000)
        record_execution_result(
            result.get("thread_id"),
            payload.question,
            result.get("execution_result"),
        )
        remember_execution_context(result.get("thread_id"), result.get("execution_result"))
        append_experiment_csv(
            participant_id=payload.participant_id,
            participant_profile=payload.participant_profile,
            thread_id=result.get("thread_id"),
            run_id=payload.run_id,
            stage="confirmed_execution",
            input_source=result.get("input_source"),
            question=payload.question,
            assistant_answer=result.get("message"),
            plan=result.get("plan"),
            execution_result=result.get("execution_result"),
            time_to_confirm_ms=payload.client_metrics.time_to_confirm_ms if payload.client_metrics else None,
            time_to_answer_ms=duration_ms,
            changed_fields=payload.client_metrics.changed_fields if payload.client_metrics else None,
            plan_diff=payload.plan_diff or (payload.client_metrics.plan_diff if payload.client_metrics else None),
            plan_changed=payload.client_metrics.plan_changed if payload.client_metrics else None,
            additional_constraint=str(payload.plan.ui_state.get("additional_constraint") or ""),
            selected_suggestion_id=payload.selected_suggestion_id,
            surface_id=payload.surface_id,
            revision=payload.revision,
            refinement_count=payload.refinement_count,
        )
        append_chat_csv(
            thread_id=result.get("thread_id"),
            run_id=payload.run_id,
            stage="confirmed_execution",
            input_source=result.get("input_source"),
            question=payload.question,
            assistant_answer=result.get("message"),
            plan=result.get("plan"),
            execution_result=result.get("execution_result"),
            app_mode=payload.app_mode,
            participant_id=payload.participant_id,
            task_id=payload.task_id,
            duration_ms=duration_ms,
        )
        if experiment:
            record_confirm_interaction(
                payload=payload,
                result=result,
                session=session,
                condition=condition,
                task_id=task_id,
                thread_id=thread_id,
                started_at=started_iso,
                duration_ms=duration_ms,
            )
        return ConfirmDraftResponse.model_validate(result)
    except ValueError as exc:
        code = INVALID_EXPERIMENT_STEP if "experiment" in str(exc) or "confirm is only allowed" in str(exc) else PLAN_VALIDATION_ERROR
        raise_api_error(422, code, str(exc))
    except HTTPException:
        raise
    except Exception:
        raise_api_error(500, INTERNAL_ERROR, "요청 처리 중 오류가 발생했습니다.")


@router.post("/api/review/refine", response_model=RefineDraftResponse)
def refine_review(payload: RefineDraftRequest) -> RefineDraftResponse:
    """추가 조건을 계획에 반영하고 revision을 하나 올린 새 화면을 만든다."""

    try:
        started_at = perf_counter()
        stored_surface = _validate_surface_revision(payload)
        payload = _with_authoritative_ui_schema(payload, stored_surface)
        refined = refine_review_plan(
            payload.plan.model_copy(deep=True),
            question=payload.question.strip(),
            additional_constraint=payload.additional_constraint,
        )
        refined.ui_state.update(
            selected_suggestion_id=payload.selected_suggestion_id,
            refinement_count=payload.refinement_count + 1,
        )
        revision = payload.revision + 1
        surface = surface_for_plan(
            refined,
            payload.supported_components,
            participant_id=payload.participant_id,
            thread_id=payload.thread_id or "",
            surface_id=payload.surface_id,
            plan_id=payload.plan_id,
            revision=revision,
        )
        plan_payload = refined.model_dump(mode="json")
        plan_payload.update(
            surface_id=payload.surface_id,
            plan_id=payload.plan_id,
            revision=revision,
            selected_suggestion_id=payload.selected_suggestion_id,
            refinement_count=payload.refinement_count + 1,
        )
        response = RefineDraftResponse(
            plan=plan_payload,
            a2ui_surface=surface,
            surface_id=payload.surface_id,
            plan_id=payload.plan_id,
            revision=revision,
        )
        append_experiment_csv(
            participant_id=payload.participant_id,
            participant_profile=payload.participant_profile,
            thread_id=payload.thread_id,
            run_id=None,
            stage="plan_refined",
            input_source="agent2ui",
            question=payload.question,
            assistant_answer=refined.summary,
            plan=plan_payload,
            time_to_plan_ms=round((perf_counter() - started_at) * 1000),
            additional_constraint=payload.additional_constraint,
            selected_suggestion_id=payload.selected_suggestion_id,
            surface_id=payload.surface_id,
            revision=revision,
            refinement_count=payload.refinement_count + 1,
        )
        return response
    except ValueError as exc:
        raise_api_error(422, PLAN_VALIDATION_ERROR, str(exc))
    except HTTPException:
        raise
    except Exception:
        raise_api_error(500, INTERNAL_ERROR, "추가 조건을 구조화하지 못했습니다.")


def _validate_surface_revision(payload: ConfirmDraftRequest | RefineDraftRequest) -> dict:
    """클라이언트가 보낸 surface/plan/revision이 서버에 저장한 최신 화면과 같은지 본다."""

    surface = get_plan_surface(payload.surface_id)
    if not surface:
        raise_api_error(409, PLAN_REVISION_CONFLICT, "최신 분석 화면을 찾을 수 없습니다.", retryable=True)
    if payload.plan_id and payload.plan_id != surface["plan_id"]:
        raise_api_error(409, PLAN_REVISION_CONFLICT, "분석 화면의 plan_id가 최신 상태와 다릅니다.", retryable=True)
    if payload.revision != surface["revision"]:
        raise_api_error(
            409,
            PLAN_REVISION_CONFLICT,
            "오래된 분석 화면입니다. 최신 계획을 다시 확인해 주세요.",
            retryable=True,
            details={"server_revision": surface["revision"]},
        )
    return surface


def _with_authoritative_ui_schema(
    payload: ConfirmDraftRequest | RefineDraftRequest,
    stored_surface: dict,
) -> ConfirmDraftRequest | RefineDraftRequest:
    """사용자가 고친 분석 값은 유지하고, UI 스키마는 서버가 준 최신 화면을 쓴다."""

    authoritative = UiPlan.model_validate(stored_surface["plan"])
    from app.planning.a2ui.validator import validate_editable_analysis_plan

    validate_editable_analysis_plan(
        authoritative.analysis_plan,
        payload.plan.analysis_plan,
        authoritative.ui_blocks,
    )
    plan = payload.plan.model_copy(
        deep=True,
        update={
            "summary": authoritative.summary,
            "ui_state": authoritative.ui_state,
            "ui_blocks": authoritative.ui_blocks,
            "suggested_constraints": authoritative.suggested_constraints,
            "infeasible": authoritative.infeasible,
            "warnings": authoritative.warnings,
            "requires_confirmation": authoritative.requires_confirmation,
        },
    )
    return payload.model_copy(update={"plan": plan})
