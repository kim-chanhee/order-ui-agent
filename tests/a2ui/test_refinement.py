import pytest

from app.planning.a2ui.models import RefinementPatch
from app.planning.a2ui.refinement import refine_dynamic_analysis, _merge_refinement_patch
from app.planning.a2ui.validator import validate_editable_analysis_plan
from app.planning.analysis_models import AnalysisPlan
from app.planning.schema_context import PlannerSchemaContext
from app.planning.ui_models import UiBlock, UiOption


class Model:
    def __init__(self, result):
        self.result = result
        self.prompt = ""

    def with_structured_output(self, schema, **kwargs):
        assert schema is RefinementPatch
        return self

    def invoke(self, prompt):
        self.prompt = prompt
        return self.result


CONTEXT = PlannerSchemaContext((), "order_id, customer_id, event_type", "test")


def plan_and_blocks():
    plan = AnalysisPlan(original_question="주문 건수", date_range={"mode": "relative", "relative_days": 7},
                        metric={"kind": "count", "field": "order_id"}, group_by=["customer_id"])
    blocks = [UiBlock(type="date_range", key="period", field_path="date_range", label="기간"),
              UiBlock(type="multi_select", key="group", field_path="group_by", label="집계",
                      options=[UiOption(value="customer_id", label="고객별"), UiOption(value="day", label="일별")])]
    return plan, blocks


def test_real_refinement_pipeline_applies_period_and_preserves_other_fields():
    plan, blocks = plan_and_blocks()
    model = Model({"updates": [{"path": "date_range", "value": {"mode": "relative", "relative_days": 30}}]})
    result = refine_dynamic_analysis(plan.original_question, plan, blocks, "30일로 변경", schema_context=CONTEXT, llm=model)
    assert result.analysis_plan.date_range.relative_days == 30
    assert result.analysis_plan.date_anchor.strategy == "dataset_max"
    assert result.analysis_plan.group_by == plan.group_by
    assert result.analysis_plan.metric == plan.metric
    assert plan.date_range.relative_days == 7
    assert not result.analysis_plan.unresolved_constraints
    assert 'replace date_range' in model.prompt


@pytest.mark.parametrize("update", [
    {"path": "limit", "value": 50},  # valid field, but not issued by this UI
    {"path": "group_by", "value": ["invented_column"]},
    {"path": "date_range", "value": {"mode": "relative", "relative_days": -1}},
])
def test_invalid_model_edits_preserve_plan_and_request_clarification(update):
    plan, blocks = plan_and_blocks()
    result = refine_dynamic_analysis(plan.original_question, plan, blocks, "조건 변경", schema_context=CONTEXT, llm=Model({"updates": [update]}))
    assert result.analysis_plan.date_range == plan.date_range
    assert result.analysis_plan.group_by == plan.group_by
    assert result.analysis_plan.limit == plan.limit
    assert result.analysis_plan.unresolved_constraints


def test_followup_can_resolve_failed_additional_constraint():
    plan, blocks = plan_and_blocks()
    message = "추가 조건 '기간 변경'의 구체적인 기준을 확인해야 합니다."
    plan.unresolved_constraints = [message]
    patch = RefinementPatch(updates=[{"path": "date_range", "value": {"mode": "relative", "relative_days": 30}}], resolve_constraints=[message])
    result = _merge_refinement_patch(plan, blocks, patch, question=plan.original_question)
    assert not result.analysis_plan.unresolved_constraints
    assert result.analysis_plan.date_range.relative_days == 30


def test_cannot_clear_original_infeasibility():
    plan, blocks = plan_and_blocks()
    plan.unresolved_constraints = ["지원되지 않는 지역 정보"]
    with pytest.raises(ValueError):
        _merge_refinement_patch(plan, blocks, RefinementPatch(resolve_constraints=plan.unresolved_constraints), question=plan.original_question)


def test_nested_field_permission_cannot_create_unissued_sibling():
    original = AnalysisPlan(original_question="분석")
    blocks = [UiBlock(type="select", key="kind", field_path="metric.kind", label="방식")]
    legitimate = AnalysisPlan.model_validate({**original.model_dump(), "metric": {"kind": "count"}})
    validate_editable_analysis_plan(original, legitimate, blocks)
    injected = legitimate.model_copy(deep=True)
    injected.metric.field = "unissued_field"
    with pytest.raises(ValueError, match="outside editable fields"):
        validate_editable_analysis_plan(original, injected, blocks)
