"""사용자가 확인한 A2UI 계획을 검증·실행하고 응답을 조립한다.

확정 요청의 UiPlan을 검증하고, 별도로 제출된 analysis_plan이 있으면 내용도 대조한다.
후속 분석은 같은 모드의 저장 결과에서 참조 대상을 찾아 실행 문맥에 추가한다.
공통 실행기의 결과를 화면과 실행 기록용 데이터로 변환해 ConfirmDraftResponse를 반환한다.
계획 ID·화면 ID·수정 횟수 등 검토 화면과 연결할 메타데이터도 응답에 보존한다.
실제 SQL 생성·실행은 confirmed_execution 이하의 공통 경로를 사용한다.
"""

from __future__ import annotations

import json
from uuid import uuid4

from app.a2ui.adapter import analysis_result_to_surface
from app.a2ui.models import A2UIClientCapabilities
from app.chat.thread_context import agent_cache_context, compact_context_record, context_record_id
from app.chat.turn_router import analysis_records
from app.execution.confirmed_execution import execute_schema_question
from app.execution.confirmed_context import ConfirmedAnalysisContext
from app.execution.result_payload import _failed_payload
from app.planning.analysis_models import AnalysisPlan
from app.planning.ui_models import UiPlan
from app.planning.a2ui.validator import validate_ui_plan
from app.routes.a2ui.schemas import ConfirmDraftRequest, ConfirmDraftResponse
from app.runtime.state_store import get_thread_results


def confirm_response_payload(payload: ConfirmDraftRequest) -> dict:
    """확정 요청의 계획을 복사·검증하고 선택된 이전 분석 결과를 실행 문맥에 연결한다.

    공통 실행기의 결과를 화면으로 변환하고 화면 ID·계획 ID·버전·수정 횟수를 보존한다.
    답변과 실행 기록용 분석 데이터를 ConfirmDraftResponse 형식의 딕셔너리로 반환한다.
    """

    thread_id = payload.thread_id or str(uuid4())
    question = payload.question.strip()
    plan = payload.plan.model_copy(deep=True)
    review = validate_confirmed_plan(plan, question=question, explicit_plan=payload.analysis_plan)
    execution_question = question
    reference = review.get("context_reference")
    if reference:
        records = analysis_records(get_thread_results(thread_id), input_source="agent2ui")
        selected = [record for record in records if context_record_id(record) == reference["scope_id"]]
        if not selected:
            raise ValueError("참조한 이전 분석 결과를 찾을 수 없습니다. 분석 계획을 다시 만들어 주세요.")
        execution_question += "\n\nSelected previous result (use only to resolve this follow-up):\n" + json.dumps(
            [compact_context_record(selected[-1])], ensure_ascii=False)
    confirmed_context = ConfirmedAnalysisContext.from_plan(
        AnalysisPlan.model_validate(review),
        original_question=execution_question,
        surface_id=payload.surface_id,
        revision=payload.revision,
    )
    execution = execute_schema_question(
        confirmed_context.original_question,
        confirmed_context=confirmed_context,
        cached_context=agent_cache_context(None, question),
    )
    analysis = execution.analysis_payload or _failed_payload(
        execution.fallback_error,
        failure_stage=execution.failure_stage,
        failure_category=execution.failure_category,
        retryable=execution.retryable,
    )
    surface = analysis_result_to_surface(
        analysis,
        answer=execution.answer,
        input_source="agent2ui",
        provider=execution.provider,
        fallback_used=execution.fallback_used,
        fallback_error=execution.fallback_error,
        capabilities=A2UIClientCapabilities(supported_components=payload.supported_components),
    ).model_dump(mode="json")
    plan_payload = plan.model_dump(mode="json")
    plan_payload.update(
        surface_id=payload.surface_id,
        plan_id=payload.plan_id,
        revision=payload.revision,
        selected_suggestion_id=payload.selected_suggestion_id,
        refinement_count=payload.refinement_count,
    )
    return ConfirmDraftResponse(
        thread_id=thread_id,
        input_source="agent2ui",
        plan=plan_payload,
        message=execution.message,
        a2ui_surface=surface,
        execution_result={
            "kind": "agent_answer",
            "input_source": "agent2ui",
            "provider": execution.provider,
            "answer": execution.answer,
            "normalized_spec": {
                "original_question": question,
                "analysis_plan": review,
                "turn_decision": plan.ui_state.get("turn_decision"),
                "confirmed_context": confirmed_context.model_dump(mode="json"),
                "execution_route": (analysis.get("metadata") or {}).get("execution_route"),
                "fallback_used": execution.fallback_used,
                "fallback_error": execution.fallback_error,
                "analysis_execution": analysis,
            },
        },
    ).model_dump(mode="json")


def validate_confirmed_plan(
    plan: UiPlan,
    *,
    question: str = "",
    explicit_plan: dict | None = None,
) -> dict:
    """UiPlan의 분석 계획을 공통 검증기로 검사하고 JSON 호환 딕셔너리로 반환한다.

    최상위 analysis_plan도 전달됐다면 정규화한 두 계획을 대조하며 다르면 ValueError를 발생시킨다.
    """

    review = validate_ui_plan(plan, question).model_dump(mode="json")
    if explicit_plan is not None:
        explicit = AnalysisPlan.model_validate(explicit_plan).model_dump(mode="json")
        if explicit != review:
            raise ValueError("top-level analysis_plan and plan.analysis_plan disagree")
    return review
