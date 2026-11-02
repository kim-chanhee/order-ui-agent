import json
import sqlite3

import pytest

from app.execution import sql_builder, schema_tools, confirmed_context
from app.execution.confirmed_context import ConfirmedAnalysisContext
from app.execution.registered_metrics import compile_registered_metric, try_registered_metric
from app.execution.sql_contract import SqlContractViolation, validate_sql_contract
from app.planning.analysis_models import AnalysisPlan, MetricSpec, FilterSpec


@pytest.fixture
def clinical_data(tmp_path,monkeypatch):
    db=tmp_path/'clinic.sqlite'
    with sqlite3.connect(db) as c:
        c.executescript('CREATE TABLE visits(visit_key TEXT,ward TEXT,occurred_at TEXT);'
                       'CREATE TABLE incidents(visit_ref TEXT,status TEXT,reported_at TEXT);')
        c.executemany('INSERT INTO visits VALUES(?,?,?)',[
            ('v1','A','2026-10-01'),('v2','A','2026-10-02'),('v3','A','2026-10-03'),('v4','B','2026-10-03')])
        c.executemany('INSERT INTO incidents VALUES(?,?,?)',[
            ('v1','flagged','2026-10-02'),('v1','flagged','2026-10-03'),('v9','flagged','2026-10-03')])
    definition={'kind':'ratio','label':'Flagged visits rate','table':'visits','field':'visit_key',
        'event_field':'ward','time_field':'occurred_at','group_by':['ward'],
        'numerator':'flagged_visits','denominator':'all_visits',
        'population':{'table':'visits','key':'visit_key','time_field':'occurred_at'},
        'subset':{'table':'incidents','key':'visit_ref','time_field':'reported_at','filters':{'status':'flagged'}}}
    config={'timeline_anchor':{'table':'visits','field':'occurred_at'},'semantic_metrics':{'flag_rate':definition}}
    path=tmp_path/'semantics.json';path.write_text(json.dumps(config))
    aliases=tmp_path/'aliases.json';aliases.write_text('{}')
    summary=tmp_path/'summary.md';summary.write_text('')
    monkeypatch.setenv('ANALYSIS_SEMANTICS_PATH',str(path))
    monkeypatch.setenv('SCHEMA_VALUE_ALIASES_PATH',str(aliases))
    monkeypatch.setenv('SCHEMA_SUMMARY_PATH',str(summary))
    monkeypatch.setenv('ORDER_UI_STATE_DB_PATH',str(tmp_path/'state.sqlite'))
    for module in [sql_builder,schema_tools,confirmed_context]:monkeypatch.setattr(module,'DEFAULT_DB_PATH',db)
    return AnalysisPlan(original_question='3일간 병동별 문제 발생 비율',
        date_range={'mode':'relative','relative_days':3},group_by=['ward'],
        metric=MetricSpec(kind='ratio',field='visit_key',semantic_id='flag_rate',numerator='flagged_visits',denominator='all_visits'))


def test_registered_population_compiler_works_for_an_unrelated_domain(clinical_data):
    p=clinical_data
    result=try_registered_metric(ConfirmedAnalysisContext.from_plan(p,original_question=p.original_question,surface_id='clinic',revision=1))
    assert result.execution_route=='registered_metric' and result.model_calls==0
    assert result.rows==[
        {'ward':'A','population_count':3,'subset_count':1,'rate':0.3333},
        {'ward':'B','population_count':1,'subset_count':0,'rate':0.0}]


def test_registered_population_cannot_be_narrowed_or_sql_injected(clinical_data):
    p=clinical_data;sql=compile_registered_metric(p)
    with pytest.raises(SqlContractViolation,match='registered_metric_query'):
        validate_sql_contract(p,sql.replace('LEFT JOIN','INNER JOIN'))
    p.filters=[FilterSpec(field='ward',operator='eq',value="A' OR 1=1 --")]
    assert "'A'' OR 1=1 --'" in compile_registered_metric(p)


def test_registered_compiler_does_not_discard_independent_metrics(clinical_data):
    clinical_data.metrics=[MetricSpec(kind='avg',field='temperature')]
    with pytest.raises(ValueError,match='additional metrics'):
        compile_registered_metric(clinical_data)


def test_reused_sql_aliases_are_checked_within_each_cte(clinical_data):
    schema='visits(visit_key TEXT, ward TEXT, occurred_at TEXT)\nincidents(visit_ref TEXT,status TEXT,reported_at TEXT)'
    sql='WITH x AS (SELECT b.ward FROM visits b),y AS (SELECT b.status FROM incidents b) SELECT * FROM x CROSS JOIN y'
    assert validate_sql_contract(None,sql,schema_context=schema)==sql
    with pytest.raises(SqlContractViolation,match='unknown_column'):
        validate_sql_contract(None,sql.replace('b.ward','b.status'),schema_context=schema)


def test_both_modes_use_the_same_registered_execution_and_rows(clinical_data,monkeypatch):
    from app.execution.baseline import service as baseline
    from app.execution.a2ui import service as agent2ui
    from app.planning.ui_models import UiPlan
    from app.routes.schemas import ChatRequest
    from app.routes.a2ui.schemas import ConfirmDraftRequest
    plan=UiPlan(summary='병동별 문제 발생 비율',analysis_plan=clinical_data)
    monkeypatch.setattr(baseline,'build_review_plan',lambda *args,**kwargs:plan)
    monkeypatch.setattr(baseline,'agent_cache_context',lambda *args:{})
    monkeypatch.setattr(agent2ui,'agent_cache_context',lambda *args:{})
    left=baseline.baseline_response_payload(ChatRequest(question=clinical_data.original_question),
        thread_id='clinical-baseline',routing_context=[])
    right=agent2ui.confirm_response_payload(ConfirmDraftRequest(question=clinical_data.original_question,
        plan=plan,surface_id='clinical-agent2ui',revision=1))
    left=left['execution_result']['normalized_spec']['analysis_execution']
    right=right['execution_result']['normalized_spec']['analysis_execution']
    assert left['rows']==right['rows'] and left['sql']==right['sql']
    assert left['metadata']['execution_route']==right['metadata']['execution_route']=='registered_metric'
