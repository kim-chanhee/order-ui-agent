"""Provider transports must avoid unsupported named tool_choice on LM Studio."""
import pytest
from app.core.llm_settings import resolve_agent_llm_settings, structured_output_options

@pytest.mark.parametrize('provider,method', [('lm_studio','required'),('local','required'),('openai',None)])
def test_structured_response_transport(monkeypatch,provider,method):
    monkeypatch.setenv('AGENT_PROVIDER',provider)
    assert structured_output_options().get('tool_choice')==method
    assert structured_output_options()['method']=='function_calling'


def test_local_connection_does_not_use_paid_provider_endpoint(monkeypatch):
    monkeypatch.setenv('AGENT_PROVIDER','lm_studio')
    monkeypatch.setenv('AGENT_BASE_URL','http://127.0.0.1:1234/v1')
    monkeypatch.setenv('AGENT_API_KEY','not-needed')
    monkeypatch.setenv('OPENAI_API_KEY','paid-key-must-not-be-used')
    provider,url,key,_,_=resolve_agent_llm_settings()
    assert (provider,url,key)==('lm_studio','http://127.0.0.1:1234/v1','not-needed')


def test_gpt_router_uses_strict_schema_without_changing_local_tools(monkeypatch):
    monkeypatch.setenv('AGENT_PROVIDER','openai')
    assert structured_output_options(strict=True) == {'method':'json_schema','strict':True}
    monkeypatch.setenv('AGENT_PROVIDER','lm_studio')
    assert structured_output_options(strict=True) == {'method':'function_calling','tool_choice':'required'}
