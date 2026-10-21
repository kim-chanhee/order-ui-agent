"""분석 계획을 SQL 생성기와 검증기가 공유하는 실행 기준으로 정리한다.

TemporalExecutionContext는 기간 모드·일수·기준 테이블과 컬럼을 표현한다.
ConfirmedAnalysisContext는 질문·계획·화면 버전·기간 정보를 함께 전달한다.
두 모드 모두 이 모델을 사용하며, confirmed라는 이름이 사용자 확인 화면을 뜻하지는 않는다.
모델 자체의 필드 재할당은 막고 원본 계획은 깊은 복사하지만, 내부 객체까지 동결하지는 않는다.
선택적 의미 설정과 실제 DB의 최대 날짜를 이용해 상대 기간의 표시 날짜를 계산한다.
LLM에는 원래 질문을 보조 문맥으로, 분석 계획을 우선 기준으로 명시한다.
"""

from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import date
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.planning.analysis_models import AnalysisPlan, FieldMetadata
from app.data.database import DEFAULT_DB_PATH
from app.execution.analysis_semantics import timeline_anchor
from app.execution.sql_safety import create_read_only_connection


class TemporalExecutionContext(BaseModel):
    """실행에 사용할 기간 모드·일수·날짜 범위와 데이터 기준 테이블·컬럼을 묶는다.

    필드 재할당을 금지하고 상대 기간·직접 날짜 지정 모드의 필수값을 검증한다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["all_time", "preset", "relative", "custom"]
    relative_days: int | None = Field(default=None, ge=1, le=3650)
    date_from: date | None = None
    date_to: date | None = None
    anchor_strategy: Literal["dataset_max", "fixed_date"] | None = None
    anchor_table: str | None = None
    anchor_field: str | None = None
    resolved_anchor_at: str | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> "TemporalExecutionContext":
        """기간 모드에 맞는 필수값을 확인하는 Pydantic 후처리 검증기다.

        상대 기간의 일수, 직접 지정 기간의 시작·종료일, 상대·프리셋 기간의 dataset_max 기준을 검사한다.
        """

        if self.mode == "relative" and self.relative_days is None:
            raise ValueError("relative temporal context requires relative_days")
        if self.mode == "custom" and (self.date_from is None or self.date_to is None):
            raise ValueError("custom temporal context requires date_from and date_to")
        if self.mode in {"relative", "preset"} and self.anchor_strategy != "dataset_max":
            raise ValueError(f"{self.mode} temporal context requires dataset_max")
        return self

    @classmethod
    def from_plan(cls, plan: AnalysisPlan) -> "TemporalExecutionContext | None":
        """계획의 기간과 날짜 기준을 읽어 실행용 기간 모델로 변환한다.

        프리셋에서 일수를 추출하고 설정된 데이터 시간축의 테이블·컬럼을 연결한다.
        계획에 기간이 없으면 None을 반환한다.
        """

        date_range = plan.date_range
        if date_range is None:
            return None
        payload = date_range.model_dump(mode="json")
        relative_days = payload.get("relative_days")
        if date_range.mode == "preset":
            match = re.search(r"(?P<days>\d+)[_-]?days?", str(payload.get("preset", "")), re.I)
            relative_days = int(match.group("days")) if match else None
        configured_anchor = timeline_anchor() if plan.date_anchor and plan.date_anchor.strategy == "dataset_max" else None
        return cls(
            mode=date_range.mode,
            relative_days=relative_days,
            date_from=payload.get("date_from"),
            date_to=payload.get("date_to"),
            anchor_strategy=plan.date_anchor.strategy if plan.date_anchor else None,
            anchor_table=configured_anchor[0] if configured_anchor else None,
            anchor_field=configured_anchor[1] if configured_anchor else None,
            resolved_anchor_at=plan.date_anchor.resolved_anchor_at if plan.date_anchor else None,
        )


def resolve_plan_temporal_preview(plan: AnalysisPlan) -> AnalysisPlan:
    """상대·프리셋 기간을 데이터셋 최대 날짜 기준의 실제 시작·종료 날짜로 계산한다.

    설정된 시간축을 읽기 전용으로 조회하고 기존 date_anchor가 있으면 계산값을 반영한다.
    기준 설정·일수가 없거나 조회에 실패하면 계획을 그대로 반환한다.
    """

    if not plan.date_range or plan.date_range.mode not in {"relative", "preset"}:
        return plan
    configured = timeline_anchor()
    if not configured:
        return plan
    table, field = configured
    try:
        with closing(create_read_only_connection(DEFAULT_DB_PATH)) as conn:
            anchor_value = conn.execute(
                f'SELECT MAX("{field}") FROM "{table}" WHERE "{field}" IS NOT NULL'
            ).fetchone()[0]
        anchor_date = date.fromisoformat(str(anchor_value)[:10])
    except Exception:
        return plan
    days = getattr(plan.date_range, "relative_days", None)
    if plan.date_range.mode == "preset":
        match = re.search(r"(?P<days>\d+)[_-]?days?", str(getattr(plan.date_range, "preset", "")), re.I)
        days = int(match.group("days")) if match else None
    if not days:
        return plan
    resolved = {
        "resolved_anchor_at": str(anchor_value),
        "resolved_date_from": anchor_date - timedelta(days=int(days) - 1),
        "resolved_date_to": anchor_date,
    }
    plan.date_anchor = (plan.date_anchor or {}).model_copy(update=resolved) if plan.date_anchor else None
    return plan


class ConfirmedAnalysisContext(BaseModel):
    """두 모드가 SQL 실행 기준으로 공유하는 질문·계획·화면 버전·기간 모델이다.

    원래 질문과 분리된 의미 검증용 텍스트, 우선순위가 명시된 LLM 요청문을 제공한다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    original_question: str = Field(min_length=1)
    confirmed_plan: AnalysisPlan
    surface_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    field_metadata: dict[str, FieldMetadata] = Field(default_factory=dict)
    unresolved_constraints: list[str] = Field(default_factory=list)
    temporal_context: TemporalExecutionContext | None = None

    @classmethod
    def from_plan(
        cls,
        plan: AnalysisPlan,
        *,
        original_question: str,
        surface_id: str,
        revision: int,
    ) -> "ConfirmedAnalysisContext":
        """원본 계획을 깊은 복사하고 실제 기간 날짜를 보충해 실행 문맥을 만든다.

        기간 모델·필드 출처·미해결 조건과 화면 ID·버전을 함께 보관한다.
        """

        plan = resolve_plan_temporal_preview(plan.model_copy(deep=True))
        return cls(
            original_question=original_question.strip(),
            confirmed_plan=plan,
            surface_id=surface_id,
            revision=revision,
            field_metadata=plan.field_metadata,
            unresolved_constraints=plan.unresolved_constraints,
            temporal_context=TemporalExecutionContext.from_plan(plan),
        )

    def semantic_validation_text(self) -> str:
        """확정 계획에서 original_question을 제외한 JSON을 검증용 문자열로 만든다.

        이전 질문 표현이 현재 확정 조건보다 우선해 해석되는 것을 줄이기 위한 입력이다.
        """

        payload = self.confirmed_plan.model_dump(mode="json", exclude={"original_question"})
        return "Confirmed semantic analysis plan:\n" + json.dumps(payload, ensure_ascii=False)

    def execution_request(self) -> str:
        """확정 문맥 JSON과 원래 질문을 한 LLM 요청문으로 결합한다.

        분석 기준은 확정 문맥이 우선하고 원래 질문은 대화 이해를 돕는 보조 자료임을 명시한다.
        """

        payload = self.model_dump(mode="json")
        return (
            "CONFIRMED ANALYSIS CONTEXT (authoritative semantic source of truth):\n"
            + json.dumps(payload, ensure_ascii=False)
            + "\nORIGINAL QUESTION (supporting conversational context only):\n"
            + self.original_question
        )
