"""A2UI 전용 계획 확정 검증과 서버가 허용한 편집 범위 검사.

주요 기능:
    - 확인 요청의 질문이 계획과 일치하는지 확인한다.
    - 필수 입력·미해결 조건·조회 불가 사유·비율 지표·선택값을 검증한다.
    - 서버가 발급한 편집 경로와 실제 변경 경로를 비교한다.
    - 하위 필드 편집 권한만으로 상위 객체를 삭제하는 변경을 차단한다.
"""

from __future__ import annotations

import re
from typing import Any

from app.planning.analysis_models import AnalysisPlan
from app.planning.ui_models import UiBlock, UiPlan
from app.planning.validator import compute_missing_fields, value_at_path


def validate_ui_plan(plan: UiPlan, question: str) -> AnalysisPlan:
    """질문 일치·필수값·미해결 조건·조회 불가 사유·비율 지표·선택값을 검사해 실행할 계획을 반환한다."""

    analysis = AnalysisPlan.model_validate(plan.analysis_plan.model_dump(mode="json"))
    if analysis.original_question.strip() != question.strip():
        raise ValueError("review plan question does not match the confirmation request")
    missing = compute_missing_fields(analysis, plan.ui_blocks)
    plan.missing_fields = missing
    if missing:
        labels = {
            (block.field_path or block.key): (block.label or block.field_path or block.key)
            for block in plan.ui_blocks
        }
        raise ValueError("required analysis fields are missing: " + ", ".join(labels.get(path, path) for path in missing))
    if analysis.unresolved_constraints:
        raise ValueError("unresolved constraints must be resolved before execution: " + "; ".join(analysis.unresolved_constraints))
    if plan.infeasible:
        raise ValueError(
            "검색할 수 없는 조건을 먼저 해결해 주세요: "
            + "; ".join(item.reason for item in plan.infeasible)
        )
    metric = analysis.metric
    if metric and metric.kind == "ratio" and (not metric.numerator or not metric.denominator):
        raise ValueError("ratio metric requires numerator and denominator")
    _validate_choice_values(analysis, plan.ui_blocks)
    return analysis


def validate_editable_analysis_plan(
    authoritative: AnalysisPlan,
    candidate: AnalysisPlan,
    ui_blocks: list[UiBlock],
) -> None:
    """원본과 수정 계획을 비교해 서버가 허용한 편집 필드 밖의 변경이나 상위 객체 삭제를 거부한다."""

    allowed = {block.field_path for block in ui_blocks if block.field_path}
    allowed.add("field_metadata")
    if "date_range" in allowed:
        allowed.add("date_anchor")
    before = authoritative.model_dump(mode="json")
    after = candidate.model_dump(mode="json")
    forbidden = [
        path
        for path in _changed_paths(before, after)
        if not _path_is_allowed(path, allowed)
        or _removes_parent_of_editable_field(path, before, after, allowed)
    ]
    if forbidden:
        raise ValueError("analysis plan contains changes outside editable fields: " + ", ".join(forbidden))


def _changed_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    """딕셔너리와 목록을 재귀 비교해 추가·삭제·값 변경이 발생한 필드 경로를 반환한다."""

    if isinstance(before, dict) and isinstance(after, dict):
        paths: list[str] = []
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_changed_paths(before.get(key), after.get(key), path))
        return paths
    if isinstance(before, list) and isinstance(after, list):
        paths = []
        for index in range(max(len(before), len(after))):
            path = f"{prefix}.{index}"
            left = before[index] if index < len(before) else object()
            right = after[index] if index < len(after) else object()
            paths.extend(_changed_paths(left, right, path))
        return paths
    return [] if before == after else [prefix]


def _path_is_allowed(path: str, allowed: set[str]) -> bool:
    """인덱스 표기를 통일하고 변경 경로가 편집 허용 경로 또는 그 상하위 경로인지 판단한다."""

    normalized_path = re.sub(r"\.(\d+)(?=\.|$)", r"[\1]", path)
    for editable in allowed:
        normalized_editable = re.sub(r"\.(\d+)(?=\.|$)", r"[\1]", editable)
        if (
            normalized_path == normalized_editable
            # 편집 허용 필드 안의 하위 경로 변경은 허용한다.
            # 예: metric 편집이 허용되면 metric.kind도 변경할 수 있다.
            or normalized_path.startswith(normalized_editable + ".")
            or normalized_path.startswith(normalized_editable + "[")
            # 변경 경로가 편집 가능한 하위 필드를 포함하는 상위 경로인 경우도 확인한다.
            # 예: metric이 None이었다면 객체를 새로 넣는 변경은 개별 키가 아니라
            # metric 전체의 교체로 기록된다. 화면에는 metric.kind나 metric.field만
            # 편집 가능하게 노출돼 있어도 이런 상위 객체 생성은 허용해야 한다.
            # 다만 하위 필드 권한으로 상위 객체를 삭제하는 경우는
            # _removes_parent_of_editable_field에서 별도로 차단한다.
            or normalized_editable.startswith(normalized_path + ".")
            or normalized_editable.startswith(normalized_path + "[")
        ):
            return True
    return False


def _removes_parent_of_editable_field(
    path: str,
    before: dict[str, Any],
    after: dict[str, Any],
    allowed: set[str],
) -> bool:
    """하위 필드만 편집할 수 있는 상황에서 상위 객체가 삭제되는지 확인한다."""

    normalized_path = re.sub(r"\.(\d+)(?=\.|$)", r"[\1]", path)
    is_parent_only = any(
        re.sub(r"\.(\d+)(?=\.|$)", r"[\1]", editable).startswith(
            normalized_path + "."
        )
        for editable in allowed
    )
    return bool(
        is_parent_only
        and value_at_path(before, path) is not None
        and value_at_path(after, path) is None
    )


def _validate_choice_values(plan: AnalysisPlan, ui_blocks: list[UiBlock]) -> None:
    """선택형 UI의 현재 값이 서버가 제공한 선택지에 포함되는지 검사한다."""

    for block in ui_blocks:
        if block.type not in {"select", "option_cards", "multi_select", "choice"} or not block.options:
            continue
        path = block.field_path or block.key
        current = value_at_path(plan.model_dump(mode="json"), path)
        if current in (None, "", []):
            continue
        allowed = {option.value for option in block.options}
        values = current if isinstance(current, list) else [current]
        invalid = [str(value) for value in values if str(value) not in allowed]
        if invalid:
            raise ValueError(f"{block.label or path} contains values outside the server-issued options: {', '.join(invalid)}")
