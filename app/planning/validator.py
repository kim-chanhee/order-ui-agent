"""두 모드가 공유하는 UI 조건 평가와 필수 입력 필드 계산.

주요 기능:
    - 중첩된 딕셔너리·목록에서 점·대괄호 경로로 값을 조회한다.
    - 단일 비교 조건과 all·any로 구성한 표시·필수 입력 조건을 평가한다.
    - 현재 표시되는 필수 입력 중 비어 있는 필드 경로를 계산한다.

A2UI 확정 계획과 편집 범위 검증은 a2ui/validator.py에서 담당한다.
"""

from __future__ import annotations

import re
from typing import Any

from app.planning.analysis_models import AnalysisPlan
from app.planning.ui_models import UiBlock, UiCondition


def condition_matches(condition: UiCondition | None, plan: AnalysisPlan | dict[str, Any]) -> bool:
    """계획의 값을 읽어 단일 비교 조건이나 all·any로 묶인 중첩 조건의 충족 여부를 평가한다."""

    if condition is None:
        return True
    data = plan.model_dump(mode="json") if isinstance(plan, AnalysisPlan) else plan
    if condition.all is not None:
        return all(condition_matches(item, data) for item in condition.all)
    if condition.any is not None:
        return any(condition_matches(item, data) for item in condition.any)
    current = value_at_path(data, condition.path or "")
    expected = condition.value
    return {
        "eq": lambda: current == expected,
        "neq": lambda: current != expected,
        "contains": lambda: expected in current if isinstance(current, (list, str)) else False,
        "not_contains": lambda: expected not in current if isinstance(current, (list, str)) else True,
        "in": lambda: current in expected if isinstance(expected, list) else False,
        "exists": lambda: current is not None,
        "not_empty": lambda: current not in (None, "", [], {}),
    }[condition.operator or "eq"]()


def value_at_path(value: Any, path: str) -> Any:
    """점·대괄호 경로로 딕셔너리와 목록의 값을 조회하고 유효하지 않거나 없는 경로는 None을 반환한다."""

    current = value
    parts = _path_parts(path)
    if not parts:
        return None
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _path_parts(path: str) -> list[str]:
    """대괄호 인덱스를 점 경로로 정규화하고 잘못된 괄호나 금지 경로 요소를 걸러낸다."""

    normalized = re.sub(r"\[(\d+)\]", r".\1", path)
    if "[" in normalized or "]" in normalized:
        return []
    parts = [part for part in normalized.split(".") if part]
    if any(part in {"__proto__", "prototype", "constructor"} for part in parts):
        return []
    return parts


def block_is_required(block: UiBlock, plan: AnalysisPlan) -> bool:
    """고정 필수 여부 또는 조건부 필수 규칙을 평가해 해당 UI 블록의 입력 필요 여부를 반환한다."""

    return block.required or (block.required_if is not None and condition_matches(block.required_if, plan))


def compute_missing_fields(plan: AnalysisPlan, ui_blocks: list[UiBlock]) -> list[str]:
    """현재 표시되는 필수 입력 블록에서 값이 비어 있는 필드 경로를 중복 없이 반환한다."""

    missing: list[str] = []
    data = plan.model_dump(mode="json")
    for block in ui_blocks:
        if block.visible_if is not None and not condition_matches(block.visible_if, plan):
            continue
        # review·notice는 정보 표시용이며 분석 계획의 입력 필드와 연결되지 않는다.
        # LLM이 required를 지정했더라도 연결되지 않은 안내 블록을
        # 사용자가 채울 수 없는 필수 입력으로 처리하지 않는다.
        if block.field_path is None and block.type in {"review", "notice"}:
            continue
        if not block_is_required(block, plan):
            continue
        path = block.field_path or block.key
        if value_at_path(data, path) in (None, "", [], {}):
            missing.append(path)
    return list(dict.fromkeys(missing))
