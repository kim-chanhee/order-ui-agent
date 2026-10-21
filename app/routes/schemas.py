"""공통 채팅·실험 API의 요청·응답 모델과 클라이언트 측정값.

A2UI 전용 계획 확정·수정 모델은 a2ui/schemas.py에 정의한다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ClientMetrics(BaseModel):
    """프론트가 보낸 계획 편집 시간·변경 필드. 실험 로그에 넣는다."""

    time_to_confirm_ms: int | None = Field(default=None, ge=0)
    changed_fields: list[str] = Field(default_factory=list)
    plan_diff: list[dict[str, Any]] = Field(default_factory=list)
    plan_changed: bool | None = None


class ChatRequest(BaseModel):
    """자연어 한 턴. baseline은 즉시 실행, agent2ui는 계획 검토 UI를 먼저 만든다."""

    question: str = Field(..., min_length=1)
    app_mode: Literal["admin", "user"] | None = None
    thread_id: str | None = None
    input_source: Literal["baseline", "agent2ui"] = "baseline"
    task_id: str | None = None
    run_id: str | None = None
    participant_id: str | None = None
    participant_profile: dict[str, Any] | None = None
    client_metrics: ClientMetrics | None = None
    supported_components: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """채팅 한 턴의 답과, 있으면 계획·실행 결과·A2UI 화면."""

    answer: str
    thread_id: str
    input_source: Literal["baseline", "agent2ui"] = "baseline"
    plan: dict | None = None
    execution_result: dict | None = None
    a2ui_surface: dict | None = None


class ExperimentStartRequest(BaseModel):
    """참여자 ID로 실험 세션을 시작하거나 이어서 연다."""

    participant_id: str = Field(..., min_length=1)


class ExperimentParticipantRequest(BaseModel):
    """과제 완료·단계 진행처럼 참여자 ID만 필요한 실험 요청."""

    participant_id: str = Field(..., min_length=1)


class ExperimentSessionResponse(BaseModel):
    """현재 실험 세션 스냅샷."""

    session: dict
