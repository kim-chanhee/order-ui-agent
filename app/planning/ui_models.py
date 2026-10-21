"""두 모드가 공유하는 선언형 UI와 분석 계획 응답 모델.

주요 기능:
    - 허용된 컴포넌트·선택지·조건부 표시·필수 입력 규칙을 정의한다.
    - UI 경로를 편집 가능한 계획 필드로 제한하고 실행형 속성을 차단한다.
    - 추천 조건·조회 불가 사유·필드 메타데이터를 계획 응답과 함께 전달한다.
    - 계획과 응답의 메타데이터를 동기화하고 UI 상태에 SQL이 포함되지 않게 한다.

Baseline도 계획 생성 과정에서 UiPlan과 DynamicPlannerOutput을 사용한다.
A2UI 전용 추가 조건 수정 패치는 a2ui/models.py에 정의한다.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.planning.analysis_models import AnalysisPlan, FieldMetadata, _reject_sql_payload


ComponentType = Literal[
    "text", "textarea", "number", "select", "option_cards", "multi_select",
    "checkbox", "date", "date_range", "choice", "review", "notice",
]
ConditionOperator = Literal["eq", "neq", "contains", "not_contains", "in", "exists", "not_empty"]

_EDITABLE_PLAN_PATH = re.compile(
    r"^(?:date_range(?:\.(?:mode|preset|relative_days|date_from|date_to))?"
    r"|event_types(?:\[\d+\]|\.\d+)?|target_conditions(?:\[\d+\]|\.\d+)?"
    r"|metric(?:\.(?:kind|unit|distinct|field|numerator|denominator|minimum_sample_size))?"
    r"|metrics(?:\[\d+\]|\.\d+)?(?:\.(?:kind|unit|distinct|field|numerator|denominator|minimum_sample_size))?"
    r"|group_by(?:\[\d+\]|\.\d+)?|filters(?:\[\d+\]|\.\d+)?(?:\.(?:field|operator|value|source))?"
    r"|comparison|sort(?:\[\d+\]|\.\d+)?(?:\.(?:field|direction))?|limit"
    r"|output(?:\.(?:view|fields(?:\[\d+\]|\.\d+)?|include_summary))?)$"
)


class StrictModel(BaseModel):
    """선언하지 않은 추가 필드를 거부하는 공통 모델."""

    model_config = ConfigDict(extra="forbid")


class UiOption(StrictModel):
    """선택형 입력에 사용할 실제 값, 표시 이름과 보충 설명을 정의한다."""

    value: str
    label: str
    description: str | None = None


class UiCondition(StrictModel):
    """필드 비교 또는 all·any로 묶은 조건으로 UI 표시·필수 입력 규칙을 표현한다."""

    path: str | None = None
    operator: ConditionOperator | None = None
    value: Any = None
    all: list["UiCondition"] | None = None
    any: list["UiCondition"] | None = None

    @field_validator("path")
    @classmethod
    def validate_condition_path(cls, value: str | None) -> str | None:
        """조건 경로의 analysis_plan 접두사를 제거하고 UI에서 허용된 필드인지 확인한다."""

        if value is None:
            return None
        normalized = value.removeprefix("analysis_plan.")
        if not _EDITABLE_PLAN_PATH.fullmatch(normalized):
            raise ValueError("condition path must target an AnalysisPlan UI field")
        return normalized

    @model_validator(mode="after")
    def validate_shape(self) -> "UiCondition":
        """단일 조건·전체 일치·일부 일치 중 하나만 사용하도록 조건 구조와 연산자를 검증한다."""

        modes = int(self.path is not None) + int(self.all is not None) + int(self.any is not None)
        if modes != 1:
            raise ValueError("condition must contain exactly one of path, all, or any")
        if self.path is not None and self.operator is None:
            raise ValueError("leaf condition requires an operator")
        if self.path is None and self.operator is not None:
            raise ValueError("condition group may not contain an operator")
        return self


class UiBlock(StrictModel):
    """허용된 컴포넌트와 계획 필드를 연결하고 선택지·표시 조건·필수 여부를 정의한다."""

    type: ComponentType
    key: str = Field(min_length=1, max_length=100)
    field_path: str | None = None
    label: str
    description: str | None = None
    required: bool = False
    required_if: UiCondition | None = None
    visible_if: UiCondition | None = None
    options: list[UiOption] = Field(default_factory=list)
    props: dict[str, Any] = Field(default_factory=dict)
    section: Literal["primary", "advanced"] = "primary"

    @field_validator("field_path")
    @classmethod
    def validate_field_path(cls, value: str | None) -> str | None:
        """필드 경로의 analysis_plan 접두사를 제거하고 편집 가능한 계획 필드인지 검증한다."""

        if value is None:
            return None
        normalized = value.removeprefix("analysis_plan.")
        if not _EDITABLE_PLAN_PATH.fullmatch(normalized):
            raise ValueError("field_path must target an editable AnalysisPlan field")
        return normalized

    @field_validator("props")
    @classmethod
    def reject_executable_props(cls, value: dict[str, Any]) -> dict[str, Any]:
        """UI 속성에 HTML·스크립트·이벤트 핸들러 등 금지된 실행 관련 키가 있으면 거부한다."""

        forbidden = {"html", "javascript", "script", "onchange", "onclick", "eval"}
        if forbidden.intersection(str(key).lower() for key in value):
            raise ValueError("UI props may not contain executable content")
        return value


class SuggestedConstraint(StrictModel):
    """사용자가 추가할 수 있는 추천 조건의 식별자·표시 이름·문장·추천 이유를 담는다."""

    id: str
    label: str
    text: str
    reason: str | None = None


class InfeasibleCondition(StrictModel):
    """현재 데이터나 스키마로 답할 수 없는 조건과 그 이유를 담는다.

    field_path는 화면의 계획 문장에서 강조할 분석 필드를 가리키며, 연결할 필드가 없으면 None이다.
    계획 생성기는 reason을 unresolved_constraints에도 반영해 확인 단계에서 실행을 차단한다."""

    field_path: str | None = None
    label: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("field_path")
    @classmethod
    def validate_field_path(cls, value: str | None) -> str | None:
        """필드 경로의 analysis_plan 접두사를 제거하고 편집 가능한 계획 필드인지 검증한다."""

        if value is None:
            return None
        normalized = value.removeprefix("analysis_plan.")
        if not _EDITABLE_PLAN_PATH.fullmatch(normalized):
            raise ValueError("field_path must target an editable AnalysisPlan field")
        return normalized


class DynamicPlannerOutput(StrictModel):
    """LLM 계획 생성 결과인 분석 계획·UI 블록·누락 입력·추천 조건·경고를 묶는다."""

    analysis_plan: AnalysisPlan
    ui_blocks: list[UiBlock] = Field(default_factory=list, max_length=12)
    missing_fields: list[str] = Field(default_factory=list)
    field_metadata: dict[str, FieldMetadata] = Field(default_factory=dict)
    suggested_constraints: list[SuggestedConstraint] = Field(default_factory=list, max_length=4)
    infeasible: list[InfeasibleCondition] = Field(default_factory=list, max_length=12)
    summary: str
    warnings: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True

    @model_validator(mode="after")
    def synchronize_metadata(self) -> "DynamicPlannerOutput":
        """계획 내부와 응답의 필드 메타데이터를 병합해 양쪽에 같은 값을 반영한다."""

        merged = {**self.analysis_plan.field_metadata, **self.field_metadata}
        self.field_metadata = merged
        self.analysis_plan.field_metadata = merged
        return self


class UiPlan(StrictModel):
    """사용자가 확인하거나 수정할 분석 계획과 화면 상태·입력 항목·제약 사항을 담는다."""

    domain: str = "schema_driven"
    intent: str = "schema_driven_query"
    summary: str
    analysis_plan: AnalysisPlan
    ui_state: dict[str, Any] = Field(default_factory=dict)
    ui_blocks: list[UiBlock] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    suggested_constraints: list[SuggestedConstraint] = Field(default_factory=list)
    infeasible: list[InfeasibleCondition] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True

    @field_validator("ui_state")
    @classmethod
    def reject_sql_in_state(cls, value: dict[str, Any]) -> dict[str, Any]:
        """UI 상태를 재귀 검사해 SQL이 포함된 상태값을 거부한다."""

        _reject_sql_payload(value, "ui_state")
        return value
