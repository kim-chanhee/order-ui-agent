"""A2UI 전용 계획 확정 실행을 실험 상호작용 기록으로 변환한다."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.experiment.interactions import _now_iso, _planner_value
from app.experiment.store import ExperimentSession, record_interaction

if TYPE_CHECKING:
    from app.routes.a2ui.schemas import ConfirmDraftRequest


def record_confirm_interaction(
    *,
    payload: ConfirmDraftRequest,
    result: dict,
    session: ExperimentSession,
    condition: str,
    task_id: str,
    thread_id: str,
    started_at: str,
    duration_ms: int,
) -> None:
    """확정 실행 한 건을 실험 interaction 저장소에 남긴다."""

    execution_result = result.get("execution_result") or {}
    normalized = execution_result.get("normalized_spec") or {}
    analysis_payload = normalized.get("analysis_execution") or {}
    metrics = payload.client_metrics
    now = _now_iso()
    record_interaction(
        {
            "interaction_id": payload.run_id or f"{payload.participant_id}-{condition}-{task_id}-{started_at}",
            "run_id": payload.run_id,
            "participant_id": payload.participant_id,
            "assignment_group": session.assignment_group,
            "condition": condition,
            "task_id": task_id,
            "thread_id": thread_id,
            "question": payload.question,
            "draft_plan": payload.plan.model_dump(mode="json"),
            "confirmed_plan": normalized.get("analysis_plan"),
            "planner_source": _planner_value(payload.plan.model_dump(mode="json"), "source"),
            "planner_confidence": _planner_value(payload.plan.model_dump(mode="json"), "confidence"),
            "changed_fields": metrics.changed_fields if metrics else [],
            "plan_diff": payload.plan_diff or (metrics.plan_diff if metrics else []),
            "execution_route": normalized.get("execution_route") or execution_result.get("provider") or "",
            "execution_success": bool(analysis_payload),
            "error_type": normalized.get("fallback_reason") or "",
            "started_at": started_at,
            "plan_created_at": started_at,
            "confirmed_at": now,
            "completed_at": now,
            "editing_duration_ms": metrics.time_to_confirm_ms if metrics else 0,
            "execution_duration_ms": duration_ms,
            "total_duration_ms": duration_ms + (metrics.time_to_confirm_ms if metrics and metrics.time_to_confirm_ms else 0),
            "analysis_payload": analysis_payload,
        }
    )
