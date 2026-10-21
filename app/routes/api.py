"""공통 엔드포인트를 제공하고 기능별 HTTP 라우터를 모은다.

채팅은 `chat`, A2UI 계획 검토는 `a2ui.review`, 실험 관리는 `experiment`에서 처리한다.
`server.py`는 이 모듈의 `router`를 앱에 붙인다.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.core.llm_settings import resolve_agent_llm_settings
from app.core.startup_checks import health_status
from app.routes.chat import router as chat_router
from app.routes.experiment import router as experiment_router
from app.routes.a2ui.review import router as review_router
from app.routes.web_ui import INDEX_HTML


router = APIRouter()


@router.get("/health")
def health() -> dict:
    """로컬 자원 점검과, 비밀을 뺀 LLM 공급자·모델 이름을 돌려준다."""

    provider, base_url, _api_key, model, _timeout = resolve_agent_llm_settings()
    status = health_status()
    status["agent"] = {"provider": provider, "model": model, "base_url_configured": bool(base_url)}
    return status


@router.get("/", response_class=HTMLResponse)
def index() -> str:
    """앱 셸 HTML을 돌려준다."""

    return INDEX_HTML


router.include_router(chat_router)
router.include_router(review_router)
router.include_router(experiment_router)
