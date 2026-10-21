"""LLM 응답의 구조·타입·필드·UI 원시 값을 복구하고 모델로 검증한다."""

from __future__ import annotations

import types
from copy import deepcopy
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from app.planning.analysis_models import AnalysisPlan, FieldSource, FieldStatus
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


_DATE_RANGE_SUBFIELDS = {"mode", "preset", "relative_days", "date_from", "date_to"}


_FIELD_PATH_TYPE_FALLBACK: list[tuple[str, str]] = [
    ("date_range", "date_range"),
    ("event_types", "multi_select"),
    ("group_by", "multi_select"),
    ("target_conditions", "textarea"),
    ("metric", "option_cards"),
    ("metrics", "option_cards"),
    ("comparison", "choice"),
    ("output", "choice"),
]


def _coerce_block_type(raw_type: Any, field_path: str | None) -> str:
    """잘못된 UI 타입을 날짜 하위 필드나 연결 경로에 따라 보정하고 판단할 수 없으면 text로 대체한다."""

    if raw_type in _VALID_COMPONENT_TYPES:
        return raw_type
    if raw_type in _DATE_RANGE_SUBFIELDS:
        return "date_range"
    if isinstance(field_path, str):
        for prefix, fallback_type in _FIELD_PATH_TYPE_FALLBACK:
            if field_path == prefix or field_path.startswith(f"{prefix}."):
                return fallback_type
    return "text"


_DROP = object()


def _wrap_scalar_as_model(data: Any, model_cls: type[BaseModel]) -> dict[str, Any] | None:
    """value와 label이 있는 모델에 단일 값이 전달되면 두 필드를 가진 객체로 감싼다."""

    if not isinstance(data, (str, int, float, bool)):
        return None
    fields = model_cls.model_fields
    if "value" in fields and "label" in fields:
        return {"value": str(data), "label": str(data)}
    return None


def _sanitize_value(data: Any, annotation: Any) -> Any:
    """타입 선언을 재귀적으로 따라 LLM 응답의 잘못된 필드·선택값·객체 형태를 제거하거나 보정한다."""

    if data is None:
        return None

    origin = get_origin(annotation)

    if origin is Union or origin is types.UnionType:
        args = get_args(annotation)
        non_none = [arg for arg in args if arg is not type(None)]
        nullable = type(None) in args
        model_args = [arg for arg in non_none if isinstance(arg, type) and issubclass(arg, BaseModel)]
        if model_args and isinstance(data, dict):
            tag = data.get("mode")
            for candidate in model_args:
                disc_field = candidate.model_fields.get("mode")
                if disc_field is not None and tag in get_args(disc_field.annotation):
                    return _sanitize_value(data, candidate)
            # 여러 모델 중 mode 값과 일치하는 모델이 없을 때만 변환을 중단한다.
            # MetricSpec | None처럼 선택 가능한 모델이 하나뿐인 경우에는
            # 아래의 단일 타입 처리 분기로 넘겨 정상적인 객체를 유지한다.
            # 이 경우까지 None으로 바꾸면 LLM이 생성한 유효한 지표가 사라진다.
            if len(model_args) > 1:
                return None if nullable else _DROP
        if len(non_none) == 1:
            result = _sanitize_value(data, non_none[0])
            if result is _DROP:
                return None if nullable else _DROP
            return result
        return data

    if origin is list:
        (item_type,) = get_args(annotation) or (Any,)
        if not isinstance(data, list):
            return _DROP
        cleaned_items = []
        for item in data:
            sanitized = _sanitize_value(item, item_type)
            if sanitized is not _DROP:
                cleaned_items.append(sanitized)
        return cleaned_items

    if origin is dict:
        args = get_args(annotation)
        value_type = args[1] if len(args) == 2 else Any
        if not isinstance(data, dict):
            return _DROP
        cleaned_dict = {}
        for key, value in data.items():
            sanitized = _sanitize_value(value, value_type)
            if sanitized is not _DROP:
                cleaned_dict[key] = sanitized
        return cleaned_dict

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if not isinstance(data, dict):
            wrapped = _wrap_scalar_as_model(data, annotation)
            if wrapped is None:
                return _DROP
            data = wrapped
        cleaned_obj = {}
        for key, field in annotation.model_fields.items():
            if key not in data:
                continue
            sanitized = _sanitize_value(data[key], field.annotation)
            if sanitized is not _DROP:
                cleaned_obj[key] = sanitized
        return cleaned_obj

    if origin is Literal:
        allowed = get_args(annotation)
        return data if data in allowed else _DROP

    return data


