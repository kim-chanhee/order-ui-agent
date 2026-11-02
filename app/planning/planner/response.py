"""LLM 응답의 구조·타입·필드·UI 원시 값을 복구하고 모델로 검증한다."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, get_args

from pydantic import BaseModel

from app.planning.analysis_models import AnalysisPlan, FieldMetadata, FieldSource, FieldStatus
from app.planning.ui_models import (
    ComponentType,
    DynamicPlannerOutput,
    InfeasibleCondition,
    SuggestedConstraint,
    UiBlock,
    _EDITABLE_PLAN_PATH,
)
from app.planning.planner.controls import _FIELD_PATH_PREFIX


_VALID_COMPONENT_TYPES = set(get_args(ComponentType))


_DROP = object()


def _canonicalize_planner_output(result: Any, question: str, *, include_ui: bool = True) -> DynamicPlannerOutput:
    """루트에 잘못 배치된 계획 필드와 UI·메타데이터를 복구한 뒤 표준 응답 모델로 검증한다."""

    if isinstance(result, BaseModel):
        payload = result.model_dump(mode="json", exclude_none=True)
    elif isinstance(result, dict):
        payload = deepcopy(result)
    else:
        raise TypeError("planner response must be an object")

    raw_plan = payload.get("analysis_plan")
    if isinstance(raw_plan, BaseModel):
        raw_plan = raw_plan.model_dump(mode="json")
    if not isinstance(raw_plan, dict):
        raw_plan = {}
    else:
        raw_plan = deepcopy(raw_plan)

    # LLM이 계획 필드를 응답 최상위에 잘못 배치했으면 계획 내부로 옮긴다.
    # 이 단계는 응답 구조만 보정하며 새로운 분석 의미를 추가하지 않는다.
    for key in AnalysisPlan.model_fields:
        if key != "field_metadata" and key in payload:
            raw_plan[key] = payload[key]
    raw_plan["original_question"] = question

    root_metadata = payload.get("field_metadata")
    plan_metadata = raw_plan.get("field_metadata")
    merged_metadata = _repair_raw_field_metadata({
        **(plan_metadata if isinstance(plan_metadata, dict) else {}),
        **(root_metadata if isinstance(root_metadata, dict) else {}),
    })
    raw_plan["field_metadata"] = merged_metadata
    # Preserve semantic values for strict validation; invalid conditions must not disappear.
    raw_plan = AnalysisPlan.model_validate(raw_plan).model_dump(mode="json")
    merged_metadata = raw_plan.get("field_metadata", merged_metadata)

    canonical = {
        "analysis_plan": raw_plan,
        "ui_blocks": _repair_raw_ui_blocks(payload.get("ui_blocks"), plan=raw_plan) if include_ui else [],
        "missing_fields": _string_list(payload.get("missing_fields")),
        "field_metadata": merged_metadata,
        "suggested_constraints": _repair_raw_suggestions(payload.get("suggested_constraints")) if include_ui else [],
        "infeasible": _repair_raw_infeasible(payload.get("infeasible")),
        "summary": str(payload.get("summary") or "요청한 분석 조건을 구조화했습니다."),
        "warnings": _string_list(payload.get("warnings")),
        "requires_confirmation": bool(payload.get("requires_confirmation", True)),
    }
    return DynamicPlannerOutput.model_validate(canonical)


_VALID_FIELD_STATUSES = set(get_args(FieldStatus))


_VALID_FIELD_SOURCES = set(get_args(FieldSource))


_FIELD_STATUS_SYNONYMS = {
    "inherited": "inferred", "carried": "inferred", "carried_forward": "inferred",
    "ready": "inferred", "available": "inferred", "resolved": "inferred", "complete": "inferred",
    "auto": "inferred", "default": "inferred", "assumed": "inferred",
    "required": "needs_confirmation", "unresolved": "needs_confirmation", "pending": "needs_confirmation",
    "ambiguous": "needs_confirmation", "uncertain": "needs_confirmation",
    "empty": "missing", "unset": "missing", "not_set": "missing", "none": "missing",
    "confirmed": "explicit", "user_provided": "explicit", "given": "explicit", "stated": "explicit",
    "edited": "user_modified", "modified": "user_modified", "changed": "user_modified",
}


_FIELD_SOURCE_SYNONYMS = {
    "inherited": "inherited_context", "previous_context": "inherited_context",
    "thread_context": "inherited_context", "carried_forward": "inherited_context",
    "llm": "llm_inferred", "model": "llm_inferred", "inferred": "llm_inferred",
    "user": "user_text", "user_input": "user_text", "text": "user_text",
    "selected": "user_selected", "user_choice": "user_selected",
    "additional_constraint": "user_additional_constraint",
}


def _coerce_field_status(raw_status: Any) -> str:
    """필드 상태의 유사 표현을 허용된 상태값으로 변환하고 알 수 없는 값은 inferred로 처리한다."""

    if raw_status in _VALID_FIELD_STATUSES:
        return raw_status
    key = str(raw_status or "").strip().lower()
    return _FIELD_STATUS_SYNONYMS.get(key, "inferred")


def _coerce_field_source(raw_source: Any) -> str | None:
    """필드 출처의 유사 표현을 허용된 출처값으로 변환하고 알 수 없는 값은 llm_inferred로 처리한다."""

    if raw_source is None or raw_source in _VALID_FIELD_SOURCES:
        return raw_source
    key = str(raw_source).strip().lower()
    return _FIELD_SOURCE_SYNONYMS.get(key, "llm_inferred")


def _repair_raw_field_metadata(value: dict[str, Any]) -> dict[str, Any]:
    """필드별 메타데이터를 딕셔너리로 정리하고 상태와 출처를 허용된 값으로 보정한다."""

    repaired: dict[str, Any] = {}
    for field, item in value.items():
        raw = item.model_dump(mode="json") if isinstance(item, BaseModel) else deepcopy(item)
        if not isinstance(raw, dict):
            continue
        # Metadata is provenance only. Ignore model-added presentation hints;
        # semantic plan fields are still validated strictly by AnalysisPlan.
        raw = {key: item for key, item in raw.items() if key in FieldMetadata.model_fields}
        raw["status"] = _coerce_field_status(raw.get("status"))
        raw["source"] = _coerce_field_source(raw.get("source"))
        repaired[str(field)] = raw
    return repaired


def _repair_raw_ui_blocks(value: Any, *, plan: dict | None = None) -> list[dict[str, Any]]:
    """Repair known transport aliases; never invent or replace a plan selection."""

    if not isinstance(value, list):
        return []
    repaired: list[dict[str, Any]] = []
    allowed = set(UiBlock.model_fields)
    used_keys: set[str] = set()
    for item in value:
        if isinstance(item, BaseModel):
            raw = item.model_dump(mode="json", exclude_none=True)
        elif isinstance(item, dict):
            raw = deepcopy(item)
        else:
            continue
        if not raw.get("field_path") and raw.get("field"):
            raw["field_path"] = raw["field"]
        path = raw.get("field_path")
        if isinstance(path, str):
            path = path.removeprefix(_FIELD_PATH_PREFIX)
            # summary처럼 편집할 수 없는 설명 필드를 가리키는 경로는 해제한다.
            # 하나의 잘못된 연결 때문에 전체 계획을 실패시키지 않고
            # 연결을 해제한 뒤 아래 단계에서 블록 유형에 따라 유지 여부를 결정한다.
            if not _EDITABLE_PLAN_PATH.fullmatch(path):
                raise ValueError(f"UI Block targets a forbidden path: {path}")
            raw["field_path"] = path
        # These are field names incorrectly emitted as types, not new components.
        aliases = {"group_by": ("group_by", "multi_select"), "metric": ("metric.kind", "choice")}
        alias = aliases.get(raw.get("type"))
        if alias and path == alias[0]:
            raw["type"] = alias[1]
        if raw.get("type") == "sort" and isinstance(path, str) and re.fullmatch(r"sort(?:\[\d+\]|\.\d+)\.direction", path):
            raw["type"] = "choice"
        if raw.get("type") not in _VALID_COMPONENT_TYPES:
            raise ValueError("UI Block type is not registered in the component catalog")
        # 분석 필드에 연결되지 않은 입력 블록은 값을 반영할 수 없으므로 제외한다.
        # LLM이 설명 필드에 연결한 날짜 입력이나 임의의 확인 체크박스가 여기에 해당한다.
        # review·notice처럼 정보만 표시하는 블록은 연결할 필드 없이도 유지한다.
        if raw.get("field_path") is None and raw["type"] not in {"review", "notice"}:
            raise ValueError("Input blocks require an editable AnalysisPlan field_path")
        props = raw.get("props") if isinstance(raw.get("props"), dict) else {}
        selected = _transport_plan_value(plan, path)
        _remove_matching_selection_copy(raw, selected, path)
        props = dict(props)
        _remove_matching_selection_copy(props, selected, path)
        raw["props"] = props
        if not raw.get("options") and isinstance(props.get("options"), list):
            raw["options"] = props["options"]
        raw_options = raw.get("options")
        if isinstance(raw_options, list):
            flattened: list[dict[str, Any]] = []
            saw_collection = False
            for option in raw_options:
                if not isinstance(option, dict) or "value" not in option:
                    continue
                option = dict(option)
                for key in list(option):
                    if key.lower() in {"default", "selected", "checked"}:
                        flag = option.pop(key)
                        values = selected if isinstance(selected, list) else [selected]
                        if not isinstance(flag, bool) or selected is _DROP or flag != (option["value"] in values):
                            raise ValueError(f"UI option selection conflicts with AnalysisPlan: {path}")
                values = option.get("value")
                if isinstance(values, list):
                    saw_collection = True
                    for scalar in values:
                        if isinstance(scalar, (str, int, float, bool)):
                            flattened.append({
                                "value": str(scalar),
                                "label": str(scalar),
                                **({"description": option["description"]} if option.get("description") else {}),
                            })
                elif isinstance(values, (str, int, float, bool)):
                    flattened.append({**option, "value": str(values), "label": str(option.get("label") or values)})
            if flattened:
                raw["options"] = list({item["value"]: item for item in flattened}.values())
            if saw_collection and raw.get("type") in {"select", "choice", "option_cards"}:
                raw["type"] = "multi_select"
        for condition_key in ("visible_if", "required_if"):
            if isinstance(raw.get(condition_key), dict):
                raw[condition_key] = _repair_raw_condition(raw[condition_key])
        raw = {key: raw[key] for key in allowed if key in raw}
        if not raw.get("key"):
            raw["key"] = str(raw.get("field_path") or "review").replace(".", "_")[:100]
        base_key = str(raw["key"])
        if base_key in used_keys:
            raise ValueError('UI Block key must be unique')
        used_keys.add(base_key)
        if not raw.get("label"):
            raw["label"] = str(raw.get("field_path") or raw["key"])
        block = UiBlock.model_validate(raw)
        repaired.append(block.model_dump(mode="json"))
    return repaired


def _transport_plan_value(plan: dict | None, path: Any) -> Any:
    if not isinstance(plan, dict) or not isinstance(path, str):
        return _DROP
    current: Any = plan
    try:
        for part in re.sub(r"\[(\d+)\]", r".\1", path).split("."):
            current = current[int(part)] if isinstance(current, list) else current[part]
        return current
    except (KeyError, IndexError, TypeError, ValueError):
        return _DROP


def _remove_matching_selection_copy(data: dict, selected: Any, path: Any) -> None:
    for key in list(data):
        if key.lower() not in {"value", "selected", "default", "default_value", "defaultvalue", "checked"}:
            continue
        value = data.pop(key)
        matches = selected is not _DROP and (value == selected or isinstance(selected, list) and len(selected) == 1 and value == selected[0])
        if not matches:
            raise ValueError(f"UI selection conflicts with AnalysisPlan: {path}")


def _repair_raw_condition(value: dict[str, Any]) -> dict[str, Any]:
    """조건의 경로·연산자 별칭과 중첩 그룹을 표준 조건 구조로 변환한다."""

    raw = deepcopy(value)
    if "path" not in raw:
        alias = raw.pop("field_path", None) or raw.pop("field", None)
        if alias:
            raw["path"] = alias
    operator_aliases = {
        "equals": "eq", "not_equals": "neq", "includes": "contains",
        "not_includes": "not_contains", "is_set": "exists", "non_empty": "not_empty",
    }
    if raw.get("operator") in operator_aliases:
        raw["operator"] = operator_aliases[raw["operator"]]
    for group_key in ("all", "any"):
        if isinstance(raw.get(group_key), list):
            raw[group_key] = [
                _repair_raw_condition(item) for item in raw[group_key] if isinstance(item, dict)
            ]
    allowed = {"path", "operator", "value", "all", "any"}
    return {key: raw[key] for key in allowed if key in raw}


def _repair_raw_suggestions(value: Any) -> list[dict[str, Any]]:
    """추천 조건 목록을 모델로 검증하고 잘못된 항목을 제외한 직렬화 결과를 반환한다."""

    if not isinstance(value, list):
        return []
    repaired: list[dict[str, Any]] = []
    for item in value:
        raw = item.model_dump(mode="json") if isinstance(item, BaseModel) else item
        if not isinstance(raw, dict):
            continue
        try:
            repaired.append(SuggestedConstraint.model_validate(raw).model_dump(mode="json"))
        except Exception:
            continue
    return repaired


def _repair_raw_infeasible(value: Any) -> list[dict[str, Any]]:
    """조회 불가 사유의 문자열·경로·이름을 보정하고 유효한 항목을 최대 12개 반환한다."""

    if not isinstance(value, list):
        return []
    repaired: list[dict[str, Any]] = []
    for item in value:
        raw = item.model_dump(mode="json") if isinstance(item, BaseModel) else deepcopy(item)
        if isinstance(raw, str):
            raw = {"label": raw[:200], "reason": raw}
        if not isinstance(raw, dict):
            continue
        path = raw.get("field_path") or raw.get("field")
        if isinstance(path, str):
            path = path.removeprefix(_FIELD_PATH_PREFIX)
            # An explanatory diagnostic is not an editable input. Preserve its
            # reason even when its target is a read-only semantic plan field.
            if not _EDITABLE_PLAN_PATH.fullmatch(path):
                path = None
            raw["field_path"] = path
        raw.setdefault("label", str(raw.get("reason") or "확인 필요")[:200])
        try:
            repaired.append(InfeasibleCondition.model_validate(raw).model_dump(mode="json"))
        except Exception:
            continue
    return repaired[:12]


def _string_list(value: Any) -> list[str]:
    """목록의 항목을 문자열로 변환하고 공백·빈 값·중복을 제거한다."""

    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
