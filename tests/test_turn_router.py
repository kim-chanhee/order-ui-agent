import json

from app.chat.turn_router import route_turn


class RoutingModel:
    def __init__(self, decision):
        self.decision = decision
        self.messages = None

    def with_structured_output(self, *args, **kwargs):
        return self

    def invoke(self, messages):
        self.messages = messages
        return self.decision


def test_new_analysis_reaches_planner_despite_premature_clarification(tmp_path, monkeypatch):
    aliases = tmp_path / "aliases.json"
    aliases.write_text(json.dumps({"배송 실패": ["failed delivery"]}))
    monkeypatch.setenv("SCHEMA_VALUE_ALIASES_PATH", str(aliases))
    model = RoutingModel({
        "request_kind": "new_analysis", "confidence": 0.9,
        "clarification_question": "배송 실패는 어떤 상태를 의미하나요?",
    })

    decision = route_turn("60일 배송 실패 총 몇건이야?", [], llm=model)

    assert decision.requires_analysis
    assert decision.clarification_question is None
    evidence = json.loads(model.messages[1][1])
    assert evidence["canonical_value_aliases"] == "배송 실패 -> failed delivery"


def test_ambiguous_prior_result_still_requires_clarification():
    model = RoutingModel({
        "request_kind": "refine_analysis", "confidence": 0.9,
        "clarification_question": "어떤 이전 분석의 기간을 바꿀까요?",
    })

    decision = route_turn("그걸 30일로 바꿔줘", [], llm=model)

    assert not decision.requires_analysis
    assert decision.clarification_question == "어떤 이전 분석의 기간을 바꿀까요?"


def test_baseline_planner_failure_is_not_rewritten_as_missing_user_conditions(monkeypatch):
    from app.chat import dispatch
    from app.chat.turn_router import TurnDecision
    from app.execution.baseline import service
    from app.planning.planner.dynamic_planner import safe_clarification_plan
    from app.planning.ui_models import UiPlan
    from app.routes.schemas import ChatRequest

    failed = safe_clarification_plan('상품별 배송 실패 주문 수', reason='invalid planner transport')
    plan = UiPlan(**failed.model_dump(exclude={'ui_state', 'field_metadata'}))
    monkeypatch.setattr(service, 'build_review_plan', lambda *args, **kwargs: plan)
    def unexpected(*args, **kwargs):
        raise AssertionError('A technical planning failure must not invoke SQL or be paraphrased.')
    monkeypatch.setattr(service, 'execute_schema_question', unexpected)
    monkeypatch.setattr(dispatch, 'generate_reply', unexpected)
    response = dispatch._baseline_analysis_response(
        ChatRequest(question='상품별 배송 실패 주문 수', input_source='baseline'),
        'test', TurnDecision(request_kind='new_analysis', confidence=1), [],
    )
    assert '오류가 발생' in response['answer']
    spec = response['execution_result']['normalized_spec']
    assert spec['failure_stage'] == 'planning'
    assert spec['planning_warnings'] == ['invalid planner transport']


def test_router_failure_does_not_fabricate_a_data_answer():
    class BrokenModel:
        def with_structured_output(self,*args,**kwargs):return self
        def invoke(self,*args):raise ConnectionError('offline')
    decision=route_turn('실패율이 가장 높은 고객은?',[],llm=BrokenModel())
    assert decision.failure_category=='routing_service_unavailable'
    assert '오류가 발생' in decision.clarification_question
    assert not decision.requires_analysis
