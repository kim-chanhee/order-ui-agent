"""두 모드의 채팅 결과를 공통 실험 상호작용 기록으로 변환한다.

A2UI 확정 실행 기록은 a2ui/interactions.py에서 담당한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.experiment.store import ExperimentSession, record_interaction

if TYPE_CHECKING:
    from app.routes.schemas import ChatRequest


def record_chat_interaction(
    *,
    payload: ChatRequest,
    result: dict,
    session: ExperimentSession,
    condition: str,
    task_id: str,
    thread_id: str,
    started_at: str,
    duration_ms: int,
    stage: str,
) -> None:
    """채팅 한 턴을 실험 interaction 저장소에 남긴다."""

    execution_result = result.get("execution_result") or {}
    normalized = execution_result.get("normalized_spec") or {}
    draft_plan = result.get("plan") or normalized.get("draft_plan")
    confirmed_plan = normalized.get("analysis_plan") if stage == "executed" else None
    analysis_payload = normalized.get("analysis_execution") or {}
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
            "draft_plan": draft_plan,
            "confirmed_plan": confirmed_plan,
            "planner_source": _planner_value(draft_plan, "source"),
            "planner_confidence": _planner_value(draft_plan, "confidence"),
            "execution_route": normalized.get("execution_route") or execution_result.get("provider") or "",
            "execution_success": bool(analysis_payload),
            "error_type": normalized.get("fallback_reason") or "",
            "started_at": started_at,
            "plan_created_at": now,
            "confirmed_at": now if confirmed_plan else "",
            "completed_at": now if confirmed_plan else "",
            "planning_duration_ms": duration_ms if draft_plan else 0,
            "execution_duration_ms": duration_ms if confirmed_plan else 0,
            "total_duration_ms": duration_ms,
            "analysis_payload": analysis_payload,
        }
    )


def _planner_value(plan: dict | None, key: str):
    """계획 또는 그 안 analysis_plan에서 source·confidence 같은 값을 꺼낸다."""

    if not isinstance(plan, dict):
        return ""
    analysis_plan = plan.get("analysis_plan") if isinstance(plan.get("analysis_plan"), dict) else plan
    return analysis_plan.get(key, "") if isinstance(analysis_plan, dict) else ""


def _now_iso() -> str:
    """로그 시각용 UTC ISO 문자열."""
    return datetime.now(timezone.utc).isoformat()
