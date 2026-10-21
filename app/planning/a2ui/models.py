"""A2UI 검토 중 허용되는 추가 조건 수정 패치 모델.

자유 입력으로 필터를 추가·삭제하거나 미해결 조건·요약·경고를 전달한다.
기간·지표·집계 기준 등 보호 필드는 이 모델의 수정 대상으로 포함하지 않는다.
"""

from pydantic import Field

from app.planning.analysis_models import FilterSpec
from app.planning.ui_models import StrictModel


class RefinementPatch(StrictModel):
    """자연어 추가 조건으로 허용되는 필터 추가·삭제와 미해결 조건·요약·경고만 담는 수정 모델."""

    add_filters: list[FilterSpec] = Field(default_factory=list, max_length=20)
    remove_filter_ids: list[str] = Field(default_factory=list, max_length=20)
    unresolved_constraints: list[str] = Field(default_factory=list, max_length=20)
    summary: str | None = None
    warnings: list[str] = Field(default_factory=list, max_length=20)
