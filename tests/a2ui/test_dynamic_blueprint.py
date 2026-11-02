"""Dynamic blueprints run through the real planner/validator using a fake LLM."""
from copy import deepcopy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.planning.analysis_models import AnalysisPlan
from app.planning.ui_models import UiPlan, UiBlock
from app.planning.schema_context import PlannerSchemaContext
from app.planning.planner.dynamic_planner import plan_dynamic_analysis
from app.planning.a2ui.validator import apply_plan_update, validate_ui_plan
from app.planning.a2ui.refinement import _merge_refinement_patch
from app.planning.a2ui.models import RefinementPatch
from app.planning.option_catalog import build_plan_option_catalog
from app.execution.sql_contract import validate_sql_contract, SqlContractViolation
from app.a2ui.review import surface_for_plan
from app.routes.a2ui import review

SCHEMA = '''TABLE: analysis_shipment_status_orders
analysis_shipment_status_orders(event_id TEXT, event_type TEXT, status_at TIMESTAMP, order_id TEXT, customer_id TEXT, courier_id TEXT)
  - event_type: failed delivery (3), package delivered (6)
TABLE: order_items
order_items(order_id TEXT, product_id TEXT, price REAL)
'''
CONTEXT = PlannerSchemaContext(('analysis_shipment_status_orders','order_items'),SCHEMA,'fixture')

class Model:
    def __init__(self, response): self.response=response; self.prompts=[]
    def with_structured_output(self, *args, **kwargs): return self
    def invoke(self, prompt): self.prompts.append(prompt); return deepcopy(self.response)

def block(path,label,kind='select',options=None,**kwargs):
    return dict(key=path.replace('.','_'),field_path=path,label=label,type=kind,
                description=f'{label}을 확인합니다.',options=options or [],**kwargs)

def draft(which='A'):
    plan=dict(original_question='분석',date_range={'mode':'relative','relative_days':7},
              metric={'kind':'count','field':'order_id','unit':'order'},event_types=['failed delivery'])
    blocks=[block('metric.kind','배송 실패 주문 수','option_cards',[{'value':'count','label':'배송 실패 주문 수'}]),block('date_range','조회할 최근 기간','date_range')]
    if which=='B':
        plan.update(date_range={'mode':'relative','relative_days':30},event_types=[],group_by=['customer_id'],
                    metric={'kind':'ratio','semantic_id':'shipment_failure_rate','unit':'배송 실패율'},sort=[{'field':'metric','direction':'desc'}])
        blocks=[block('metric.semantic_id','고객별 배송 실패율'),block('date_range','분석할 30일','date_range'),block('group_by','고객 단위','multi_select'),block('sort[0].direction','실패율 높은 순')]
    if which=='C':
        plan.update(date_range={'mode':'all_time'},event_types=['failed delivery','package delivered'],group_by=['month','event_type'],
                    metric={'kind':'count','field':'event_id','unit':'event'},comparison='event_vs_event',output={'view':'chart'})
        blocks=[block('event_types','비교할 배송 이벤트','multi_select'),block('comparison','이벤트 비교 방식','choice'),block('group_by','월별 추이','multi_select'),block('metric.kind','이벤트 발생 횟수','option_cards',[{'value':'count','label':'이벤트 발생 횟수'}]),block('output.view','그래프 표시','choice')]
    return dict(analysis_plan=plan,ui_blocks=blocks,summary=f'{which} 분석 목적 요약')

@pytest.fixture(autouse=True)
def isolated(monkeypatch,tmp_path):
    # Pin semantics and prevent date preview from using the developer DB.
    from pathlib import Path
    monkeypatch.setenv('ANALYSIS_SEMANTICS_PATH',str(Path(__file__).resolve().parents[2]/'Data/docs/analysis_semantics.json'))
    monkeypatch.setenv('ORDER_UI_STATE_DB_PATH',str(tmp_path/'state.sqlite'))
    monkeypatch.setattr('app.planning.planner.dynamic_planner.resolve_plan_temporal_preview',lambda p:p)


def generate(which='A', response=None):
    model=Model(response or draft(which))
    output=plan_dynamic_analysis('사용자 질문 '+which,schema_context=CONTEXT,llm=model)
    assert output.analysis_plan.source != 'safe_fallback', output.warnings
    return output

def ui(output):
    return UiPlan(analysis_plan=output.analysis_plan,ui_blocks=output.ui_blocks,ui_state=output.ui_state,summary=output.summary)

