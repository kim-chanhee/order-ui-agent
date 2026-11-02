"""Replay short task turns through the running app, retaining plans and actual SQL."""
import concurrent.futures
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

from app.execution.sql_safety import create_read_only_connection

OUT = Path(os.environ.get('TASK_TEST_OUTPUT_DIR', 'artifacts/task-tests'))
BASE_URL = os.environ.get('TASK_TEST_BASE_URL', 'http://127.0.0.1:8001')
TRUTH = {i['id']: i for i in json.loads(Path('Data/eval/ground_truth.json').read_text())['items']}
STEPS = {
    'task1': [
        ('count60', '최근 60일 배송 실패 주문은 몇 건이야?', 'recent60_failed_order_count', [0]),
        ('names60', '같은 60일의 배송 실패 이벤트에 직접 연결된 물품명을 알려줘.', 'recent60_failed_product_names', [0]),
    ],
    'task2': [
        ('orders90', '최근 90일에 생성된 주문 수를 고객별로 알려줘.', 'recent90_orders_per_customer', [0, 1]),
        ('failed90', '최근 90일 생성 주문 중 고객별 배송 실패 주문 수를 알려줘.', 'recent90_customer_failure_breakdown', [0, 2]),
        ('rates90', '같은 주문 기준으로 고객별 배송 실패율을 알려줘.', 'recent90_customer_failure_breakdown', [0, 3]),
        ('top90', '그 실패율이 가장 높은 고객은 누구야?', 'recent90_top1_failure_customer', [0]),
        ('undelivered90', '그 고객의 최근 90일 주문 중 실패 후에도 배송 완료되지 않은 물품명을 알려줘.', None, None),
    ],
}


def post(path, data):
    req = urllib.request.Request(BASE_URL + path,
        data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=240) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}: {exc.read().decode()[:2000]}') from exc


def expected(truth_id, indices):
    with create_read_only_connection('Data/order-management.sqlite') as conn:
        rows = conn.execute(TRUTH[truth_id]['expected_sql']).fetchall()
    return [[row[i] for i in indices] for row in rows]


def equal(a, b):
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-4, abs_tol=1e-4)
    except (ValueError, TypeError):
        return str(a).strip().casefold() == str(b).strip().casefold()


def contains_row(actual, wanted):
    remaining = list(actual)
    for value in wanted:
        index = next((i for i, candidate in enumerate(remaining) if equal(value, candidate)), None)
        if index is None:
            return False
        remaining.pop(index)
    return True


def compare(actual_rows, wanted):
    if len(actual_rows) != len(wanted):
        return False
    remaining = [list(row.values()) for row in actual_rows]
    for row in wanted:
        index = next((i for i, candidate in enumerate(remaining) if contains_row(candidate, row)), None)
        if index is None:
            return False
        remaining.pop(index)
    return True


def run_mode(mode):
    outcomes = []
    provider_blocked = False
    for task, steps in STEPS.items():
        thread = str(uuid.uuid4())
        for step, question, truth_id, indices in steps:
            item = {'mode': mode, 'task': task, 'step': step, 'question': question, 'thread_id': thread}
            start = time.perf_counter()
            print(json.dumps({'started': mode, 'step': step, 'question': question}, ensure_ascii=False), flush=True)
            try:
                if provider_blocked:
                    raise RuntimeError('Not run: provider credit is exhausted; restore the connection before replaying.')
                response = post('/api/chat', {'question': question, 'thread_id': thread,
                    'input_source': mode, 'app_mode': 'admin', 'task_id': task})
                item['chat_response'] = response
                plan = response.get('plan')
                if mode == 'agent2ui' and plan:
                    item['plan_source'] = plan['analysis_plan'].get('source')
                    if plan['analysis_plan'].get('source') != 'safe_fallback' and not plan.get('infeasible') and not plan.get('missing_fields'):
                        response = post('/api/review/confirm', {'question': plan['analysis_plan']['original_question'],
                            'thread_id': thread, 'input_source': mode, 'app_mode': 'admin', 'task_id': task,
                            'plan': {k: v for k, v in plan.items() if k not in {'surface_id', 'plan_id', 'revision'}},
                            'surface_id': plan['surface_id'], 'plan_id': plan['plan_id'],
                            'revision': plan['revision']})
                        item['confirm_response'] = response
                result = response.get('execution_result') or {}
                normalized = result.get('normalized_spec') or {}
                analysis = normalized.get('analysis_execution') or {}
                item.update(answer=response.get('answer') or response.get('message'),
                    kind=result.get('kind'), analysis=analysis)
                provider_blocked = normalized.get('failure_category') == 'provider_quota_exhausted'
                if truth_id:
                    item['expected_rows'] = expected(truth_id, indices)
                    item['passed'] = bool(analysis.get('sql')) and compare(analysis.get('rows') or [], item['expected_rows'])
                else:
                    item['passed'] = False if not analysis.get('sql') else None
                    item['blocked_by_previous_step'] = not any(
                        outcome['task'] == task and outcome['step'] == 'top90' and outcome.get('passed')
                        for outcome in outcomes)
                    item['review_required'] = 'An empty result only passes after verifying the selected customer and failed-minus-delivered scope in SQL.'
                if not analysis.get('sql'):
                    item['failure'] = 'No SQL result returned'
            except Exception as exc:
                item.update(passed=False, failure=str(exc))
            item['seconds'] = round(time.perf_counter() - start, 2)
            outcomes.append(item)
            (OUT / f'{mode}.json').write_text(json.dumps(outcomes, ensure_ascii=False, indent=2))
            print(json.dumps({'finished': mode, 'step': step, 'passed': item.get('passed'),
                'rows': len(item.get('analysis', {}).get('rows', [])), 'failure': item.get('failure'),
                'seconds': item['seconds']}, ensure_ascii=False), flush=True)
    return outcomes


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True, parents=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(os.environ.get('TASK_TEST_WORKERS','1'))) as pool:
        outcomes = list(pool.map(run_mode, ['baseline', 'agent2ui']))
    (OUT / 'all-results.json').write_text(json.dumps(outcomes, ensure_ascii=False, indent=2))
