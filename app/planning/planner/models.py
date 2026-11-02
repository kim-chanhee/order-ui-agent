"""계획 생성 응답과 후속 분석 맥락을 표현하는 모델."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.planning.analysis_models import AnalysisPlan, FieldMetadata
from app.planning.ui_models import UiBlock, SuggestedConstraint, InfeasibleCondition


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


class AnalysisDraft(BaseModel):
    """형식이 불완전할 수 있는 LLM의 최초 응답을 수용하는 임시 모델.

    계획 필드가 최상위에 배치되거나 일부 응답 필드가 누락된 경우도 우선 받아들인다.
    응답을 보정한 뒤 AnalysisPlan과 UI 모델로 엄격하게 검증한다."""

    model_config = ConfigDict(extra="allow")

    analysis_plan: AnalysisPlan | None = None
    missing_fields: list[str] = Field(default_factory=list)
    field_metadata: dict[str, FieldMetadata] = Field(default_factory=dict, description="Provenance only: status, confidence, source, label, description. Analysis values belong in analysis_plan.")
    infeasible: list[InfeasibleCondition] = Field(default_factory=list)
    summary: str | None = None
    warnings: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    context_resolution: PlannerContextResolution = Field(default_factory=PlannerContextResolution)

    @model_validator(mode="before")
    @classmethod
    def normalize_transport(cls, value: Any) -> Any:
        # The SDK parses this model before the planner's canonicalization step.
        # Use the same bounded repair here, then still validate strict UiBlocks.
        if isinstance(value, dict):
            from app.planning.planner.response import (
                _repair_raw_field_metadata, _repair_raw_infeasible, _repair_raw_ui_blocks,
            )
            data = dict(value)
            if cls is AnalysisDraft:
                data.pop('ui_blocks', None)
                data.pop('suggested_constraints', None)
            raw_plan = data.get("analysis_plan")
            if isinstance(raw_plan, BaseModel):
                raw_plan = raw_plan.model_dump(mode="json")
            plan = dict(raw_plan) if isinstance(raw_plan, dict) else {}
            for container in (data, plan):
                if isinstance(container.get("field_metadata"), dict):
                    container["field_metadata"] = _repair_raw_field_metadata(container["field_metadata"])
            if isinstance(raw_plan, dict):
                data["analysis_plan"] = plan
            for key in AnalysisPlan.model_fields:
                if key in data:
                    plan[key] = data[key]
            if isinstance(data.get("ui_blocks"), list):
                data["ui_blocks"] = _repair_raw_ui_blocks(data["ui_blocks"], plan=plan)
            if isinstance(data.get("infeasible"), list):
                data["infeasible"] = _repair_raw_infeasible(data["infeasible"])
            return data
        return value


class PlannerDraft(AnalysisDraft):
    """공통 분석 응답에 A2UI의 편집 블록과 추천 조건만 추가한다."""
    ui_blocks: list[UiBlock] = Field(default_factory=list)
    suggested_constraints: list[SuggestedConstraint] = Field(default_factory=list)