@pytest.mark.parametrize('which,size',[('A',2),('B',4),('C',5)])
def test_llm_blueprints_retain_variable_count_order_labels_and_internal_scope(which,size):
    output=generate(which)
    original=draft(which)
    assert len(output.ui_blocks)==size
    assert [(b.key,b.label,b.description,b.section) for b in output.ui_blocks]==[(b['key'],b['label'],b['description'],'primary') for b in original['ui_blocks']]
    if which=='A':
        assert 'event_types' not in {b.field_path for b in output.ui_blocks}
        assert output.analysis_plan.event_types==['failed delivery']
        assert output.analysis_plan.metric.distinct
    validate_ui_plan(ui(output),output.analysis_plan.original_question)


def test_more_than_five_primary_blocks_are_not_capped_or_reordered():
    raw=draft('C')
    raw['ui_blocks'] += [block('limit','최대 표시 개수','number'),block('date_range','선택 기간','date_range')]
    output=generate(response=raw)
    assert len(output.ui_blocks)==7
    assert all(b.section=='primary' for b in output.ui_blocks)


def test_model_can_write_different_labels_for_same_component():
    assert generate('A').ui_blocks[0].label != generate('C').ui_blocks[3].label

@pytest.mark.parametrize('bad',[ 'unknown_dimension','month_without_time','unregistered_component','invalid_option','bad_ratio' ])
def test_invalid_blueprints_require_confirmation_without_silent_condition_deletion(bad):
    raw=draft('C')
    context=CONTEXT
    if bad=='unknown_dimension':raw['analysis_plan']['group_by']=['age_band']
    if bad=='month_without_time':context=PlannerSchemaContext((),SCHEMA.replace('status_at TIMESTAMP','status TEXT'),'no-time')
    if bad=='unregistered_component':raw['ui_blocks'][0]['type']='custom_script'
    if bad=='invalid_option':raw['ui_blocks'][0]['options']=[{'value':'made up event','label':'가짜 이벤트'}]
    if bad=='bad_ratio':
        raw=draft('B');raw['analysis_plan']['metric'].update(numerator='order_id',denominator='customer_id')
    output=plan_dynamic_analysis('분석',schema_context=context,llm=Model(raw))
    assert output.analysis_plan.source=='safe_fallback'
    assert output.analysis_plan.unresolved_constraints


def test_catalog_does_not_accept_selected_but_unverified_dimension_or_offer_unavailable_average():
    plan=AnalysisPlan(original_question='분석',group_by=['fake'])
    catalog=build_plan_option_catalog('orders(order_id TEXT, customer_id TEXT)',plan)
    assert 'fake' not in {o.value for o in catalog.group_by}
    assert 'avg' not in {o.value for o in catalog.metric_kinds}
    assert 'month' not in {o.value for o in catalog.group_by}


def test_period_ui_and_chat_patch_use_the_same_update_and_preserve_unedited_scope():
    output=generate()
    original=output.analysis_plan
    candidate=original.model_copy(deep=True)
    candidate.date_range=original.date_range.model_copy(update={'relative_days':30})
    direct=apply_plan_update(original,candidate,output.ui_blocks,output.ui_state['semantic_catalog'])
    refined=_merge_refinement_patch(original,output.ui_blocks,RefinementPatch(updates=[{'path':'date_range','value':{'mode':'relative','relative_days':30}}]),question=original.original_question,catalog=output.ui_state['semantic_catalog'],schema_context=CONTEXT)
    assert direct.model_dump(exclude={'source'})==refined.analysis_plan.model_dump(exclude={'source'})
    assert direct.event_types==original.event_types
    assert direct.metric==original.metric
    assert original.date_range.relative_days==7


def test_chat_can_change_a_supported_hidden_dimension_without_replanning_other_conditions():
    output=generate()
    result=_merge_refinement_patch(output.analysis_plan,output.ui_blocks,RefinementPatch(updates=[{'path':'group_by','value':['customer_id']}]),question=output.analysis_plan.original_question,catalog=output.ui_state['semantic_catalog'],schema_context=CONTEXT)
    assert result.analysis_plan.group_by==['customer_id']
    assert result.analysis_plan.event_types==output.analysis_plan.event_types
    assert result.analysis_plan.date_range==output.analysis_plan.date_range
    assert len(result.ui_blocks)==2


def test_metric_edit_updates_only_headline_mirror_and_count_unit():
    output=generate()
    original=output.analysis_plan.model_copy(deep=True)
    original.metrics=[original.metric.model_copy(deep=True)]
    candidate=original.model_copy(deep=True);candidate.metric.field='customer_id'
    blocks=[*output.ui_blocks, UiBlock(**block('metric.field','집계 대상'))]
    # Use the catalog options that a real server would issue.
    blocks[-1].options=build_plan_option_catalog(SCHEMA,original).count_fields
    updated=apply_plan_update(original,candidate,blocks,output.ui_state['semantic_catalog'])
    assert updated.metric.unit=='customer'
    assert updated.metrics==[updated.metric]
    assert updated.event_types==original.event_types


