"""A2UI-compatible transport models for review and result surfaces."""

from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

# UI 상에서 사용자 상호작용을 통해 발생할 수 있는 액션의 종류 정의
ActionType = Literal[
    "update_field", "select_choice", "confirm_plan", "edit_plan", "refine_plan",
    "cancel_run", "start_new_query",
]


class A2UIAction(BaseModel):
    """UI 상의 액션(예: 버튼 클릭, 필드 수정 등) 정보를 표현하는 모델입니다.

    Attributes:
        action_id: 액션의 고유 식별자.
        action_type: 어떤 종류의 액션인지 나타내는 타입 (예: "confirm_plan").
        label: 사용자 화면에 표시될 버튼/링크의 텍스트 레이블.
        target: 액션이 영향을 주는 대상 컴포넌트 ID (없을 수도 있음).
        payload_schema: 액션 실행 시 함께 전달해야 하는 데이터 스키마(JSON Schema 형태).
    """
    action_id: str
    action_type: ActionType
    label: str
    target: str | None = None
    payload_schema: dict[str, Any] = Field(default_factory=dict)


class A2UIComponent(BaseModel):
    """UI 화면을 구성하는 개별 컴포넌트(입력창, 차트, 테이블 등)를 표현하는 모델입니다.

    Attributes:
        component_id: 컴포넌트의 고유 식별자.
        component_type: 컴포넌트 종류 (예: "select", "table", "bar_chart").
        data_model: 컴포넌트가 화면에 렌더링할 때 사용하는 실제 데이터와 메타데이터.
        actions: 해당 컴포넌트 내에서 개별적으로 트리거할 수 있는 액션 리스트.
    """
    component_id: str
    component_type: str
    data_model: dict[str, Any] = Field(default_factory=dict)
    actions: list[A2UIAction] = Field(default_factory=list)


class A2UISurface(BaseModel):
    """사용자에게 보여줄 하나의 화면(Surface) 단위 정보입니다.
    여러 컴포넌트와 화면 전체의 전역 액션들로 구성됩니다.

    Attributes:
        surface_id: 화면 자체의 고유 식별자.
        plan_id: 관련 분석 계획(Plan)의 고유 식별자 (있을 수도 있음).
        revision: 화면의 버전 번호 (사용자 수정 시 증가).
        surface_type: 화면의 성격 (계획, 결과 또는 확인 질문).
        data_model: 화면 전체에서 공통으로 사용되는 원본 데이터.
        components: 화면을 채우는 컴포넌트들의 목록.
        actions: 화면 전체에서 실행 가능한 전역 액션들의 목록 (예: 계획 확정, 취소).
        compatibility: 클라이언트 컴포넌트 미지원에 따른 대체 컴포넌트(fallback) 및 지원 정보.
    """
    surface_id: str
    plan_id: str | None = None
    revision: int = 1
    surface_type: Literal["plan", "result", "clarification"] = "plan"
    data_model: dict[str, Any] = Field(default_factory=dict)
    components: list[A2UIComponent] = Field(default_factory=list)
    actions: list[A2UIAction] = Field(default_factory=list)
    compatibility: dict[str, Any] = Field(default_factory=dict)


class A2UIClientCapabilities(BaseModel):
    """클라이언트(프론트엔드) 애플리케이션이 지원하는 기능 스펙을 표현하는 모델입니다.

    Attributes:
        supported_components: 클라이언트가 렌더링할 수 있는 UI 컴포넌트 이름 목록.
    """
    supported_components: list[str] = Field(default_factory=list)
