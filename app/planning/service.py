"""Baseline과 A2UI가 공유하는 분석 계획 생성 서비스.

주요 기능:
    - 대화 기록에서 SQL과 유효한 분석 계획을 가진 참조 후보를 수집한다.
    - 질문과 이전 분석 후보를 동적 계획 생성기에 전달한다.
    - 생성 결과를 상속 필드·참조 정보·누락 입력을 포함한 UiPlan으로 구성한다.

A2UI 검토 화면 조립과 추가 조건 수정은 a2ui/review.py에서 담당한다.
"""

from __future__ import annotations

from app.chat.thread_context import CONTEXT_HISTORY_LIMIT, compact_context_record
from app.planning.analysis_models import AnalysisPlan
from app.planning.planner import (
    PlannerContextCandidate,
    plan_dynamic_analysis,
)
from app.planning.ui_models import UiPlan
from app.runtime.state_store import get_thread_results


def build_schema_review_plan(
    question: str,
    *,
    previous_plan: AnalysisPlan | None = None,
    context_candidates: list[PlannerContextCandidate] | None = None,
) -> UiPlan:
    """동적 계획 생성 결과를 상속 정보와 참조 정보를 포함한 편집용 UiPlan으로 변환한다."""

    output = plan_dynamic_analysis(
        question.strip(),
        previous_plan=previous_plan,
        context_candidates=context_candidates,
    )
    return UiPlan(
        summary=output.summary,
        analysis_plan=output.analysis_plan,
        ui_state={
            "additional_constraint": "",
            "inherited_fields": [
                field
                for field, metadata in output.analysis_plan.field_metadata.items()
                if metadata.source == "inherited_context"
            ],
            "context_reference": (
                output.analysis_plan.context_reference.model_dump(mode="json")
                if output.analysis_plan.context_reference
                else None
            ),
        },
        ui_blocks=output.ui_blocks,
        missing_fields=output.missing_fields,
        suggested_constraints=output.suggested_constraints,
        infeasible=output.infeasible,
        warnings=output.warnings,
        requires_confirmation=output.requires_confirmation,
    )


def build_review_plan(question: str, thread_id: str, *, context_records: list[dict] | None = None) -> UiPlan:
    """대화의 이전 분석 후보를 수집해 현재 질문의 확인용 계획을 생성한다."""

    return build_schema_review_plan(
        question,
        context_candidates=_thread_analysis_context_candidates(thread_id, records=context_records),
    )


def _thread_analysis_context_candidates(thread_id: str | None, *, records: list[dict] | None = None) -> list[PlannerContextCandidate]:
    """SQL과 유효한 계획이 있는 기록을 압축해 최근 분석 맥락 후보를 반환한다."""

    candidates: list[PlannerContextCandidate] = []
    for record in (get_thread_results(thread_id) if records is None else records):
        normalized = record.get("normalized_spec") or {}
        execution = normalized.get("analysis_execution") or {}
        if not execution.get("sql"):
            continue
        compact = compact_context_record(record)
        plan_payload = compact.get("analysis_plan")
        if not isinstance(plan_payload, dict):
            continue
        try:
            candidates.append(
                PlannerContextCandidate(
                    context_id=str(compact["context_id"]),
                    question=str(compact.get("question") or "").strip(),
                    analysis_plan=AnalysisPlan.model_validate(plan_payload),
                    answer=str(compact.get("answer") or "")[:8000] or None,
                    columns=[str(column) for column in compact.get("columns") or []],
                    rows=list(compact.get("rows") or []),
                    identity_values={
                        str(key): [str(value) for value in values]
                        for key, values in (compact.get("identity_values") or {}).items()
                        if isinstance(values, list)
                    },
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return candidates[-CONTEXT_HISTORY_LIMIT:]


def _latest_thread_analysis_plan(thread_id: str | None) -> AnalysisPlan | None:
    """SQL이 기록된 대화 결과를 최신순으로 살펴보고 유효한 첫 분석 계획을 반환한다."""

    for record in reversed(get_thread_results(thread_id)):
        normalized = record.get("normalized_spec") or {}
        execution = normalized.get("analysis_execution") or {}
        if not execution.get("sql"):
            continue
        candidate = normalized.get("analysis_plan")
        if not isinstance(candidate, dict):
            confirmed = normalized.get("confirmed_context") or {}
            candidate = confirmed.get("confirmed_plan") if isinstance(confirmed, dict) else None
        if not isinstance(candidate, dict):
            continue
        try:
            return AnalysisPlan.model_validate(candidate)
        except ValueError:
            continue
    return None
