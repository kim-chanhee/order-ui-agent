"""요청별 모델 호출 상한과 공급자가 보고한 토큰 사용량. 프롬프트·키는 기록하지 않는다."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler


class LLMBudgetExceeded(RuntimeError):
    """추가 과금 호출을 보내기 전에 적용하는 애플리케이션 제한."""


@dataclass
class RequestUsage:
    request_id: str = field(default_factory=lambda: str(uuid4()))
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    responses_with_usage: int = 0
    max_calls: int = field(default_factory=lambda: int(os.environ.get('LLM_MAX_CALLS_PER_REQUEST', '12')))
    calls_by_purpose: dict[str, int] = field(default_factory=dict)
    models: list[str] = field(default_factory=list)

    def snapshot(self):
        return {'usage_complete': self.responses_with_usage == self.calls} | {k: getattr(self, k) for k in ('request_id', 'calls', 'input_tokens', 'output_tokens',
                                              'cached_input_tokens', 'responses_with_usage', 'max_calls', 'calls_by_purpose', 'models')}


_CURRENT: ContextVar[RequestUsage | None] = ContextVar('llm_request_usage', default=None)


class UsageCallback(BaseCallbackHandler):
    raise_error = True
    run_inline = True

    def __init__(self, purpose: str, model: str = ''):
        self.purpose = purpose
        self.model = model

    def on_chat_model_start(self, serialized, messages, **kwargs):
        state = _CURRENT.get()
        if state is not None and state.calls >= state.max_calls:
            raise LLMBudgetExceeded('llm_budget_exceeded: request model-call limit reached')
        # Include tool schemas, which otherwise escape message-only size checks.
        payload = json.dumps([messages, kwargs.get('invocation_params', {})], default=str, ensure_ascii=False)
        if len(payload.encode('utf-8')) > int(os.environ.get('LLM_MAX_PROMPT_BYTES', '120000')):
            raise LLMBudgetExceeded('llm_budget_exceeded: prompt byte limit reached')
        if state is not None:
            state.calls += 1
            if self.model and self.model not in state.models:
                state.models.append(self.model)
            state.calls_by_purpose[self.purpose] = state.calls_by_purpose.get(self.purpose, 0) + 1

    def on_llm_end(self, response, **kwargs):
        state = _CURRENT.get()
        if state is None:
            return
        message = response.generations[0][0].message if response.generations and response.generations[0] else None
        usage = getattr(message, 'usage_metadata', None)
        if usage:
            state.input_tokens += usage.get('input_tokens', 0)
            state.output_tokens += usage.get('output_tokens', 0)
            state.cached_input_tokens += (usage.get('input_token_details') or {}).get('cache_read', 0)
        else:
            usage = (response.llm_output or {}).get('token_usage')
            if not usage:
                return
            state.input_tokens += usage.get('prompt_tokens', 0)
            state.output_tokens += usage.get('completion_tokens', 0)
            state.cached_input_tokens += (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0)
        state.responses_with_usage += 1


def track_llm_request(function):
    """직접 호출과 spawn 워커 모두에서 같은 요청 한도·사용량을 적용한다."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        if _CURRENT.get() is not None:
            return function(*args, **kwargs)
        state = RequestUsage()
        if state.max_calls < 1:
            raise ValueError('LLM_MAX_CALLS_PER_REQUEST must be positive')
        token = _CURRENT.set(state)
        try:
            result = function(*args, **kwargs)
            if isinstance(result, dict) and result.get('execution_result'):
                result['execution_result'].setdefault('normalized_spec', {})['llm_usage'] = state.snapshot()
            return result
        finally:
            _CURRENT.reset(token)
            if state.calls:
                from app.runtime.state_store import get_state_db_path
                directory = Path(os.environ.get('ORDER_UI_LOG_DIR', str(get_state_db_path().parent / 'logs')))
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                    record = {'created_at': datetime.now(timezone.utc).isoformat(), 'operation': function.__name__, **state.snapshot()}
                    fd = os.open(directory / 'llm_usage.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                    try:
                        os.write(fd, (json.dumps(record, ensure_ascii=False) + '\n').encode())
                    finally:
                        os.close(fd)
                except OSError:
                    logging.getLogger(__name__).warning('Unable to persist model usage; response metadata retained.', exc_info=True)
    return wrapped
