"""SQL과 분리된 의미 기반 분석 계획을 Pydantic 모델로 정의한다.

주요 기능:
    - 전체·사전 정의·상대·직접 지정 기간과 날짜 기준점을 표현하고 검증한다.
    - 지표, 필터, 정렬, 출력 형식, 필드 출처와 이전 분석 참조를 구조화한다.
    - 읽기 전용 실행 정책과 고유 대상 건수 집계를 강제하고 중복 항목을 정리한다.
    - 원본 질문 외의 계획 필드에 SQL 구문이 포함되지 않도록 검사한다.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FilterOperator = Literal["eq", "neq", "in", "not_in", "gte", "gt", "lte", "lt", "contains", "between"]
FieldStatus = Literal["explicit", "inferred", "needs_confirmation", "missing", "user_modified"]
FieldSource = Literal["user_text", "llm_inferred", "user_selected", "inherited_context", "user_additional_constraint"]


class StrictModel(BaseModel):
    """선언하지 않은 추가 필드를 거부하는 공통 모델."""

    model_config = ConfigDict(extra="forbid")


class AllTimeRange(StrictModel):
    """기간을 제한하지 않는 전체 데이터 조회 범위."""

    mode: Literal["all_time"]


class PresetRange(StrictModel):
    """이름으로 지정한 사전 정의 기간 범위."""

    mode: Literal["preset"]
    preset: str = Field(min_length=1, max_length=100)


class RelativeRange(StrictModel):
    """데이터 기준일을 바탕으로 최근 며칠을 조회할지 지정하는 기간 범위."""

    mode: Literal["relative"]
    relative_days: int = Field(ge=1, le=3650)


class CustomRange(StrictModel):
    """사용자가 시작일과 종료일을 직접 지정하는 기간 범위."""

    mode: Literal["custom"]
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def validate_order(self) -> "CustomRange":
        """직접 지정한 기간의 시작일이 종료일보다 늦으면 검증 오류를 발생시킨다."""

        if self.date_from > self.date_to:
            raise ValueError("date_from must be before or equal to date_to")
        return self


DateRangeSpec = Annotated[
    AllTimeRange | PresetRange | RelativeRange | CustomRange,
    Field(discriminator="mode"),
]


class DateAnchorSpec(StrictModel):
    """기간 계산 기준일과 실제로 해석된 시작일·종료일을 보관한다."""

    strategy: Literal["dataset_max", "fixed_date"] = "dataset_max"
    fixed_date: date | None = None
    resolved_anchor_at: str | None = None
    resolved_date_from: date | None = None
    resolved_date_to: date | None = None

    @model_validator(mode="after")
    def validate_anchor(self) -> "DateAnchorSpec":
        """날짜 기준 전략에 따라 고정 날짜의 필수 여부와 허용 여부를 검증한다."""

        if self.strategy == "fixed_date" and self.fixed_date is None:
            raise ValueError("fixed_date is required for a fixed_date anchor")
        if self.strategy == "dataset_max" and self.fixed_date is not None:
            raise ValueError("fixed_date is not allowed for a dataset_max anchor")
        return self


class MetricSpec(StrictModel):
    """집계 방식, 대상 필드, 중복 제거, 비율의 분자·분모와 최소 표본 수를 정의한다."""

    kind: Literal["rows", "count", "ratio", "sum", "avg", "min", "max"]
    unit: str | None = None
    distinct: bool | None = None
    field: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    minimum_sample_size: int | None = Field(default=None, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def normalize_count_unit(self) -> "MetricSpec":
        # rows는 실제 행 수를, count는 의미상 구분되는 대상·이벤트의 수를 나타낸다.
        # 테이블 관계를 확장해 같은 대상이 반복돼도 count의 집계 단위는 유지해야 한다.
        """대상 건수 지표는 관계 확장으로 중복 집계되지 않도록 distinct를 활성화한다."""

        if self.kind == "count":
            self.distinct = True
        return self


class FilterSpec(StrictModel):
    """분석 대상에 적용할 필드·비교 연산자·값과 조건의 출처를 담는다."""

    field: str = Field(min_length=1, max_length=200)
    operator: FilterOperator
    value: Any
    source: str | None = None


class SortSpec(StrictModel):
    """결과를 정렬할 필드와 오름차순·내림차순 방향을 정의한다."""

    field: str = Field(min_length=1, max_length=200)
    direction: Literal["asc", "desc"] = "desc"


class OutputSpec(StrictModel):
    """결과 표시 형식, 출력 필드와 요약 포함 여부를 정의한다."""

    view: Literal["summary", "table", "chart", "table_and_chart"] = "table"
    fields: list[str] = Field(default_factory=list)
    include_summary: bool = True


class FieldMetadata(StrictModel):
    """계획 필드의 입력 상태, 신뢰도, 출처와 화면용 설명을 담는다."""

    status: FieldStatus
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: FieldSource | None = None
    label: str | None = None
    description: str | None = None


class ContextReferenceSpec(StrictModel):
    """현재 질문이 참조하는 이전 분석 범위와 선택 근거·신뢰도·확인 필요 여부를 담는다."""

    scope_id: str = Field(min_length=1, max_length=100)
    source_question: str = Field(min_length=1, max_length=2000)
    evidence: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_confirmation: bool = False


class AnalysisPlan(StrictModel):
    """질문의 분석 의도를 기간·대상·지표·필터·출력 형식으로 구조화한다.

    SQL이나 물리적 조인 대신 분석 의미를 표현하며, 읽기 전용 실행 정책을 강제한다."""

    version: str = "4.0"
    original_question: str = Field(min_length=1)
    analysis_type: str = "schema_driven_query"
    date_range: DateRangeSpec | None = None
    date_anchor: DateAnchorSpec | None = None
    event_types: list[str] = Field(default_factory=list)
    target_conditions: list[str] = Field(default_factory=list)
    target_entity: str | None = Field(default=None, max_length=200)
    requested_attributes: list[str] = Field(default_factory=list, max_length=20)
    result_grain: str | None = Field(default=None, max_length=200)
    relationship_scope: str | None = Field(default=None, max_length=200)
    excluded_attributes: list[str] = Field(default_factory=list, max_length=20)
    metric: MetricSpec | None = None
    metrics: list[MetricSpec] = Field(default_factory=list, max_length=12)
    group_by: list[str] = Field(default_factory=list)
    filters: list[FilterSpec] = Field(default_factory=list)
    comparison: str | None = None
    sort: list[SortSpec] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=10_000)
    unresolved_constraints: list[str] = Field(default_factory=list)
    output: OutputSpec = Field(default_factory=OutputSpec)
    context_reference: ContextReferenceSpec | None = None
    field_metadata: dict[str, FieldMetadata] = Field(default_factory=dict)
    execution_policy: dict[str, Any] = Field(default_factory=lambda: {
        "database_access": "read_only",
        "schema_discovery": True,
        "query_check_required": True,
        "relative_time_anchor": "dataset_timeline_max",
    })
    source: str = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("execution_policy")
    @classmethod
    def enforce_execution_policy(cls, value: dict[str, Any]) -> dict[str, Any]:
        """읽기 전용 접근, 스키마 탐색, 쿼리 검사와 데이터 기준 상대 기간 정책을 강제한다."""

        policy = dict(value or {})
        policy.update(
            database_access="read_only",
            schema_discovery=True,
            query_check_required=True,
            relative_time_anchor="dataset_timeline_max",
        )
        return policy

    @field_validator(
        "event_types",
        "target_conditions",
        "requested_attributes",
        "excluded_attributes",
        "group_by",
        "unresolved_constraints",
    )
    @classmethod
    def dedupe_strings(cls, value: list[str]) -> list[str]:
        """문자열 목록의 앞뒤 공백과 빈 항목을 제거하고 순서를 유지해 중복을 정리한다."""

        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @model_validator(mode="after")
    def validate_semantics(self) -> "AnalysisPlan":
        """상대·사전 정의 기간의 데이터 기준점을 보장하고 계획 내 SQL 포함 여부를 검증한다."""

        if self.date_range and self.date_range.mode in {"preset", "relative"}:
            if self.date_anchor is None:
                self.date_anchor = DateAnchorSpec(strategy="dataset_max")
            elif self.date_anchor.strategy != "dataset_max":
                raise ValueError(f"{self.date_range.mode} date ranges require a dataset_max anchor")
        _reject_sql_payload(self.model_dump())
        return self

    @model_validator(mode="after")
    def normalize_metrics(self) -> "AnalysisPlan":
        """직렬화한 지표 내용이 같은 항목을 제거해 지표 목록의 중복을 정리한다."""

        unique: list[MetricSpec] = []
        seen: set[str] = set()
        for metric in self.metrics:
            key = metric.model_dump_json(exclude_none=True)
            if key not in seen:
                unique.append(metric)
                seen.add(key)
        self.metrics = unique
        return self


_SQL_KEYS = {"sql", "raw_sql", "statement", "query", "select", "join"}
_SQL_TEXT = re.compile(r"\b(?:select|with|insert|update|delete|drop|alter|attach|pragma)\b", re.I)
_SQL_STATEMENT_TEXT = re.compile(
    r"^\s*(?:select\b.+\bfrom\b|with\b.+\bselect\b|insert\s+into\b|"
    r"update\b.+\bset\b|delete\s+from\b|drop\s+(?:table|view)\b|"
    r"alter\s+table\b|attach\s+database\b|pragma\b)",
    re.I | re.S,
)


def _reject_sql_payload(value: Any, path: str = "analysis_plan") -> None:
    """계획을 재귀 탐색해 SQL 관련 키와 SQL로 보이는 문자열을 거부한다. 원본 질문 문자열은 허용한다."""

    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _SQL_KEYS:
                raise ValueError(f"{path}.{key} may not contain SQL")
            _reject_sql_payload(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sql_payload(child, f"{path}[{index}]")
    elif isinstance(value, str) and not path.endswith(".original_question"):
        text = value.strip()
        if _SQL_STATEMENT_TEXT.match(text) or ((";" in text or "--" in text) and _SQL_TEXT.search(text)):
            raise ValueError(f"{path} appears to contain SQL")
