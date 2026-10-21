"""Baseline 요청의 계획 생성·즉시 실행·응답 조립을 담당한다.

입력은 채팅 요청과 스레드 ID, 선택된 이전 분석 기록이다.
공통 planner의 분석 계획에서 실행 문맥을 만들고 confirmed_execution을 호출한다.
계획 생성 실패나 이전 결과 참조 불명확 시에는 조건 확인 응답을 반환한다.
정상 실행 결과는 답변·결과 화면·분석 계획·실행 메타데이터로 묶어 반환한다.
SQL 생성과 DB 접근의 세부 처리는 공통 에이전트와 도구에 위임한다.
"""

from __future__ import annotations

import json
from uuid import uuid4

from app.a2ui.adapter import analysis_result_to_surface
from app.a2ui.models import A2UIClientCapabilities
from app.chat.thread_context import agent_cache_context, contextual_request, compact_context_record, context_record_id
from app.execution.confirmed_execution import execute_schema_question
from app.execution.confirmed_context import ConfirmedAnalysisContext
from app.execution.result_payload import _failed_payload
from app.planning.service import build_review_plan
from app.routes.schemas import ChatRequest, ChatResponse


def baseline_response_payload(
    payload: ChatRequest,
    *,
    thread_id: str,
    routing_context: list[dict] | None = None,
) -> dict:
    """채팅 요청으로 분석 계획을 만들고 확인 화면 없이 공통 SQL 실행기로 전달한다.

    이전 결과 참조와 대체 계획 여부를 확인해 필요한 경우 추가 질문을 반환한다.
    실행 후에는 답변·결과 화면·계획·실행 메타데이터를 ChatResponse 형식의 딕셔너리로 묶는다.
    """

    thread_id = thread_id or str(uuid4())
    question = payload.question.strip()
    review_plan = build_review_plan(question, thread_id, context_records=routing_context)
    if not review_plan.requires_confirmation:
        return ChatResponse(
            answer=review_plan.summary, thread_id=thread_id, input_source="baseline",
            execution_result={"kind": "clarification", "input_source": "baseline",
                              "answer": review_plan.summary,
                              "normalized_spec": {"original_question": question}},
        ).model_dump(mode="json")
    analysis_plan = review_plan.analysis_plan
    reference = analysis_plan.context_reference
    if routing_context is not None and (
        analysis_plan.source == "safe_fallback"
        or (routing_context and (not reference or reference.needs_confirmation
                                or reference.scope_id != context_record_id(routing_context[-1])))
    ):
        answer = "분석 조건이나 참조할 이전 결과를 확인하지 못했습니다. 원하는 조건을 조금 더 구체적으로 알려주세요."
        return ChatResponse(answer=answer, thread_id=thread_id, input_source="baseline",
                            execution_result={"kind": "clarification", "input_source": "baseline", "answer": answer,
                                              "normalized_spec": {"original_question": question}}).model_dump(mode="json")
    execution_question = contextual_request(question, thread_id) if routing_context is None else question
    if routing_context:
        execution_question += "\n\nSelected previous result (use only to resolve this follow-up):\n" + json.dumps(
            [compact_context_record(record) for record in routing_context], ensure_ascii=False)
    confirmed_context = ConfirmedAnalysisContext.from_plan(
        analysis_plan,
        original_question=execution_question,
        surface_id=f"baseline-{thread_id}",
        revision=1,
    )
    execution = execute_schema_question(
        confirmed_context.original_question,
        confirmed_context=confirmed_context,
        cached_context=agent_cache_context(thread_id if routing_context is None else None, question),
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
        input_source="baseline",
        provider=execution.provider,
        fallback_used=execution.fallback_used,
        fallback_error=execution.fallback_error,
        capabilities=A2UIClientCapabilities(supported_components=payload.supported_components),
    ).model_dump(mode="json")
    return ChatResponse(
        answer=execution.answer,
        thread_id=thread_id,
        input_source="baseline",
        a2ui_surface=surface,
        execution_result={
            "kind": "agent_answer",
            "input_source": "baseline",
            "provider": execution.provider,
            "answer": execution.answer,
            "normalized_spec": {
                "original_question": question,
                "analysis_plan": analysis_plan.model_dump(mode="json"),
                "confirmed_context": confirmed_context.model_dump(mode="json"),
                "execution_route": (analysis.get("metadata") or {}).get("execution_route"),
                "fallback_used": execution.fallback_used,
                "fallback_error": execution.fallback_error,
                "analysis_execution": analysis,
            },
        },
    ).model_dump(mode="json")
