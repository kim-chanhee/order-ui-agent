"""계획 생성 응답과 후속 분석 맥락을 표현하는 모델."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.planning.analysis_models import AnalysisPlan


ContextField = Literal[
    "date_range", "target_conditions", "filters", "event_types", "metric", "metrics",
    "group_by", "comparison", "sort", "limit", "output",
    "target_entity", "requested_attributes", "result_grain", "relationship_scope",
    "excluded_attributes",
]


class PlannerContextResolution(BaseModel):
    """현재 질문의 후속 여부, 참조할 이전 분석과 상속·덮어쓰기할 필드를 지정한다."""

    model_config = ConfigDict(extra="forbid")

    is_followup: bool = False
    selected_context_id: str | None = None
    inherit_fields: list[ContextField] = Field(default_factory=list)
    override_fields: list[ContextField] = Field(default_factory=list)
    reference_evidence: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_confirmation: bool = False


class PlannerContextCandidate(BaseModel):
    """후속 질문의 참조 후보가 되는 이전 분석의 계획·답변·행 샘플·식별자 값을 담는다."""

    model_config = ConfigDict(extra="forbid")

    context_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=4000)
    analysis_plan: AnalysisPlan
    answer: str | None = Field(default=None, max_length=8000)
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    identity_values: dict[str, list[str]] = Field(default_factory=dict)


class PlannerDraft(BaseModel):
    """형식이 불완전할 수 있는 LLM의 최초 응답을 수용하는 임시 모델.

    계획 필드가 최상위에 배치되거나 일부 응답 필드가 누락된 경우도 우선 받아들인다.
    응답을 보정한 뒤 AnalysisPlan과 UI 모델로 엄격하게 검증한다."""

    model_config = ConfigDict(extra="allow")

    analysis_plan: dict[str, Any] | AnalysisPlan | None = None
    ui_blocks: list[Any] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    field_metadata: dict[str, Any] = Field(default_factory=dict)
    suggested_constraints: list[Any] = Field(default_factory=list)
    infeasible: list[Any] = Field(default_factory=list)
    summary: str | None = None
    warnings: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    context_resolution: PlannerContextResolution = Field(default_factory=PlannerContextResolution)