def test_registered_ratio_rejects_incompatible_product_breakdown():
    output=generate('B');candidate=output.analysis_plan.model_copy(deep=True);candidate.group_by=['product_id']
    with pytest.raises(ValueError,match='지원.*집계'):
        apply_plan_update(output.analysis_plan,candidate,output.ui_blocks,output.ui_state['semantic_catalog'])


def test_dynamic_surface_update_is_not_execution_and_stale_confirm_is_rejected(monkeypatch):
    output=generate();plan=ui(output)
    surface=surface_for_plan(plan,[],participant_id=None,thread_id='dynamic')
    app=FastAPI();app.include_router(review.router);client=TestClient(app)
    monkeypatch.setattr(review,'confirm_response_payload',lambda _:pytest.fail('must not execute on save'))
    request=dict(question=plan.analysis_plan.original_question,plan=plan.model_dump(mode='json'),surface_id=surface['surface_id'],plan_id=surface['plan_id'],revision=1)
    request['plan']['analysis_plan']['date_range']['relative_days']=30
    saved=client.post('/api/review/update',json=request)
    assert saved.status_code==200,saved.text
    assert saved.json()['revision']==2
    assert len(saved.json()['plan']['ui_blocks'])==2
    assert client.post('/api/review/confirm',json=request).status_code==409


def test_month_sql_must_group_a_real_month_not_an_arbitrary_alias():
    plan=generate('C').analysis_plan
    correct="SELECT strftime('%Y-%m',status_at) AS month,event_type,COUNT(DISTINCT event_id) AS n FROM analysis_shipment_status_orders GROUP BY month,event_type"
    assert validate_sql_contract(plan,correct,schema_context=SCHEMA)==correct
    with pytest.raises(SqlContractViolation,match='temporal_group_mismatch'):
        validate_sql_contract(plan,correct.replace("strftime('%Y-%m',status_at)","event_type"),schema_context=SCHEMA)


def test_registered_rate_sql_cannot_count_customers_or_narrow_the_denominator():
    plan=generate('B').analysis_plan
    sql="SELECT customer_id,1.0*COUNT(DISTINCT CASE WHEN event_type='failed delivery' THEN order_id END)/NULLIF(COUNT(DISTINCT order_id),0) AS rate FROM analysis_shipment_status_orders GROUP BY customer_id ORDER BY rate DESC"
    assert validate_sql_contract(plan,sql,schema_context=SCHEMA)==sql
    for broken in [sql.replace('NULLIF(COUNT(DISTINCT order_id)','NULLIF(COUNT(DISTINCT customer_id)'),sql.replace(' GROUP BY'," WHERE event_type='failed delivery' GROUP BY"),sql.replace('1.0*','')]:
        with pytest.raises(SqlContractViolation,match='semantic_ratio_population'):
            validate_sql_contract(plan,broken,schema_context=SCHEMA)


def test_switch_to_registered_ratio_derives_population_and_headline_mirror():
    from app.planning.ui_models import UiOption
    output=generate()
    output.ui_blocks[0].options=[UiOption(value='count',label='건수'),UiOption(value='ratio',label='배송 실패율')]
    original=output.analysis_plan.model_copy(deep=True)
    original.metrics=[original.metric.model_copy(deep=True)]
    changed=original.model_copy(deep=True);changed.metric.kind='ratio'
    result=apply_plan_update(original,changed,output.ui_blocks,output.ui_state['semantic_catalog'])
    assert result.metric.semantic_id=='shipment_failure_rate'
    assert result.metrics==[result.metric]
    assert set(result.event_types)=={'failed delivery','package delivered'}


def test_ratio_definition_tampering_and_hidden_scope_changes_are_rejected():
    output=generate('B')
    candidate=output.analysis_plan.model_copy(deep=True)
    candidate.metric.denominator='customer_id'
    with pytest.raises(ValueError,match='정의가'):
        apply_plan_update(output.analysis_plan,candidate,output.ui_blocks,output.ui_state['semantic_catalog'])
    candidate=output.analysis_plan.model_copy(deep=True)
    raw=candidate.model_dump(mode='json')
    raw['filters']=[{'field':'customer_id','operator':'eq','value':'invented'}]
    candidate=AnalysisPlan.model_validate(raw)
    with pytest.raises(ValueError,match='outside editable'):
        apply_plan_update(output.analysis_plan,candidate,output.ui_blocks,output.ui_state['semantic_catalog'])


