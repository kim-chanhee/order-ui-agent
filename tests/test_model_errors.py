import pytest

from app.core.model_errors import invoke_with_retry
from app.execution.fast_sql_agent import classify_model_error, classify_failure_message
from app.execution.confirmed_execution import format_agent_failure_answer


class Exhausted(Exception):
    status_code=429


def test_credit_exhaustion_is_not_retried_or_described_as_wait_and_retry():
    error=Exhausted('429 credit_balance_exhausted: no credits remaining')
    class Model:
        calls=0
        def invoke(self,_):self.calls+=1;raise error
    model=Model()
    with pytest.raises(Exhausted):invoke_with_retry(model,[])
    assert model.calls==1
    assert not classify_model_error(error).retryable
    assert classify_failure_message(str(error))['failure_category']=='provider_quota_exhausted'
    assert '크레딧이 소진' in format_agent_failure_answer(error)


def test_quota_failure_response_is_not_retryable():
    from app.chat.dispatch import _chat_response
    from app.chat.turn_router import TurnDecision
    from app.routes.schemas import ChatRequest
    response=_chat_response(ChatRequest(question='조회'), 'test',
        TurnDecision(request_kind='conversation',confidence=0,failure_category='provider_quota_exhausted'),
        answer='크레딧 소진',kind='clarification')
    assert response['execution_result']['normalized_spec']['retryable'] is False


def test_reply_transient_failure_has_one_retry_layer(monkeypatch):
    from app.chat.responses import generate_reply
    monkeypatch.setattr('app.core.model_errors.sleep', lambda _: None)
    class Model:
        calls=0
        def invoke(self,_):
            self.calls+=1
            raise ConnectionError('offline')
    model=Model()
    generate_reply('조회',purpose='test',llm=model)
    assert model.calls == 3


def test_reply_auth_failure_is_not_retried():
    from app.chat.responses import generate_reply
    class AuthError(Exception): status_code=401
    class Model:
        calls=0
        def invoke(self,_):
            self.calls+=1
            raise AuthError('invalid API key')
    model=Model()
    generate_reply('조회',purpose='test',llm=model)
    assert model.calls == 1
