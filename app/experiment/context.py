"""채팅·계획 검토에서 공유하는 활성 실험 과제와 대화 식별자 조회."""

from __future__ import annotations

from app.experiment.store import (
    ExperimentSession, experiment_thread_id, require_session, validate_active_task,
)


def experiment_context(
    participant_id: str | None, input_source: str,
) -> tuple[ExperimentSession, str, str, str] | None:
    """활성 실험이면 세션·조건·과제·고정 thread_id를 돌려준다. 아니면 None."""

    session = require_session(participant_id)
    if not session:
        return None
    if session.status == "completed" or session.current_step == "completed":
        return None
    condition, task_id = validate_active_task(session, input_source)
    return session, condition, task_id, experiment_thread_id(session.participant_id, condition, task_id)