@pytest.mark.parametrize('metric',[
    {'kind':'count','field':'order_id','unit':'customer'},
    {'kind':'avg','field':'price','unit':'평균 배송 시간'},
])
def test_a_plausible_field_cannot_mask_inconsistent_metric_semantics(metric):
    raw=draft();raw['analysis_plan']['metric']=metric
    raw['ui_blocks'][0]['options']=[]
    output=plan_dynamic_analysis('분석',schema_context=CONTEXT,llm=Model(raw))
    assert output.analysis_plan.source=='safe_fallback'
    assert output.infeasible


def parse_sdk_payload(payload):
    """Exercise the actual SDK tool parser, not the dict-returning test double."""
    from langchain_core.messages import AIMessage
    from langchain_core.output_parsers.openai_tools import PydanticToolsParser
    from app.planning.planner.models import PlannerDraft
    return PydanticToolsParser(tools=[PlannerDraft], first_tool_only=True).invoke(
        AIMessage(content='', tool_calls=[{'name':'PlannerDraft','args':payload,'id':'regression'}]))


@pytest.mark.parametrize('which', ['A','B','C'])
def test_real_sdk_parser_accepts_dynamic_blueprints(which):
    parsed=parse_sdk_payload(draft(which))
    assert len(parsed.ui_blocks)==len(draft(which)['ui_blocks'])
    assert generate(which,parsed.model_dump(mode='json')).analysis_plan.source=='llm_dynamic_planner'


@pytest.mark.parametrize('location', ['root', 'plan', 'both'])
def test_sdk_parser_repairs_provenance_before_nested_validation(location):
    raw = draft('B')
    metadata = {'product_name': {'status': 'required', 'source': 'llm',
                                 'semantic_type': 'display_name', 'label': '상품명'}}
    if location in {'root', 'both'}:
        raw['field_metadata'] = metadata
    if location in {'plan', 'both'}:
        raw['analysis_plan']['field_metadata'] = metadata
    parsed = parse_sdk_payload(raw)
    output = generate('B', parsed.model_dump(mode='json'))
    repaired = output.analysis_plan.field_metadata['product_name']
    assert repaired.status == 'needs_confirmation'
    assert repaired.source == 'llm_inferred'
    assert repaired.label == '상품명'
    assert output.analysis_plan.group_by == ['customer_id']


def test_sdk_metadata_repair_does_not_hide_invalid_analysis_fields():
    raw = draft('B')
    raw['analysis_plan']['invented_filter'] = 'failed'
    with pytest.raises(ValueError, match='invented_filter'):
        parse_sdk_payload(raw)


def test_grounded_product_name_grouping_reaches_review():
    schema = SCHEMA.replace('product_id TEXT, price REAL', 'product_id TEXT, product_name TEXT, price REAL')
    context = PlannerSchemaContext(CONTEXT.table_names, schema, 'product-names')
    raw = draft('A')
    raw['analysis_plan']['group_by'] = ['product_name']
    raw['ui_blocks'].append(block('group_by', '상품별', 'multi_select',
                                  [{'value': 'product_name', 'label': '상품명별'}]))
    out = plan_dynamic_analysis('상품별 배송 실패 주문 수', schema_context=context, llm=Model(raw))
    assert out.analysis_plan.source == 'llm_dynamic_planner', out.warnings
    assert out.analysis_plan.group_by == ['product_name']
    groups = {o.value for o in build_plan_option_catalog(schema, out.analysis_plan).group_by}
    assert 'product_name' in groups
    assert 'item_name' not in groups  # Declared role without a real column.
    assert 'price' not in groups


def test_unreachable_display_name_is_not_a_grouping_option():
    schema = SCHEMA + '\nTABLE: unrelated\nunrelated(product_name TEXT)\n'
    groups = build_plan_option_catalog(schema, AnalysisPlan.model_validate(draft('A')['analysis_plan'])).group_by
    assert 'product_name' not in {o.value for o in groups}


@pytest.mark.parametrize('path', ['metrics[0].kind', 'metrics.0.kind'])
def test_list_only_headline_metric_control_uses_synchronized_primary_editor(path):
    raw = draft('A')
    metric = raw['analysis_plan'].pop('metric')
    raw['analysis_plan']['metrics'] = [metric]
    raw['ui_blocks'][0]['field_path'] = path
    output = generate('A', parse_sdk_payload(raw).model_dump(mode='json'))
    assert output.analysis_plan.metric == output.analysis_plan.metrics[0]
    assert output.ui_blocks[0].field_path == 'metric.kind'