def _sanitize_for_model(data: dict[str, Any], model_cls: type[BaseModel]) -> dict[str, Any]:
    """지정한 Pydantic 모델 기준으로 응답을 정리하고 딕셔너리 형태의 결과를 반환한다."""

    sanitized = _sanitize_value(data, model_cls)
    return sanitized if isinstance(sanitized, dict) else data


def _canonicalize_planner_output(result: Any, question: str) -> DynamicPlannerOutput:
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
        if key in payload:
            raw_plan[key] = payload[key]
    raw_plan["original_question"] = question

    root_metadata = payload.get("field_metadata")
    plan_metadata = raw_plan.get("field_metadata")
    merged_metadata = _repair_raw_field_metadata({
        **(plan_metadata if isinstance(plan_metadata, dict) else {}),
        **(root_metadata if isinstance(root_metadata, dict) else {}),
    })
    raw_plan["field_metadata"] = merged_metadata
    raw_plan = _sanitize_for_model(raw_plan, AnalysisPlan)
    merged_metadata = raw_plan.get("field_metadata", merged_metadata)

    canonical = {
        "analysis_plan": raw_plan,
        "ui_blocks": _repair_raw_ui_blocks(payload.get("ui_blocks")),
        "missing_fields": _string_list(payload.get("missing_fields")),
        "field_metadata": merged_metadata,
        "suggested_constraints": _repair_raw_suggestions(payload.get("suggested_constraints")),
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
        raw["status"] = _coerce_field_status(raw.get("status"))
        raw["source"] = _coerce_field_source(raw.get("source"))
        repaired[str(field)] = raw
    return repaired


def _repair_raw_ui_blocks(value: Any) -> list[dict[str, Any]]:
    """UI 경로·타입·선택지·조건·키를 보정하고 연결할 필드가 없는 입력 블록을 제외한 뒤 검증한다."""

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
            raw["field_path"] = path if _EDITABLE_PLAN_PATH.fullmatch(path) else None
        raw["type"] = _coerce_block_type(raw.get("type"), raw.get("field_path"))
        # 분석 필드에 연결되지 않은 입력 블록은 값을 반영할 수 없으므로 제외한다.
        # LLM이 설명 필드에 연결한 날짜 입력이나 임의의 확인 체크박스가 여기에 해당한다.
        # review·notice처럼 정보만 표시하는 블록은 연결할 필드 없이도 유지한다.
        if raw.get("field_path") is None and raw["type"] not in {"review", "notice"}:
            continue
        props = raw.get("props") if isinstance(raw.get("props"), dict) else {}
        if not raw.get("options") and isinstance(props.get("options"), list):
            raw["options"] = props["options"]
        raw_options = raw.get("options")
        if isinstance(raw_options, list):
            flattened: list[dict[str, Any]] = []
            saw_collection = False
            for option in raw_options:
                if not isinstance(option, dict) or "value" not in option:
                    continue
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
        candidate = base_key
        suffix = 2
        while candidate in used_keys:
            candidate = f"{base_key}_{suffix}"[:100]
            suffix += 1
        raw["key"] = candidate
        used_keys.add(candidate)
        if not raw.get("label"):
            raw["label"] = str(raw.get("field_path") or raw["key"])
        raw = _sanitize_for_model(raw, UiBlock)
        block = UiBlock.model_validate(raw)
        repaired.append(block.model_dump(mode="json"))
    return repaired


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
            raw["field_path"] = path if _EDITABLE_PLAN_PATH.fullmatch(path) else None
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
