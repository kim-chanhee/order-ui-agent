"""실행 결과의 컬럼과 행이 계획의 요청 속성·결과 단위에 맞는지 검사한다.

주요 검사는 사람이 읽을 이름 컬럼의 존재, 원치 않은 이력 속성의 포함,
식별 가능한 고유 결과 단위의 중복, 명시적으로 제외한 속성의 노출이다.
대상 엔터티와 컬럼의 의미는 analysis_semantics 설정과 이름 규칙으로 해석한다.
요청 속성이 없는 계획은 현재 검사 대상에서 제외하며, 모든 분석의 정답을 증명하지는 않는다.
위반하면 ResultContractViolation을 던져 에이전트가 결과를 채택하기 전에 SQL을 수정하게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.execution.analysis_semantics import load_analysis_semantics


@dataclass(frozen=True)
class ResultContractViolation(ValueError):
    """결과의 속성이나 행 단위가 계획과 어긋난 이유를 코드·상세 메시지로 표현한다.

    실행 도구는 이 예외를 오류 문자열로 바꿔 LLM에 SQL 수정을 요청한다.
    """

    code: str
    detail: str

    def __str__(self) -> str:
        """결과 계약 오류의 코드와 상세 사유를 한 문자열로 묶는다.

        로그와 도구 오류에서 위반 종류를 함께 확인할 수 있게 한다.
        """

        return f"[{self.code}] {self.detail}"


def validate_result_contract(
    confirmed_plan: Any | None,
    *,
    columns: list[str],
    rows: list[dict[str, Any]],
) -> None:
    """계획의 요청 속성을 실제 결과 컬럼과 행에 대조한다.

    표시 이름 누락·불필요한 이력 속성·확인 가능한 고유 키 중복·제외 속성 노출을 검사한다.
    요청 속성이 없으면 검사를 생략하고, 위반하면 ResultContractViolation을 발생시킨다.
    """

    plan = _as_mapping(confirmed_plan)
    if not plan:
        return
    requested = {_normalize(value) for value in plan.get("requested_attributes", []) if value}
    if not requested:
        return

    semantics = load_analysis_semantics()
    roles = {
        _normalize(role): {_normalize(field) for field in fields if field}
        for role, fields in (semantics.get("attribute_roles") or {}).items()
        if isinstance(fields, list)
    }
    normalized_columns = {_normalize(column): column for column in columns}

    if "display_name" in requested:
        display_fields = set(roles.get("display_name", set()))
        entity = _entity_definition(plan.get("target_entity"), semantics)
        if entity:
            display_fields.update(
                _normalize(field) for field in entity.get("display_name_fields", []) if field
            )
        display_columns = [
            original
            for normalized, original in normalized_columns.items()
            if normalized in display_fields or normalized.endswith("_name") or normalized.endswith("_label")
        ]
        if not display_columns:
            raise ResultContractViolation(
                "missing_display_name",
                "confirmed plan requests a human-readable display_name, but the result exposes no verified name/label field",
            )

        history_fields = {
            _normalize(field)
            for table in (semantics.get("table_grains") or {}).values()
            if isinstance(table, dict)
            for field in table.get("history_fields", [])
            if field
        }
        requested_fields = set().union(*(roles.get(role, set()) for role in requested))
        unexpected_history = sorted(
            original
            for normalized, original in normalized_columns.items()
            if normalized in history_fields and normalized not in requested_fields
        )
        if unexpected_history:
            raise ResultContractViolation(
                "unexpected_history_attributes",
                "display-name result includes unrequested history/measure fields: "
                + ", ".join(unexpected_history),
            )

        grain = _normalize(plan.get("result_grain"))
        if grain.startswith("distinct_") or grain.startswith("unique_"):
            identifier_fields = {
                _normalize(field) for field in entity.get("identifier_fields", []) if field
            }
            key_columns = [
                original
                for normalized, original in normalized_columns.items()
                if normalized in identifier_fields
            ]
            # A product's configured display field may itself be its stable key.
            # For item-level rows, repeated product names are legitimate because
            # different items can share the same product type; only item_id can
            # prove item-grain uniqueness.
            if not key_columns and _normalize(plan.get("target_entity")) == "product":
                key_columns = [display_columns[0]]
            keys = [
                tuple(str(row.get(column)) for column in key_columns)
                for row in rows
                if key_columns and any(row.get(column) not in (None, "") for column in key_columns)
            ]
            if keys and len(keys) != len(set(keys)):
                raise ResultContractViolation(
                    "result_grain_mismatch",
                    f"confirmed grain {plan.get('result_grain')!r} requires unique entity keys, "
                    f"but {', '.join(key_columns)!r} is duplicated",
                )

    excluded = {_normalize(value) for value in plan.get("excluded_attributes", []) if value}
    excluded_fields = set().union(*(roles.get(role, {role}) for role in excluded)) if excluded else set()
    present_excluded = sorted(
        original for normalized, original in normalized_columns.items() if normalized in excluded_fields
    )
    if present_excluded:
        raise ResultContractViolation(
            "excluded_attribute_present",
            "result includes attributes excluded by the confirmed plan: " + ", ".join(present_excluded),
        )


def _as_mapping(value: Any | None) -> dict[str, Any]:
    """Pydantic 모델을 JSON 호환 딕셔너리로 바꾸거나 기존 딕셔너리를 그대로 반환한다.

    값이 없거나 지원하지 않는 자료형이면 빈 딕셔너리로 처리한다.
    """

    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return value if isinstance(value, dict) else {}


def _entity_definition(value: Any, semantics: dict[str, Any]) -> dict[str, Any]:
    """대상 이름을 의미 설정의 엔터티 이름·동의어와 비교해 해당 정의를 찾는다.

    일치하는 정의가 없으면 빈 딕셔너리를 반환한다.
    """

    target = _normalize(value)
    if not target:
        return {}
    for name, raw in (semantics.get("entity_roles") or {}).items():
        if not isinstance(raw, dict):
            continue
        terms = {_normalize(name), *(_normalize(term) for term in raw.get("semantic_terms", []))}
        if target in terms:
            return raw
    return {}


def _normalize(value: Any) -> str:
    """속성·엔터티·컬럼 이름의 대소문자·공백·하이픈 차이를 정리한다.

    비교에 사용할 소문자 언더스코어 문자열을 반환한다.
    """

    return "_".join(str(value or "").strip().casefold().replace("-", " ").split())
