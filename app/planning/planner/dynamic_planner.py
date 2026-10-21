"""Baseline과 A2UI가 공유하는 LLM 분석 계획 생성 진입점.

설정 확인, LLM 호출, 후처리 순서, 재시도와 실패 시 대체 계획을 담당한다.
세부 처리는 같은 패키지의 models/response/controls/context/semantics/prompt에 위임한다.
검토 중 자연어 추가 조건 수정은 a2ui/refinement.py에서 담당한다.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI

from app.core.llm_settings import resolve_agent_llm_settings
from app.execution.confirmed_context import resolve_plan_temporal_preview
from app.planning.analysis_models import AnalysisPlan, FieldMetadata
from app.planning.schema_context import PlannerSchemaContext, build_planner_schema_context
from app.planning.ui_models import DynamicPlannerOutput, UiBlock
from app.planning.planner.models import (
    ContextField,
    PlannerContextCandidate,
    PlannerContextResolution,
    PlannerDraft,
)
from app.planning.planner.response import (
    _canonicalize_planner_output,
)
from app.planning.planner.controls import (
    _normalize_ui_blocks,
    _ensure_plan_controls,
)
from app.planning.planner.context import (
    _inherit_followup_scope,
    _normalize_context_candidates,
    _context_resolution_from_result,
    _inherited_field_label,
)
from app.planning.planner.semantics import (
    _normalize_identifier_count,
    _normalize_detail_result_metric,
    _normalize_relationship_scope,
    _promote_headline_metric,
    _mirror_infeasible_into_unresolved,
    _validate_planner_semantics,
    _synchronize_temporal_copy,
)
from app.planning.planner.prompt import (
    _planner_prompt,
)


def planner_enabled() -> bool:
    """환경 변수의 명시적 설정이나 LLM 접속 설정 유무로 계획 생성기 활성 여부를 판단한다."""

    value = os.environ.get("AGENT2UI_LLM_PLANNER", "auto").strip().lower()
    if value in {"0", "false", "no", "off"}:
        return False
    if value in {"1", "true", "yes", "on"}:
        return True
    return any(os.environ.get(key, "").strip() for key in ("AGENT_PROVIDER", "AGENT_BASE_URL", "OPENAI_API_KEY", "AGENT_API_KEY"))


def plan_dynamic_analysis(
    question: str,
    *,
    schema_context: PlannerSchemaContext | None = None,
    previous_plan: AnalysisPlan | None = None,
    context_candidates: list[PlannerContextCandidate] | None = None,
    llm: Any | None = None,
) -> DynamicPlannerOutput:
    """질문과 스키마로 LLM 계획을 생성하고 구조 보정·맥락 상속·의미 검증을 수행한다. 재시도 후에도 실패하면 조건 확인 계획을 반환한다."""

    question = question.strip()
    context = schema_context or build_planner_schema_context(question)
    candidates = _normalize_context_candidates(previous_plan, context_candidates)
    if not planner_enabled() and llm is None:
        return _ensure_plan_controls(
            safe_clarification_plan(question, reason="LLM planner is not configured"),
            context,
        )
    model = llm or _planner_llm()
    structured = model.with_structured_output(PlannerDraft, method="function_calling")
    prompt = _planner_prompt(question, context, context_candidates=candidates)
    last_error: Exception | None = None
    attempt_prompt = prompt
    max_attempts = max(1, int(os.environ.get("AGENT2UI_PLANNER_MAX_ATTEMPTS", "2")))
    for _attempt in range(max_attempts):
        try:
            result = structured.invoke(attempt_prompt)
            output = _canonicalize_planner_output(result, question)
            context_resolution = _context_resolution_from_result(result)
            output.analysis_plan.original_question = question
            output.analysis_plan.source = "llm_dynamic_planner"
            output = _promote_headline_metric(output)
            output = _normalize_detail_result_metric(output)
            output = _normalize_relationship_scope(output)
            output = _normalize_identifier_count(output)
            output.ui_blocks = _normalize_ui_blocks(output.ui_blocks)
            output, inherited_fields = _inherit_followup_scope(output, candidates, context_resolution)
            if inherited_fields:
                output.warnings = [
                    *output.warnings,
                    "이전 질문에서 유지한 조건: " + ", ".join(_inherited_field_label(field) for field in inherited_fields),
                ]
            if output.analysis_plan.context_reference and output.analysis_plan.context_reference.needs_confirmation:
                output.warnings = [
                    *output.warnings,
                    "현재 질문과 연결할 이전 분석 범위가 명확하지 않습니다. 적용된 기간과 대상을 확인해 주세요.",
                ]
            output = _ensure_plan_controls(output, context)
            output = _mirror_infeasible_into_unresolved(output)
            output.analysis_plan = resolve_plan_temporal_preview(output.analysis_plan)
            output = _synchronize_temporal_copy(output)
            _validate_planner_semantics(output, question)
            output.suggested_constraints = output.suggested_constraints[:3]
            return output
        except Exception as exc:  # 설정된 시도 횟수 안에서 재시도하고, 모두 실패하면 조건 확인용 계획을 반환한다.
            last_error = exc
            attempt_prompt = (
                f"{prompt}\n\nThe previous structured response was invalid. Correct only its structure and "
                f"return the complete envelope again. Validation feedback: {type(exc).__name__}: {exc}"
            )
    detail = " ".join(str(last_error or "unknown error").split())[:600]
    return _ensure_plan_controls(
        safe_clarification_plan(
            question,
            reason=f"structured planner failed: {type(last_error).__name__}: {detail}",
        ),
        context,
    )


def _planner_llm() -> ChatOpenAI:
    """공통 접속 설정과 계획 생성 전용 모델·추론 옵션을 적용한 LLM 클라이언트를 만든다."""

    _provider, base_url, api_key, agent_model, timeout = resolve_agent_llm_settings()
    model = os.environ.get("AGENT2UI_PLANNER_MODEL", "").strip() or agent_model
    kwargs: dict[str, Any] = {"model": model, "api_key": api_key, "timeout": timeout, "max_retries": 0}
    if model.startswith("gpt-5"):
        default_effort = "none" if model.startswith("gpt-5.6") else "low"
        kwargs["reasoning_effort"] = os.environ.get(
            "AGENT2UI_PLANNER_REASONING_EFFORT", default_effort
        )
    else:
        kwargs["temperature"] = 0
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def safe_clarification_plan(question: str, *, reason: str) -> DynamicPlannerOutput:
    """계획 생성 실패 이유와 미해결 조건을 담고 사용자가 분석 기준을 입력할 대체 계획을 만든다."""

    metadata = {"analysis_goal": FieldMetadata(status="needs_confirmation", confidence=0.0, source="llm_inferred")}
    analysis = AnalysisPlan(
        original_question=question,
        unresolved_constraints=["분석 조건을 자동으로 구조화하지 못했습니다. 원하는 기준을 추가 조건에 적어 주세요."],
        field_metadata=metadata,
        source="safe_fallback",
    )
    return DynamicPlannerOutput(
        analysis_plan=analysis,
        ui_blocks=[
            UiBlock(type="review", key="analysis_review", label="분석 요청", props={"display_only": True}),
            UiBlock(type="textarea", key="analysis_goal", field_path="target_conditions", label="원하는 분석 기준", required=True),
        ],
        missing_fields=["analysis_goal"],
        field_metadata=metadata,
        summary="분석 조건을 확인해 주세요.",
        warnings=[reason],
    )
