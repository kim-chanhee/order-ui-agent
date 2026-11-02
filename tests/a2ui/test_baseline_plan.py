"""Baseline must not depend on generated UI, but still validate analysis meaning."""
from langchain_core.messages import AIMessage
from langchain_core.output_parsers.openai_tools import PydanticToolsParser
from app.planning.planner.dynamic_planner import plan_dynamic_analysis
from app.planning.schema_context import PlannerSchemaContext

CONTEXT = PlannerSchemaContext(('customers',), 'customers(customer_id TEXT)', 'fixture')


class Transport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
    def with_structured_output(self, schema, **kwargs):
        self.schema = schema
        return self
    def invoke(self, prompt):
        self.calls += 1
        self.prompt = prompt
        return PydanticToolsParser(tools=[self.schema], first_tool_only=True).invoke(
            AIMessage(content='',tool_calls=[{'name':self.schema.__name__,'args':self.payload,'id':'plan'}]))


def payload(field='customer_id'):
    return {'analysis_plan':{'original_question':'전체 고객 수', 'metric':{'kind':'count','field':field,'distinct':True},
                             'target_entity':'customer','result_grain':'customer'},
            'summary':'전체 고객 수를 조회합니다.', 'requires_confirmation':True,
            'ui_blocks':[{'type':'invented_result_card','label':'잘못된 화면'}]}


def test_baseline_sdk_parser_drops_ui_without_retry():
    model = Transport(payload())
    result = plan_dynamic_analysis('전체 고객 수',schema_context=CONTEXT,llm=model,include_ui=False)
    assert result.analysis_plan.source == 'llm_dynamic_planner'
    assert result.analysis_plan.metric.field == 'customer_id'
    assert result.ui_blocks == []
    assert model.calls == 1
    assert model.schema.__name__ == 'AnalysisDraft'
    assert '\nUI\n' not in model.prompt


def test_baseline_still_rejects_ungrounded_aggregate_field():
    result = plan_dynamic_analysis('전체 고객 수',schema_context=CONTEXT,llm=Transport(payload('made_up_id')),include_ui=False)
    assert result.analysis_plan.source == 'safe_fallback'


def test_a2ui_keeps_strict_blueprint_validation():
    result = plan_dynamic_analysis('전체 고객 수',schema_context=CONTEXT,llm=Transport(payload()))
    assert result.analysis_plan.source == 'safe_fallback'
