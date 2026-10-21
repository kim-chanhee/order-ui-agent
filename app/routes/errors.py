"""API 오류 JSON을 한 형태로 맞춘다.

프론트는 `error.code` / `message` / `field_errors` / `retryable`만 보면 된다.
`server.py` 예외 핸들러가 이 페이로드를 그대로 내려보낸다.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


PLAN_VALIDATION_ERROR = "PLAN_VALIDATION_ERROR"
PLAN_REVISION_CONFLICT = "PLAN_REVISION_CONFLICT"
RUN_CANCELLED = "RUN_CANCELLED"
INVALID_EXPERIMENT_STEP = "INVALID_EXPERIMENT_STEP"
INTERNAL_ERROR = "INTERNAL_ERROR"


def api_error_payload(
    code: str,
    message: str,
    *,
    field_errors: list[dict[str, Any]] | None = None,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """공통 오류 본문을 만든다."""

    return {
        "error": {
            "code": code,
            "message": message,
            "field_errors": field_errors or [],
            "retryable": retryable,
            "details": details or {},
        }
    }


def raise_api_error(
    status_code: int,
    code: str,
    message: str,
    *,
    field_errors: list[dict[str, Any]] | None = None,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> None:
    """핸들러에서 HTTPException으로 올려 `server.py`가 JSON으로 맞추게 한다."""

    raise HTTPException(
        status_code=status_code,
        detail=api_error_payload(code, message, field_errors=field_errors, retryable=retryable, details=details),
    )


def is_api_error_detail(detail: Any) -> bool:
    """이미 공통 오류 형태인지 본다. 맞으면 핸들러가 다시 감싸지 않는다."""

    return isinstance(detail, dict) and isinstance(detail.get("error"), dict)
