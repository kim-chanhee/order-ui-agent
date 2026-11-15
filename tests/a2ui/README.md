# 분석 계획과 검토 UI 검증

## 1. 이 폴더의 역할

> **한눈에 보기** · 계획 생성과 수정 과정에서 분석 조건이 유지되는지 확인합니다. 화면이 없는 실행 방식도 함께 검사합니다.

**기본 흐름:** 계획·수정 입력 → 검증 실행 → 조건·오류 확인

## 2. 해결하려는 문제

계획 편집이나 프롬프트 변경 중에 유효한 선택지와 분석 조건이 누락될 수 있습니다. 계획 생성·수정의 주요 조건을 자동으로 비교합니다.

## 3. 핵심 기술

계획 테스트는 스키마에 근거한 값과 동적 UI 제안을 분리하고, 화면 없는 Baseline·UI 편집·자연어 패치가 같은 분석 계약을 보존하는지 확인합니다. 프롬프트 압축은 선택값과 식별자 근거가 손실되지 않는지를 기준으로 봅니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `test_catalog_keeps_all_supported_values_and_types` | 압축 뒤 카탈로그 값과 타입 유지 | 프롬프트 회귀 검증 |
| `test_prior_scope_keeps_filter_ids_rows_and_identity_values` | 이전 범위의 필터·행·ID 근거 보존 | 문맥 압축 |

### 핵심 코드: test_catalog_keeps_all_supported_values_and_types

프롬프트 길이를 줄이면서 선택 가능한 값이 사라지는 것을 방지합니다.

**동작:** 실제 스키마로 catalog를 만들고 프롬프트용 표현의 값·타입을 assert합니다.

**설계:** 실행 가능한 데이터 계약 검증입니다. 토큰 수 감소 자체보다 의미 근거 보존을 우선하는 테스트입니다.

**예:** ID·숫자·기간 타입과 semantic metric 목록이 압축 뒤에도 남아야 합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [tests/a2ui/test_prompt_compaction.py](test_prompt_compaction.py#L13). 아래는 실제 코드의 13~19행 발췌이며 앞뒤는 생략했습니다.

```python
def test_catalog_keeps_all_supported_values_and_types():
    expected = catalog_snapshot(build_plan_option_catalog(SCHEMA, AnalysisPlan(original_question='도서별 대출 건수')))
    compact = _planner_catalog(CONTEXT, '도서별 대출 건수')
    assert compact['schema'] == expected['schema']
    assert compact['semantic_metrics'] == expected['semantic_metrics']
    for key in ('event_types','group_by','count_fields','metric_kinds','numeric_fields'):
        assert [(o['value'],o['label']) for o in compact[key]] == [(o['value'],o['label']) for o in expected[key]]
```

</details>

### 다른 기능과 연결되는 순서

baseline_plan은 include_ui=False 경로, dynamic_blueprint는 블록·선택지·의미 검사, refinement는 패치, review_update는 서버 저장값·revision 충돌을 확인합니다.

## 5. 구현 결과와 한계

**현재 구현:** 실제 스키마에 근거한 선택값과 모드별 계획·수정 조건을 테스트 사례로 확인합니다.

구조화 대체 응답을 사용하는 테스트이며 실모델 출력의 표현 다양성 전체·사용자 만족도·브라우저 DOM을 검증하지 않습니다.

관련 검증: [test_baseline_plan.py](test_baseline_plan.py), [test_dynamic_blueprint.py](test_dynamic_blueprint.py), [test_refinement.py](test_refinement.py), [test_review_update.py](test_review_update.py).
