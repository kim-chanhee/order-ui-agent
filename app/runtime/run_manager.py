"""별도 워커 프로세스에서 요청을 실행하고 취소·시간 제한을 관리한다.

LLM/SQL Agent 실행은 오래 걸릴 수 있으므로, 프론트의 "중단" 버튼이
실제로 동작하려면 요청을 별도 프로세스에서 돌려야 한다. 이 파일은
run_id별 워커 프로세스를 추적하고, 취소 요청이 오면 terminate한다.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import threading
from time import perf_counter
from multiprocessing.queues import Queue

from fastapi import HTTPException

from app.routes.schemas import ChatRequest
from app.chat.service import chat_response_payload
from app.runtime.a2ui.worker import run_confirmation


# macOS/일반 Python 환경에서 안전한 spawn 컨텍스트를 사용한다.
# RUNS는 현재 살아 있는 워커 프로세스 목록이다.
RUN_CONTEXT = mp.get_context("spawn")
RUNS: dict[str, mp.Process] = {}
RUNS_LOCK = threading.Lock()


def _default_run_timeout_seconds() -> float:
    """계획 생성과 SQL 실행에 필요한 기본 제한 시간을 초 단위로 계산한다.

    SQL 실행 예산에 LLM 요청 제한 시간 × 계획 시도 횟수와 여유 5초를 더한다.
    계획 시도 횟수는 최소 1회로 계산한다.
    """

    sql_total = float(os.environ.get("FAST_SQL_TOTAL_TIMEOUT_SECONDS", "45"))
    provider_timeout = float(os.environ.get("AGENT_TIMEOUT_SECONDS", "120"))
    planner_attempts = int(os.environ.get("AGENT2UI_PLANNER_MAX_ATTEMPTS", "2"))
    return sql_total + provider_timeout * max(planner_attempts, 1) + 5


RUN_TIMEOUT_SECONDS = float(
    os.environ.get("AGENT_RUN_TIMEOUT_SECONDS", str(_default_run_timeout_seconds()))
)


class RunTimedOutError(TimeoutError):
    """워커의 실행 시간이 설정된 제한을 초과했을 때 발생하는 예외."""


def run_cancelable(kind: str, payload: dict, run_id: str, *, timeout_seconds: float | None = RUN_TIMEOUT_SECONDS) -> dict:
    """채팅 또는 계획 확정 요청을 취소 가능한 별도 프로세스에서 실행한다.

    워커를 run_id로 등록하고 Queue로 전달받은 결과를 반환한다.
    시간 초과 시 RunTimedOutError, 결과 없이 워커가 종료되면 HTTP 499,
    워커가 오류를 전달하면 HTTP 500을 발생시킨다.
    처리 종료 시 워커를 정리하고 실행 목록에서 제거한다.
    timeout_seconds가 None 또는 0이면 시간 제한을 적용하지 않는다.
    """

    # 부모 프로세스는 Queue로 결과만 받고, 실제 heavy work는 _run_worker에서 수행한다.
    result_queue = RUN_CONTEXT.Queue()
    process = RUN_CONTEXT.Process(
        target=_run_worker,
        args=(kind, payload, result_queue),
        daemon=True,
    )
    with RUNS_LOCK:
        RUNS[run_id] = process
    process.start()
    started = perf_counter()
    try:
        while True:
            try:
                # 짧게 polling해야 /cancel이 process를 죽였을 때 빠르게 감지할 수 있다.
                message = result_queue.get(timeout=0.2)
            except queue.Empty:
                if timeout_seconds and perf_counter() - started >= timeout_seconds:
                    raise RunTimedOutError(f"run exceeded {timeout_seconds:.1f}s")
                if not process.is_alive():
                    raise HTTPException(status_code=499, detail="run was cancelled")
                continue
            if message.get("ok"):
                return message["result"]
            raise HTTPException(status_code=500, detail=message.get("error") or "run failed")
    finally:
        # 정상/오류/취소 어떤 경우든 프로세스와 RUNS 테이블을 정리한다.
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        with RUNS_LOCK:
            if RUNS.get(run_id) is process:
                RUNS.pop(run_id, None)


def cancel_run(run_id: str) -> dict[str, str]:
    """run_id에 등록된 워커를 찾아 종료하고 실행 목록에서 제거한다.

    등록된 워커가 없으면 not_found, 있으면 취소 처리 후 cancelled를 반환한다.
    응답에는 요청한 run_id도 함께 담는다.
    """

    with RUNS_LOCK:
        process = RUNS.get(run_id)
    if process is None:
        return {"status": "not_found", "run_id": run_id}
    if process.is_alive():
        process.terminate()
        process.join(timeout=1)
    with RUNS_LOCK:
        if RUNS.get(run_id) is process:
            RUNS.pop(run_id, None)
    return {"status": "cancelled", "run_id": run_id}


def _run_worker(kind: str, payload: dict, result_queue: Queue) -> None:
    """워커 안에서 요청 데이터를 검증하고 종류에 맞는 서비스를 호출한다.

    chat은 채팅 서비스, confirm은 계획 확정 실행 서비스를 호출한다.
    성공하면 결과를, 예외가 발생하면 오류 문자열을 result_queue에 담아
    부모 프로세스로 전달한다.
    """

    try:
        if kind == "chat":
            result = chat_response_payload(ChatRequest.model_validate(payload))
        elif kind == "confirm":
            result = run_confirmation(payload)
        else:
            raise ValueError(f"Unsupported run kind: {kind}")
        result_queue.put({"ok": True, "result": result})
    except Exception as exc:
        result_queue.put({"ok": False, "error": str(exc)})
