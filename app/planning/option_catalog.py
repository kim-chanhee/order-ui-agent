"""스키마와 현재 분석 계획에 근거한 확인 화면 선택지를 만든다.

주요 기능:
    - 스키마 텍스트에서 컬럼과 이벤트 값을 추출해 집계 기준·건수 단위를 구성한다.
    - 현재 선택값을 보존하면서 카탈로그 선택지를 보충하고 중복을 제거한다.
    - 이벤트·집계 기준·건수 단위를 화면용 이름으로 변환한다.
    - 비교 방식과 결과 표시 형식에 사용할 기본 선택지를 제공한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.execution.semantic_aliases import canonical_value_labels
from app.planning.analysis_models import AnalysisPlan
from app.planning.ui_models import UiOption


_LOW_CARDINALITY_VALUE = re.compile(r"(?:^|,\s*)(.+?)\s+\(\d+\)(?=,|$)")
_PROFILE_VALUE_LINE = re.compile(r"^\s*-\s+(event_type|ocel_type):\s+(.+)$")
_TABLE_HEADER_LINE = re.compile(r"^TABLE:\s+(\S+)\s*$")
_COLUMN_LINE = re.compile(
    r"^\s*-\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:TEXT|NUM|INTEGER|INT|REAL|FLOAT|DOUBLE|DATE|DATETIME|TIMESTAMP|VARCHAR|\(no declared type\))",
    re.MULTILINE | re.IGNORECASE,
)
_TABLE_SIGNATURE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\(([^\n]+)\)$", re.MULTILINE)

_DIMENSION_LABELS = {
    "customer": "고객별",
    "courier": "배송 기사별",
    "shipper": "배송 기사별",
    "employee": "직원별",
    "product": "상품별",
    "item": "물품별",
    "order": "주문별",
    "package": "패키지별",
    "event": "이벤트별",
    "event_type": "이벤트 유형별",
    "status": "상태별",
    "day": "일자별",
}
_COUNT_FIELD_LABELS = {
    "event_id": "이벤트 발생 기준",
    "order_id": "주문 기준",
    "item_id": "물품 기준",
    "product_id": "상품 기준",
    "package_id": "패키지 기준",
    "customer_id": "고객 기준",
    "courier_id": "배송 기사 기준",
    "shipper_id": "배송 기사 기준",
    "employee_id": "직원 기준",
}

COMPARISON_OPTIONS = [
    UiOption(value="event_vs_event", label="이벤트 간 비교", description="두 이벤트나 상태를 같은 기준으로 비교합니다."),
    UiOption(value="breakdown", label="항목별 분포", description="선택한 대상을 유형별로 나눠 봅니다."),
    UiOption(value="none", label="비교 없음", description="선택한 대상만 조회합니다."),
]
OUTPUT_VIEW_OPTIONS = [
    UiOption(value="summary", label="요약"),
    UiOption(value="table", label="표"),
    UiOption(value="chart", label="차트"),
    UiOption(value="table_and_chart", label="표와 차트"),
]


@dataclass(frozen=True)
class PlanOptionCatalog:
    """이벤트 유형·집계 기준·건수 단위·비교 방식의 화면 선택지를 묶는다."""

    event_types: list[UiOption]
    group_by: list[UiOption]
    count_fields: list[UiOption]
    comparisons: list[UiOption]


def build_plan_option_catalog(schema_text: str, plan: AnalysisPlan) -> PlanOptionCatalog:
    """스키마에서 확인한 값과 현재 계획의 선택값으로 이벤트·집계 기준·건수 단위·비교 선택지를 만든다."""

    columns = _schema_columns(schema_text)
    events = _event_values(schema_text)
    event_options = _dedupe_by_label(_options_with_selected(
        plan.event_types,
        events,
        labeler=_event_label,
    ))
    group_candidates = _group_candidates(columns)
    group_options = _dedupe_by_label(_options_with_selected(
        plan.group_by,
        group_candidates,
        labeler=_dimension_label,
    ))
    count_candidates = [column for column in columns if column in _COUNT_FIELD_LABELS]
    selected_count = [plan.metric.field] if plan.metric and plan.metric.field else []
    count_options = _options_with_selected(
        selected_count,
        count_candidates,
        labeler=_count_field_label,
    )
    comparison_options = list(COMPARISON_OPTIONS)
    if plan.comparison and plan.comparison not in {option.value for option in comparison_options}:
        comparison_options.insert(0, UiOption(
            value=plan.comparison,
            label="현재 비교 방식",
            description=plan.comparison.replace("_", " "),
        ))
    return PlanOptionCatalog(
        event_types=event_options[:15],
        group_by=group_options[:12],
        count_fields=count_options[:10],
        comparisons=comparison_options,
    )


def merge_options(preferred: list[UiOption], available: list[UiOption]) -> list[UiOption]:
    """값이 같은 선택지는 기존 문구를 우선하고 카탈로그의 나머지 선택지를 뒤에 보충한다."""

    merged: dict[str, UiOption] = {}
    for option in [*preferred, *available]:
        if option.value not in merged:
            merged[option.value] = option
    return list(merged.values())


def _schema_columns(text: str) -> list[str]:
    """컬럼 설명과 테이블 요약 형식에서 컬럼 이름을 추출해 중복 없이 반환한다."""

    values = list(_COLUMN_LINE.findall(text or ""))
    for signature in _TABLE_SIGNATURE.findall(text or ""):
        for raw_column in signature.split(","):
            name = raw_column.strip().split(" ", 1)[0]
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                values.append(name)
    return list(dict.fromkeys(values))


def _event_values(text: str) -> list[str]:
    # ocel_type의 값 분포는 이벤트 테이블과 객체 테이블에 모두 존재한다.
    # 이벤트 테이블에는 배송 실패 같은 이벤트 유형이, 객체 테이블에는
    # 물품·주문 같은 객체 유형이 있으므로 현재 TABLE 블록을 기준으로 구분한다.
    # 객체 유형이 이벤트 필터의 선택지에 섞이지 않도록 객체 테이블을 제외한다.
    """객체 테이블을 제외한 값 분포에서 이벤트 유형 값을 추출하고 중복을 제거한다."""

    values: list[str] = []
    current_table = ""
    for line in (text or "").splitlines():
        header = _TABLE_HEADER_LINE.match(line)
        if header:
            current_table = header.group(1).lower()
            continue
        if current_table.startswith("object"):
            continue
        match = _PROFILE_VALUE_LINE.match(line)
        if not match:
            continue
        values.extend(item.group(1).strip() for item in _LOW_CARDINALITY_VALUE.finditer(match.group(2)))
    return list(dict.fromkeys(value for value in values if value))


def _group_candidates(columns: list[str]) -> list[str]:
    """컬럼 이름에서 지원하는 대상 ID·이벤트 유형·날짜별 집계 기준 후보를 찾는다."""

    candidates: list[str] = []
    for column in columns:
        lowered = column.lower()
        root = lowered.removesuffix("_id")
        if lowered == "event_type":
            candidates.append(lowered)
        elif lowered.endswith("_id") and root in _DIMENSION_LABELS and root != "event":
            candidates.append(lowered)
        elif lowered.endswith(("_date", "_time", "_at")) and "day" not in candidates:
            candidates.append("day")
    return list(dict.fromkeys(candidates))


def _options_with_selected(selected: list[str], available: list[str], *, labeler) -> list[UiOption]:
    """현재 선택값을 앞에 유지해 가용 값과 합치고 화면 이름을 붙인 선택지로 변환한다."""

    values = list(dict.fromkeys(str(value).strip() for value in [*selected, *available] if str(value).strip()))
    return [UiOption(value=value, label=labeler(value)) for value in values]


def _dedupe_by_label(options: list[UiOption]) -> list[UiOption]:
    """표시 이름의 공백과 대소문자를 정규화해 같은 이름의 선택지를 하나만 남긴다."""

    unique: list[UiOption] = []
    seen: set[str] = set()
    for option in options:
        key = option.label.strip().casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(option)
    return unique


def _event_label(value: str) -> str:
    """이벤트 값의 표준 표시 이름을 찾고 없으면 밑줄을 공백으로 바꿔 반환한다."""

    label = canonical_value_labels().get(value.lower())
    return label or value.replace("_", " ")


def _dimension_label(value: str) -> str:
    """집계 기준 컬럼을 화면용 이름으로 변환하고 알 수 없는 값에는 별 접미사를 붙인다."""

    lowered = value.lower()
    root = lowered.removesuffix("_id")
    return _DIMENSION_LABELS.get(lowered) or _DIMENSION_LABELS.get(root) or f"{value}별"


def _count_field_label(value: str) -> str:
    """건수 집계 컬럼을 화면용 기준 이름으로 변환한다."""

    return _COUNT_FIELD_LABELS.get(value.lower(), f"{value} 기준")
