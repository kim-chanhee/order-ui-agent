"""A2UI 전용 계획 검토 응답과 참조 불명확 시 확인 질문을 만든다."""

from app.chat.responses import generate_reply
from app.chat.thread_context import context_record_id, compact_context_record, recent_dialogue
from app.chat.turn_router import TurnDecision
from app.planning.service import build_review_plan
from app.planning.a2ui.review import plan_response_parts
from app.routes.schemas import ChatRequest, ChatResponse


def review_response(
    payload: ChatRequest,
    thread_id: str,
    decision: TurnDecision,
    selected: list[dict],
    *,
    planning_question: str | None = None,
) -> dict:
    """Agent2UI 분석 계획과 확인 화면을 만들며, 참조가 불명확하면 추가 질문을 반환한다.

    이 단계에서는 SQL을 실행하지 않고 사용자 확인에 필요한 계획만 제공한다.
    """
    question = payload.question.strip()
    context = selected if decision.request_kind == "refine_analysis" else []
    plan = build_review_plan(planning_question or question, thread_id, context_records=context)
    # 확인 API와 화면은 사용자가 실제 입력한 질문을 기준으로 계획을 대조한다.
    plan.analysis_plan.original_question = question
    conversation = recent_dialogue(thread_id, payload.input_source)
    reference = plan.analysis_plan.context_reference
    if not plan.requires_confirmation or (context and (
        not reference or reference.scope_id != context_record_id(context[-1])
    )):
        answer = generate_reply(
            question,
            purpose="clarify_review_plan_without_execution",
            evidence={
                "plan_summary": plan.summary,
                "unresolved_constraints": plan.analysis_plan.unresolved_constraints,
                "reference_matches": not context or bool(
                    reference and reference.scope_id == context_record_id(context[-1])
                ),
                "available_results": [compact_context_record(record) for record in context],
                "new_sql_executed": False,
            },
            conversation=conversation,
        )
        decision.clarification_question = answer
        return ChatResponse(
            answer=answer, thread_id=thread_id, input_source="agent2ui",
            execution_result={"kind": "clarification", "input_source": "agent2ui", "answer": answer,
                              "normalized_spec": {"original_question": question, "turn_decision": decision.as_payload()}},
        ).model_dump(mode="json")
    plan.ui_state["turn_decision"] = decision.as_payload()
    _, plan_payload, surface = plan_response_parts(plan, payload, thread_id)
    answer = generate_reply(
        question,
        purpose="introduce_analysis_review_and_request_user_confirmation",
        evidence={
            "plan_summary": plan.summary,
            "missing_fields": plan.missing_fields,
            "unresolved_constraints": plan.analysis_plan.unresolved_constraints,
            "new_sql_executed": False,
            "review_surface_created": True,
        },
        conversation=conversation,
    )
    return ChatResponse(
        answer=answer, thread_id=thread_id, input_source="agent2ui", plan=plan_payload, a2ui_surface=surface,
        execution_result={"kind": "review_required", "input_source": "agent2ui", "provider": "schema_review",
                          "answer": answer, "normalized_spec": {
                              "original_question": question, "execution_route": "schema_review_required",
                              "analysis_plan": plan.analysis_plan.model_dump(mode="json"),
                              "turn_decision": decision.as_payload(),
                          }},
    ).model_dump(mode="json")
