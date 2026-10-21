"""실험 세션·과제·단계 관리와 CSV 내보내기 HTTP 라우터."""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.experiment.store import (
    advance_step, complete_current_task, export_interactions_csv,
    require_session, start_session,
)
from app.routes.errors import INVALID_EXPERIMENT_STEP, raise_api_error
from app.routes.schemas import ExperimentParticipantRequest, ExperimentSessionResponse, ExperimentStartRequest


router = APIRouter()


@router.post("/api/experiment/start", response_model=ExperimentSessionResponse)
def experiment_start(payload: ExperimentStartRequest) -> ExperimentSessionResponse:
    """참여자 세션을 시작하거나, 있으면 이어서 연다."""

    return ExperimentSessionResponse(session=start_session(payload.participant_id).model_dump())


@router.get("/api/experiment/session/{participant_id}", response_model=ExperimentSessionResponse)
def experiment_session(participant_id: str) -> ExperimentSessionResponse:
    """현재 실험 세션을 돌려준다. 없으면 404."""

    session = require_session(participant_id)
    if not session:
        raise_api_error(404, INVALID_EXPERIMENT_STEP, "실험 세션을 찾을 수 없습니다.")
    return ExperimentSessionResponse(session=session.model_dump())


@router.post("/api/experiment/task/complete", response_model=ExperimentSessionResponse)
def experiment_task_complete(payload: ExperimentParticipantRequest) -> ExperimentSessionResponse:
    """현재 과제를 완료로 표시한다."""

    try:
        return ExperimentSessionResponse(session=complete_current_task(payload.participant_id).model_dump())
    except ValueError as exc:
        raise_api_error(422, INVALID_EXPERIMENT_STEP, str(exc))


@router.post("/api/experiment/step/advance", response_model=ExperimentSessionResponse)
def experiment_step_advance(payload: ExperimentParticipantRequest) -> ExperimentSessionResponse:
    """서버가 허용한 다음 실험 단계로 넘긴다."""

    try:
        return ExperimentSessionResponse(session=advance_step(payload.participant_id).model_dump())
    except ValueError as exc:
        raise_api_error(422, INVALID_EXPERIMENT_STEP, str(exc))


@router.get("/api/experiment/export")
def experiment_export(researcher_key: str | None = None) -> PlainTextResponse:
    """실험 상호작용 CSV를 내려준다. 연구자 키가 맞아야 한다."""

    expected = os.environ.get("ORDER_UI_RESEARCHER_KEY", "dev")
    if researcher_key != expected:
        raise_api_error(403, INVALID_EXPERIMENT_STEP, "연구자 권한이 필요합니다.")
    return PlainTextResponse(export_interactions_csv(), media_type="text/csv; charset=utf-8")
