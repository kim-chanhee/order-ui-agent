"""취소 가능한 워커에서 A2UI 계획 확정 요청을 검증하고 실행한다."""

from app.execution.a2ui.service import confirm_response_payload
from app.routes.a2ui.schemas import ConfirmDraftRequest


def run_confirmation(payload: dict) -> dict:
    """확정 요청을 전용 모델로 검증한 뒤 공통 SQL 실행 계층에 연결한다."""

    return confirm_response_payload(ConfirmDraftRequest.model_validate(payload))
