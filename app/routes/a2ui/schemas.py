"""A2UI 전용 계획 확정·수정 요청과 응답 모델."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.planning.ui_models import UiPlan
from app.routes.schemas import ClientMetrics


class ConfirmDraftRequest(BaseModel):
    """사용자가 확인한 Agent2UI 계획을 SQL 실행에 넘긴다."""

    thread_id: str | None = None
    question: str = Field(..., min_length=1)
    app_mode: Literal["admin", "user"] | None = None
    plan: UiPlan
    analysis_plan: dict[str, Any] | None = None
    input_source: Literal["agent2ui"] = "agent2ui"
    task_id: str | None = None
    run_id: str | None = None
    participant_id: str | None = None
    participant_profile: dict[str, Any] | None = None
    client_metrics: ClientMetrics | None = None
    plan_diff: list[dict[str, Any]] = Field(default_factory=list)
    surface_id: str = Field(min_length=1)
    plan_id: str | None = None
    revision: int = Field(ge=1)
    selected_suggestion_id: str | None = None
    refinement_count: int = Field(default=0, ge=0)
    supported_components: list[str] = Field(default_factory=list)


class ConfirmDraftResponse(BaseModel):
    """확정 실행 결과와 갱신된 계획·화면."""

    thread_id: str
    input_source: Literal["agent2ui"] = "agent2ui"
    plan: dict
    message: str
    execution_result: dict
    a2ui_surface: dict | None = None


class RefineDraftRequest(BaseModel):
    """검토 중 자연어 추가 조건을 기존 계획에 붙인다. SQL은 아직 실행하지 않는다."""

    question: str = Field(..., min_length=1)
    thread_id: str | None = None
    plan: UiPlan
    additional_constraint: str = Field(..., min_length=1, max_length=2000)
    selected_suggestion_id: str | None = None
    surface_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    participant_id: str | None = None
    participant_profile: dict[str, Any] | None = None
    refinement_count: int = Field(default=0, ge=0)
    supported_components: list[str] = Field(default_factory=list)


class RefineDraftResponse(BaseModel):
    """revision이 하나 올라간 새 계획과 A2UI 화면."""

    plan: dict
    a2ui_surface: dict
    surface_id: str
    plan_id: str
    revision: int
