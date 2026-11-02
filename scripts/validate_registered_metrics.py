"""Compare the shared registered execution path to independent reference SQL.

No model is called and these results must not be reported as end-to-end LLM
accuracy. The reference queries are evaluation-only inputs, never runtime data.
"""
import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
from app.core.data_profile import apply_data_profile
apply_data_profile()

from app.execution.confirmed_context import ConfirmedAnalysisContext
from app.execution.confirmed_execution import execute_schema_question
from app.execution.sql_safety import create_read_only_connection
from app.data.database import DEFAULT_DB_PATH
from app.planning.analysis_models import AnalysisPlan, MetricSpec


def validate(reference_path, output):
    references={item['id']:item for item in json.loads(Path(reference_path).read_text())['items']}
    reference=references['recent90_customer_failure_breakdown']['expected_sql']
    outcomes=[]
    for days in (7,14,30,60,90):
        with create_read_only_connection(DEFAULT_DB_PATH) as conn:
            expected=[tuple(row) for row in conn.execute(reference.replace('-89 days',f'-{days-1} days'))]
        for kind,identifier in [('ratio','created_order_failure_rate'),('count','failed_created_order_count')]:
            plan=AnalysisPlan(original_question=f'{days}일 생성 주문 기준 고객별 지표 검증',
                date_range={'mode':'relative','relative_days':days},group_by=['customer_id'],
                metric=MetricSpec(kind=kind,field='order_id',unit='주문' if kind=='count' else None,
                                  semantic_id=identifier))
            context=ConfirmedAnalysisContext.from_plan(plan,original_question=plan.original_question,
                surface_id='offline-reference-validation',revision=1)
            result=execute_schema_question(plan.original_question,confirmed_context=context)
            data=result.analysis_payload or {}
            actual=[(r['customer_id'],r['population_count'],r['subset_count'])+
                    ((r['rate'],) if kind=='ratio' else ()) for r in data.get('rows',[])]
            wanted=expected if kind=='ratio' else [row[:3] for row in expected]
            passed=bool(data.get('sql')) and sorted(actual)==sorted(wanted)
            outcomes.append({'days':days,'metric':identifier,'passed':passed,'expected_rows':len(wanted),
                'actual_rows':len(actual),'sql':data.get('sql'),'error':result.fallback_error,
                'execution_route':data.get('metadata',{}).get('execution_route'),
                'model_calls':data.get('metadata',{}).get('llm_model_calls')})
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps({'test_type':'local_registered_pipeline_not_live_llm',
        'outcomes':outcomes},ensure_ascii=False,indent=2))
    print(f'{sum(r["passed"] for r in outcomes)}/{len(outcomes)} passed; no LLM calls')
    return all(r['passed'] for r in outcomes)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',default='Data/eval/ground_truth.json')
    parser.add_argument('--output',default='artifacts/validation/registered-metrics.json')
    args=parser.parse_args()
    raise SystemExit(0 if validate(args.reference,args.output) else 1)
