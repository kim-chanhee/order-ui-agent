import json
import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from app.core.llm_usage import LLMBudgetExceeded, UsageCallback, track_llm_request


def model():
    return FakeMessagesListChatModel(responses=[AIMessage(content='ok',usage_metadata={
        'input_tokens':10,'output_tokens':2,'total_tokens':12,
        'input_token_details':{'cache_read':4}})],callbacks=[UsageCallback('routing','test-model')])


def test_budget_stops_before_extra_model_call_and_records_actual_usage(tmp_path,monkeypatch):
    monkeypatch.setenv('ORDER_UI_LOG_DIR',str(tmp_path))
    monkeypatch.setenv('LLM_MAX_CALLS_PER_REQUEST','2')
    llm = model()
    @track_llm_request
    def request():
        llm.invoke('first');llm.invoke('second')
        with pytest.raises(LLMBudgetExceeded): llm.invoke('third')
        return {'execution_result':{'normalized_spec':{}}}
    result = request()['execution_result']['normalized_spec']['llm_usage']
    assert result['calls'] == 2
    assert result['input_tokens'] == 20
    assert result['output_tokens'] == 4
    assert result['cached_input_tokens'] == 8
    assert result['responses_with_usage'] == 2
    assert result['models'] == ['test-model']
    saved = json.loads((tmp_path/'llm_usage.jsonl').read_text())
    assert saved['calls'] == 2
    assert 'first' not in (tmp_path/'llm_usage.jsonl').read_text()


def test_scopes_are_independent_and_nested_calls_share_limit(tmp_path,monkeypatch):
    monkeypatch.setenv('ORDER_UI_LOG_DIR',str(tmp_path))
    monkeypatch.setenv('LLM_MAX_CALLS_PER_REQUEST','1')
    llm = model()
    @track_llm_request
    def inner(): return llm.invoke('data')
    @track_llm_request
    def outer():
        inner()
        with pytest.raises(LLMBudgetExceeded): inner()
        return {'execution_result':{'normalized_spec':{}}}
    first=outer();second=outer()
    a=first['execution_result']['normalized_spec']['llm_usage']
    b=second['execution_result']['normalized_spec']['llm_usage']
    assert a['calls'] == b['calls'] == 1
    assert a['request_id'] != b['request_id']


def test_usage_logging_failure_does_not_discard_success(tmp_path,monkeypatch):
    file = tmp_path/'not-a-directory';file.write_text('test')
    monkeypatch.setenv('ORDER_UI_LOG_DIR',str(file))
    llm=model()
    @track_llm_request
    def request():
        llm.invoke('data')
        return {'execution_result':{'normalized_spec':{}}}
    assert request()['execution_result']['normalized_spec']['llm_usage']['calls'] == 1


def test_prompt_size_guard_includes_tool_schema_and_prevents_dispatch(tmp_path,monkeypatch):
    monkeypatch.setenv('ORDER_UI_LOG_DIR',str(tmp_path))
    monkeypatch.setenv('LLM_MAX_PROMPT_BYTES','100')
    callback=UsageCallback('planner','test-model')
    @track_llm_request
    def request():
        with pytest.raises(LLMBudgetExceeded):
            callback.on_chat_model_start({},[],invocation_params={'tools':[{'schema':'x'*200}]})
        return {'execution_result':{'normalized_spec':{}}}
    assert request()['execution_result']['normalized_spec']['llm_usage']['calls']==0
