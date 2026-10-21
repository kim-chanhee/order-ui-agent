"""채팅 요청과 실행 취소를 처리하는 HTTP 라우터."""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from fastapi import APIRouter, HTTPException

from app.chat.service import chat_response_payload
from app.chat.thread_context import remember_execution_context
from app.experiment.context import experiment_context
from app.experiment.interactions import record_chat_interaction
from app.experiment.log import append_experiment_csv
from app.routes.errors import INTERNAL_ERROR, INVALID_EXPERIMENT_STEP, PLAN_VALIDATION_ERROR, raise_api_error
from app.routes.schemas import ChatRequest, ChatResponse
from app.runtime.chat_log import append_chat_csv
from app.runtime.run_manager import RunTimedOutError, run_cancelable
from app.runtime.run_manager import cancel_run as cancel_running_run
from app.runtime.state_store import record_execution_result


router = APIRouter()


@router.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, str]:
    """프론트 중단 버튼이 보낸 run_id의 워커를 종료한다."""

    return cancel_running_run(run_id)


@router.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    """한 턴을 chat 계층에 넘긴다. 실험이면 thread를 고정하고, run_id가 있으면 취소 가능한 워커에서 돌린다."""

    try:
        started_at = perf_counter()
        started_iso = datetime.now(timezone.utc).isoformat()
        experiment = experiment_context(payload.participant_id, payload.input_source)
        if experiment:
            session, condition, task_id, thread_id = experiment
            payload = payload.model_copy(update={"thread_id": thread_id, "task_id": task_id})
            result = chat_response_payload(payload)
        elif payload.run_id:
            try:
                result = run_cancelable("chat", payload.model_dump(mode="json"), payload.run_id)
            except RunTimedOutError:
                # SQL 엔진이 하나라 타임아웃 때 다른 경로로 바꾸지 않고 실패로 알린다.
                label = "Baseline" if payload.input_source == "baseline" else "Agent2UI"
                raise_api_error(500, INTERNAL_ERROR, f"{label} 요청 처리 시간이 초과되었습니다. 다시 시도해 주세요.")
        else:
            result = chat_response_payload(payload)
        duration_ms = round((perf_counter() - started_at) * 1000)
        execution_result = result.get("execution_result")
        if _should_record_execution_result(execution_result):
            record_execution_result(result.get("thread_id"), payload.question, execution_result)
            remember_execution_context(result.get("thread_id"), execution_result)
        stage = _chat_stage(execution_result)
        append_experiment_csv(
            participant_id=payload.participant_id,
            participant_profile=payload.participant_profile,
            thread_id=result.get("thread_id"),
            run_id=payload.run_id,
            stage=stage,
            input_source=result.get("input_source"),
            question=payload.question,
            assistant_answer=result.get("answer"),
            plan=result.get("plan"),
            execution_result=execution_result,
            time_to_plan_ms=duration_ms if stage == "plan_created" else None,
            time_to_answer_ms=duration_ms if stage != "plan_created" else None,
        )
        append_chat_csv(
            thread_id=result.get("thread_id"),
            run_id=payload.run_id,
            stage=stage,
            input_source=result.get("input_source"),
            question=payload.question,
            assistant_answer=result.get("answer"),
            plan=result.get("plan"),
            execution_result=execution_result,
            app_mode=payload.app_mode,
            participant_id=payload.participant_id,
            task_id=payload.task_id,
            duration_ms=duration_ms,
        )
        if experiment:
            record_chat_interaction(
                payload=payload,
                result=result,
                session=session,
                condition=condition,
                task_id=task_id,
                thread_id=thread_id,
                started_at=started_iso,
                duration_ms=duration_ms,
                stage=stage,
            )
        return ChatResponse.model_validate(result)
    except ValueError as exc:
        code = INVALID_EXPERIMENT_STEP if "experiment" in str(exc) or "input_source" in str(exc) or "current" in str(exc) else PLAN_VALIDATION_ERROR
        raise_api_error(422, code, str(exc))
    except HTTPException:
        raise
    except Exception:
        raise_api_error(500, INTERNAL_ERROR, "요청 처리 중 오류가 발생했습니다.")


def _chat_stage(execution_result: dict | None) -> str:
    """로그용 단계 이름. 실행 결과 kind를 plan_created / executed 등으로 바꾼다."""

    kind = (execution_result or {}).get("kind")
    if kind == "summary":
        return "summary"
    if kind in {"explanation", "result_transform"}:
        return kind
    if kind == "unsupported_query":
        return "unsupported"
    if kind == "conversation":
        return "conversation"
    if kind in {"review_required", "ad_hoc_review_required", "clarification"}:
        return "plan_created"
    return "executed" if execution_result else "plan_created"


def _should_record_execution_result(execution_result: dict | None) -> bool:
    """실제 조회 결과만 thread에 남긴다. 요약·검토·대화는 저장하지 않는다."""

    kind = (execution_result or {}).get("kind")
    return bool(execution_result) and kind not in {
        "summary",
        "explanation",
        "result_transform",
        "review_required",
        "ad_hoc_review_required",
        "clarification",
        "unsupported_query",
        "conversation",
    }
