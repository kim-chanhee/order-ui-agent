"""Actual OpenAI/LangChain JSON Schema parsing with a local HTTP transport; no paid API."""
import json
import httpx
from langchain_openai import ChatOpenAI
from app.chat.turn_router import route_turn


def test_router_uses_strict_response_schema_through_actual_sdk(monkeypatch):
    monkeypatch.setenv('AGENT_PROVIDER','openai')
    captured=[]
    decision={'request_kind':'new_analysis','context_reference':None,'presentation':None,'confidence':0.95,
              'clarification_question':None,'reply':'','resolved_question':None,'context_ambiguous':False,
              'failure_category':None}
    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'id':'chatcmpl-local','object':'chat.completion','created':0,
            'model':'gpt-4.1-mini-2025-04-14','choices':[{'index':0,'finish_reason':'stop',
            'message':{'role':'assistant','content':json.dumps(decision)}}],
            'usage':{'prompt_tokens':100,'completion_tokens':40,'total_tokens':140}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        llm=ChatOpenAI(model='gpt-4.1-mini-2025-04-14',api_key='test',base_url='https://example.test/v1',
                       http_client=client,max_retries=0,max_completion_tokens=700)
        result=route_turn('전체 고객 수',[],llm=llm)
    assert result.requires_analysis
    assert len(captured)==1
    format=captured[0]['response_format']
    assert format['type']=='json_schema'
    assert format['json_schema']['strict'] is True
    schema=format['json_schema']['schema']
    assert set(schema['required'])==set(schema['properties'])
    assert schema['additionalProperties'] is False
    assert captured[0]['max_completion_tokens']==700
