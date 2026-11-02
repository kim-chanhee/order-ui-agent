"""검토 화면의 허용된 필드 수정과 필터 추가·삭제를 표현하는 패치."""

from typing import Any

from pydantic import Field, field_validator

from app.planning.analysis_models import FilterSpec
from app.planning.ui_models import StrictModel, UiBlock, _EDITABLE_PLAN_PATH


class PlanFieldUpdate(StrictModel):
    """화면이 발급한 편집 경로 하나에 적용할 값. 권한은 병합 단계에서 검사한다."""

    path: str
    value: Any

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not _EDITABLE_PLAN_PATH.fullmatch(value):
            raise ValueError("수정 가능한 분석 조건 경로가 아닙니다.")
        return value


class RefinementPatch(StrictModel):
    """기존 계획의 나머지 의미를 유지하며 요청받은 조건만 변경한다."""

    updates: list[PlanFieldUpdate] = Field(default_factory=list, max_length=20)
    add_filters: list[FilterSpec] = Field(default_factory=list, max_length=20)
    remove_filter_ids: list[str] = Field(default_factory=list, max_length=20)
    resolve_constraints: list[str] = Field(default_factory=list, max_length=20)
    unresolved_constraints: list[str] = Field(default_factory=list, max_length=20)
    ui_blocks: list[UiBlock] | None = Field(default=None, max_length=64)
    summary: str | None = None
    warnings: list[str] = Field(default_factory=list, max_length=20)
