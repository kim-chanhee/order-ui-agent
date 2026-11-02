"""Shared provider error handling; an exhausted balance is not a rate limit."""
from time import sleep
from dataclasses import dataclass

from app.core.llm_usage import LLMBudgetExceeded


def quota_exhausted(error):
    text = str(error).casefold()
    return any(code in text for code in ('credit_balance_exhausted','insufficient_quota','no credits remaining'))


@dataclass(frozen=True)
class ModelErrorClassification:
    """모델 호출 오류의 분류명·재시도 가능 여부·HTTP 상태를 함께 보관한다.

    재시도 정책이 공급자 오류와 의미 오류를 구분하는 기준으로 사용한다.
    """

    category: str
    retryable: bool
    status_code: int | None = None


def _is_rate_limit_error(exc: BaseException) -> bool:
    """예외 클래스명·상태 코드·메시지에서 요청 한도 초과 여부를 찾는다.

    SDK마다 오류 표현이 달라도 429 계열을 공통으로 분류하기 위한 보조 함수다.
    """

    if exc.__class__.__name__ in {"RateLimitError", "TooManyRequestsError"}:
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status == 429 or status == "429":
        return True
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "too many requests" in text


def classify_model_error(exc: BaseException) -> ModelErrorClassification:
    """모델 호출 예외를 요청 한도·일시적 공급자 오류·인증·시간 초과·연결 오류 등으로 분류한다.

    재시도 여부와 상태 코드를 포함한 ModelErrorClassification을 반환한다.
    """

    raw_status = (
        getattr(exc, "status_code", None)
        or getattr(exc, "code", None)
        or getattr(getattr(exc, "response", None), "status_code", None)
    )
    try:
        status = int(raw_status) if raw_status is not None else None
    except (TypeError, ValueError):
        status = None
    name = exc.__class__.__name__.casefold()
    text = str(exc).casefold()
    if isinstance(exc, LLMBudgetExceeded):
        return ModelErrorClassification('llm_budget_exceeded', False, status)
    if quota_exhausted(exc):
        return ModelErrorClassification('provider_quota_exhausted', False, status)
    if _is_rate_limit_error(exc):
        return ModelErrorClassification("provider_rate_limit", True, 429)
    if status in {408, 425, 500, 502, 503, 504}:
        return ModelErrorClassification("provider_transient", True, status)
    if status in {401, 403}:
        return ModelErrorClassification("provider_auth", False, status)
    if (
        isinstance(exc, TimeoutError)
        or "timeout" in name
        or "timed out" in text
        or "deadline exceeded" in text
    ):
        return ModelErrorClassification("network_timeout", True, status)
    if (
        isinstance(exc, ConnectionError)
        or "connection" in name
        or "connection reset" in text
        or "connection refused" in text
        or "temporarily unavailable" in text
    ):
        return ModelErrorClassification("network_connection", True, status)
    return ModelErrorClassification("model_non_retryable", False, status)


def invoke_with_retry(model, messages):
    """Retry transient errors twice, but never retry auth or exhausted credit."""
    for attempt in range(3):
        try:
            return model.invoke(messages)
        except Exception as exc:
            if not classify_model_error(exc).retryable or attempt == 2:
                raise
            sleep(0.5 * 2 ** attempt)
