"""Compression must retain domain facts and scope, while dropping duplicate dumps."""
import json
from app.planning.planner.prompt import _planner_catalog, _planner_prompt, _semantic_notes
from app.planning.schema_context import PlannerSchemaContext
from app.planning.option_catalog import build_plan_option_catalog, catalog_snapshot
from app.planning.analysis_models import AnalysisPlan
from app.planning.planner.models import PlannerContextCandidate

SCHEMA = 'books(book_id TEXT, title TEXT, price REAL)\nloans(loan_id TEXT, book_id TEXT, created_at TIMESTAMP)'
CONTEXT = PlannerSchemaContext(('books','loans'), SCHEMA, 'library')


def test_catalog_keeps_all_supported_values_and_types():
    expected = catalog_snapshot(build_plan_option_catalog(SCHEMA, AnalysisPlan(original_question='도서별 대출 건수')))
    compact = _planner_catalog(CONTEXT, '도서별 대출 건수')
    assert compact['schema'] == expected['schema']
    assert compact['semantic_metrics'] == expected['semantic_metrics']
    for key in ('event_types','group_by','count_fields','metric_kinds','numeric_fields'):
        assert [(o['value'],o['label']) for o in compact[key]] == [(o['value'],o['label']) for o in expected[key]]


def test_repeated_semantic_notes_are_kept_once_without_sample_rows():
    text = '\n'.join(['## books','- Business meaning: Library inventory.','- Row grain: One edition.',
                      'TABLE: books','- sample 1: title=Unrelated sample',
                      '## books','- Business meaning: Library inventory.','## loans',
                      '- Population time: Use loan creation, not return time.'])
    compact = _semantic_notes(text)
    assert compact.count('Library inventory.') == 1
    assert 'One edition.' in compact
    assert 'Use loan creation, not return time.' in compact
    assert 'Unrelated sample' not in compact


def test_prior_scope_keeps_filter_ids_rows_and_identity_values():
    candidate = PlannerContextCandidate(context_id='scope-7',question='최근 30일 도서 대출',
        analysis_plan=AnalysisPlan(original_question='최근 30일 도서 대출',
                                   date_range={'mode':'relative','relative_days':30},
                                   target_entity='book',requested_attributes=['display_name'],
                                   group_by=['book_id'],limit=5),
        answer='A repeated prose answer',columns=['book_id','title'],
        rows=[{'book_id':'book-17','title':'자료구조'}],identity_values={'book_id':['book-17']})
    prompt = _planner_prompt('그 도서들의 제목을 알려줘', CONTEXT, context_candidates=[candidate])
    previous = json.loads(prompt.split('Prior successful analysis candidates:\n',1)[1].split('\nQuestion:',1)[0])
    actual = previous[0]
    assert actual['context_id'] == 'scope-7'
    assert actual['analysis_plan']['date_range']['relative_days'] == 30
    assert actual['analysis_plan']['group_by'] == ['book_id']
    assert actual['analysis_plan']['limit'] == 5
    assert actual['rows'] == candidate.rows
    assert actual['identity_values'] == candidate.identity_values
    assert 'A repeated prose answer' not in prompt
