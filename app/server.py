"""FastAPI 앱 진입점.

환경 변수를 먼저 로드한 뒤 앱을 만들고, 정적 파일·API 라우터를 붙인다.
시작 시 LLM 설정을 확인하고, HTTP/검증/내부 예외를 공통 JSON 오류로 맞춘다.
`python -m app.server` 또는 `main()`으로 uvicorn을 띄운다.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# 아래 import가 환경 변수에 의존하므로, 앱 모듈을 가져오기 전에 .env를 먼저 읽는다.
load_dotenv()

from app.core.llm_settings import resolve_agent_llm_settings
from app.routes.errors import INTERNAL_ERROR, PLAN_VALIDATION_ERROR, RUN_CANCELLED, api_error_payload, is_api_error_detail
from app.routes.api import router as api_router
from app.core.startup_checks import run_startup_checks
from app.routes.web_ui import STATIC_DIR


HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
TITLE = "Schema-driven SQLite Agent"


def log_agent_llm_config() -> None:
    """시작 점검을 돌리고, SQL 에이전트가 쓸 LLM 설정을 로그에 남긴다."""

    run_startup_checks()
    provider, base_url, _api_key, model, timeout = resolve_agent_llm_settings()
    print(
        f"[order-ui-agent] fast_llm_sql: provider={provider} model={model} "
        f"timeout={timeout}s base_url={base_url}",
        flush=True,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """앱이 요청을 받기 전에 LLM 설정을 한 번 확인하고, 종료 시에는 별도 정리가 없다."""

    log_agent_llm_config()
    yield


app = FastAPI(title=TITLE, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(api_router)


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    """라우트에서 올린 HTTPException을 공통 API 오류 JSON으로 맞춘다."""

    # 이미 api_error_payload 형태면 그대로 내려보낸다.
    if is_api_error_detail(exc.detail):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    # 499는 실행 취소, 그 외는 내부 오류로 취급한다.
    code = RUN_CANCELLED if exc.status_code == 499 else INTERNAL_ERROR
    message = "요청이 취소되었습니다." if exc.status_code == 499 else str(exc.detail or "요청 처리 중 오류가 발생했습니다.")
    return JSONResponse(status_code=exc.status_code, content=api_error_payload(code, message, retryable=exc.status_code >= 500))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """요청 본문/쿼리 검증 실패를 필드별 메시지가 담긴 422로 돌려준다."""

    field_errors = [{"field": ".".join(map(str, error.get("loc", []))), "message": error.get("msg", "")} for error in exc.errors()]
    return JSONResponse(status_code=422, content=api_error_payload(PLAN_VALIDATION_ERROR, "요청 형식을 확인해 주세요.", field_errors=field_errors))


@app.exception_handler(Exception)
async def internal_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
    """처리되지 않은 예외는 내부 메시지 없이 500으로 감춘다."""

    return JSONResponse(status_code=500, content=api_error_payload(INTERNAL_ERROR, "요청 처리 중 오류가 발생했습니다."))


def main() -> None:
    """HOST/PORT 환경 변수로 uvicorn을 기동한다."""

    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