@pytest.mark.parametrize('mode', ['direct_event_link','parent_membership','entity_lifecycle','order_lifecycle'])
def test_semantic_relationship_modes_do_not_require_an_invented_physical_edge(mode):
    raw=draft('A');raw['analysis_plan']['relationship_scope']=mode
    output=generate('A',raw)
    assert output.analysis_plan.relationship_scope == ('entity_lifecycle' if mode=='order_lifecycle' else mode)


def test_unregistered_relationship_name_is_still_rejected():
    raw=draft('A');raw['analysis_plan']['relationship_scope']='invented_business_join'
    output=plan_dynamic_analysis('분석',schema_context=CONTEXT,llm=Model(raw))
    assert output.analysis_plan.source=='safe_fallback'


def test_sdk_parser_repairs_matching_defaults_without_creating_selection_state():
    raw=draft('B')
    group=raw['ui_blocks'][2]
    group.update(type='group_by',default='customer_id',props={'defaultValue':['customer_id']},
                 options=[{'value':'customer_id','label':'고객별','default':True}])
    raw['ui_blocks'][3]['type']='sort'
    parsed=parse_sdk_payload(raw)
    repaired=parsed.ui_blocks[2]
    assert repaired.type=='multi_select'
    assert repaired.props=={}
    assert parsed.analysis_plan.group_by==['customer_id']
    assert repaired.options[0].model_dump()=={'value':'customer_id','label':'고객별','description':None}
    assert parsed.ui_blocks[3].type=='choice'


@pytest.mark.parametrize('change', ['conflicting_default','conflicting_option','unknown_component','forbidden_path','script'])
def test_sdk_parser_still_blocks_conflicting_or_unsafe_ui(change):
    raw=draft('B');b=raw['ui_blocks'][2]
    if change=='conflicting_default':b['props']={'defaultValue':'product_id'}
    if change=='conflicting_option':b['options']=[{'value':'product_id','label':'상품별','selected':True}]
    if change=='unknown_component':b['type']='execute_script'
    if change=='forbidden_path':b['field_path']='execution_policy'
    if change=='script':b['props']={'onclick':'alert(1)'}
    with pytest.raises(ValueError):parse_sdk_payload(raw)


def test_invalid_sdk_response_is_repaired_by_retry_with_feedback():
    from app.planning.planner.models import PlannerDraft
    from langchain_core.messages import AIMessage
    from langchain_core.output_parsers.openai_tools import PydanticToolsParser
    invalid=draft('B');invalid['ui_blocks'][2]['default']='product_id'
    class Transport:
        prompts=[]
        def with_structured_output(self,schema,**kwargs):
            assert schema is PlannerDraft
            return self
        def invoke(self,prompt):
            self.prompts.append(prompt)
            raw=invalid if len(self.prompts)==1 else draft('B')
            return PydanticToolsParser(tools=[schema], first_tool_only=True).invoke(AIMessage(content='',tool_calls=[{'name':'PlannerDraft','args':raw,'id':'retry'}]))
    schema=PlannerDraft
    model=Transport()
    out=plan_dynamic_analysis('고객별 배송 실패율',schema_context=CONTEXT,llm=model)
    assert out.analysis_plan.source=='llm_dynamic_planner'
    assert len(model.prompts)==2
    assert 'conflicts with AnalysisPlan' in model.prompts[1]


def test_readonly_infeasible_reason_is_retained_without_editable_path():
    from app.planning.planner.response import _repair_raw_infeasible
    result=_repair_raw_infeasible([{'field_path':'relationship_scope','label':'관계 확인','reason':'관계를 확인해야 합니다.'}])
    assert result[0]['reason']=='관계를 확인해야 합니다.'
    assert result[0]['field_path'] is None


def test_sdk_parser_preserves_infeasible_diagnostic_for_readonly_semantic_field():
    raw = draft('A')
    raw['infeasible'] = [{'field_path': 'relationship_scope', 'label': '관계 확인',
                          'reason': '관계를 확인해야 합니다.'}]
    parsed = parse_sdk_payload(raw)
    assert parsed.infeasible[0].reason == '관계를 확인해야 합니다.'
    assert parsed.infeasible[0].field_path is None


def test_refinement_prompt_contains_authoritative_metric_catalog():
    from app.planning.a2ui.refinement import _refinement_prompt
    plan=AnalysisPlan.model_validate(draft('A')['analysis_plan'])
    prompt=_refinement_prompt('분석',plan,[],'실패율로 변경',CONTEXT)
    assert 'shipment_failure_rate' in prompt
    assert 'failed_delivery_orders' in prompt
    assert 'shipment_orders' in prompt
