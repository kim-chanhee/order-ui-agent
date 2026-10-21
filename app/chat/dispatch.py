"""요청을 분류하고 분석 실행·계획 확인·저장 결과 활용 경로로 전달한다.

처리 순서:
    1. 현재 모드의 이전 분석 결과를 불러와 요청을 분류한다.
    2. 새 분석·분석 수정은 Baseline 실행 또는 Agent2UI 계획 확인으로 연결한다.
    3. 나머지는 추가 질문, 일반 대화, 결과 요약·설명, 표시 형식 변경으로 처리한다.

함수 구성:
    routed_chat_response        - 전체 요청 처리 흐름
    _baseline_analysis_response - Baseline 분석 실행과 분류 정보 반영
    _transform_result_response  - 저장된 결과의 표시 형식 변경
    _chat_response              - 분석 실행이 필요 없는 경로의 공통 응답 구성
"""

from copy import deepcopy

from app.a2ui.adapter import analysis_result_to_surface
from app.a2ui.models import A2UIClientCapabilities
from app.chat.a2ui.review import review_response
from app.chat.responses import generate_reply
from app.chat.thread_context import context_record_id, recent_dialogue
from app.chat.turn_router import TurnDecision, analysis_records, respond_from_results, route_turn
from app.execution.baseline.service import baseline_response_payload
from app.routes.schemas import ChatRequest, ChatResponse
from app.runtime.state_store import get_thread_results


def routed_chat_response(payload: ChatRequest, thread_id: str) -> dict:
    """이전 결과와 요청 분류를 바탕으로 처리할 경로를 선택해 응답을 반환한다."""

    question = payload.question.strip()
    history = get_thread_results(thread_id)
    records = analysis_records(history, input_source=payload.input_source)
    conversation = recent_dialogue(thread_id, payload.input_source)
    decision = route_turn(question, records, conversation=conversation)
    selected_records = [
        record
        for record in records
        if context_record_id(record) == decision.context_reference
    ]

    # 확인 질문에 대한 짧은 답은 LLM이 복원한 전체 요청으로 분석한다.
    analysis_payload = payload
    if conversation and conversation[-1].get("kind") == "clarification" and decision.resolved_question:
        analysis_payload = payload.model_copy(update={"question": decision.resolved_question})

    # 새 분석·분석 수정: 모드에 따라 실행하거나 확인 화면을 만든다.
    if decision.requires_analysis:
        if payload.input_source == "agent2ui":
            return review_response(
                payload, thread_id, decision, selected_records,
                planning_question=analysis_payload.question,
            )
        return _baseline_analysis_response(analysis_payload, thread_id, decision, selected_records)

    # 분류가 불명확하거나 참조 결과가 없으면 먼저 추가 질문을 한다.
    if decision.clarification_question:
        return _chat_response(
            payload, thread_id, decision,
            answer=decision.clarification_question,
            kind="clarification",
        )

    if decision.request_kind == "conversation":
        return _chat_response(
            payload, thread_id, decision,
            answer=decision.reply or generate_reply(
                question, purpose="conversation", conversation=conversation,
            ),
            kind="conversation",
        )

    if decision.request_kind in {"summarize_results", "explain_results"}:
        result_records = selected_records if decision.context_reference else records
        answer = respond_from_results(analysis_payload.question.strip(), result_records, decision.request_kind)
        kind = "summary" if decision.request_kind == "summarize_results" else "explanation"
        return _chat_response(payload, thread_id, decision, answer=answer, kind=kind)

    # 위 분기에 해당하지 않으면 저장된 결과의 표시 형식을 변경한다.
    return _transform_result_response(analysis_payload, thread_id, decision, selected_records)


def _baseline_analysis_response(
    payload: ChatRequest,
    thread_id: str,
    decision: TurnDecision,
    selected_records: list[dict],
) -> dict:
    """Baseline 분석을 실행하고 실행 중 발생한 추가 질문과 요청 분류 정보를 반영한다."""

    routing_context = []
    if decision.request_kind == "refine_analysis":
        routing_context = selected_records

    response = baseline_response_payload(
        payload,
        thread_id=thread_id,
        routing_context=routing_context,
    )
    execution_result = response["execution_result"]
    if execution_result["kind"] == "clarification":
        answer = generate_reply(
            payload.question,
            purpose="clarify_analysis_plan_without_execution",
            evidence={"planning_feedback": response["answer"], "selected_results": selected_records},
            conversation=recent_dialogue(thread_id, payload.input_source),
        )
        response["answer"] = answer
        execution_result["answer"] = answer
        decision.clarification_question = answer
    execution_result["normalized_spec"]["turn_decision"] = decision.as_payload()
    return response


def _transform_result_response(
    payload: ChatRequest,
    thread_id: str,
    decision: TurnDecision,
    selected_records: list[dict],
) -> dict:
    """원본 결과를 보존하면서 저장된 분석을 표·차트·요약 형식의 응답으로 변환한다."""

    selected_record = selected_records[-1]
    analysis = deepcopy(selected_record["normalized_spec"]["analysis_execution"])

    view = decision.presentation
    if view == "text":
        view = "summary"
    elif view == "chart":
        # 차트로 표시하기 어려운 데이터도 확인할 수 있도록 표를 함께 제공한다.
        view = "table_and_chart"

    metadata = analysis.get("metadata") or {}
    analysis["metadata"] = {
        **metadata,
        "result_view": view,
        "execution_route": "stored_result",
        "reused_result": True,
    }

    if view == "summary":
        answer = respond_from_results(payload.question.strip(), selected_records, "summarize_results")
    else:
        answer = decision.reply or generate_reply(
            payload.question.strip(),
            purpose="describe_stored_result_presentation",
            evidence={
                "result_view": view,
                "columns": analysis.get("columns") or [],
                "stored_row_count": len(analysis.get("rows") or []),
                "reused_result": True,
                "new_sql_executed": False,
                "chart_requires_numeric_data": True,
            },
            conversation=recent_dialogue(thread_id, payload.input_source),
        )

    capabilities = A2UIClientCapabilities(supported_components=payload.supported_components)
    surface = analysis_result_to_surface(
        analysis,
        answer=answer,
        input_source=payload.input_source,
        provider="stored_result",
        capabilities=capabilities,
    ).model_dump(mode="json")

    return _chat_response(
        payload, thread_id, decision,
        answer=answer,
        kind="result_transform",
        analysis=analysis,
        surface=surface,
    )


def _chat_response(
    payload: ChatRequest,
    thread_id: str,
    decision: TurnDecision,
    *,
    answer: str,
    kind: str,
    analysis: dict | None = None,
    surface: dict | None = None,
) -> dict:
    """답변·요청 분류·선택적 재사용 결과를 공통 ChatResponse 형식으로 묶는다."""

    normalized_spec = {
        "original_question": payload.question.strip(),
        "turn_decision": decision.as_payload(),
    }
    if analysis is not None:
        normalized_spec["analysis_execution"] = analysis
        normalized_spec["execution_route"] = "stored_result"

    execution_result = {
        "kind": kind,
        "input_source": payload.input_source,
        "provider": "turn_router",
        "answer": answer,
        "normalized_spec": normalized_spec,
    }
    return ChatResponse(
        answer=answer,
        thread_id=thread_id,
        input_source=payload.input_source,
        a2ui_surface=surface,
        execution_result=execution_result,
    ).model_dump(mode="json")
