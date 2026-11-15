# `app/execution/baseline` · 프롬프트 모드 즉시 실행

> **한눈에 보기** · 질문에서 내부 분석 계획을 만든 뒤 바로 실행합니다. 사용자에게 계획 검토 화면을 보여주는 단계는 생략합니다.

**기본 흐름:** 질문 → 내부 계획 → 조건 확인 → 공통 실행

프롬프트 질문의 내부 분석 계획을 생성하고 바로 실행해 응답을 구성합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [service.py](service.py) | Baseline 요청의 계획 생성·즉시 실행·응답 조립을 담당한다. |

## 핵심 개념과 동작

Baseline은 계획이 없는 직접 SQL 경로가 아닙니다. 공통 planner를 include_ui=False로 호출해 구조화된 계획을 만든 뒤 사용자 검토 화면만 생략하고 공통 실행기로 전달합니다. 모호한 이전 참조나 미해결 조건은 즉시 실행하지 않고 확인 응답으로 반환합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `baseline_response_payload` | 분석 계획 생성·실행·응답 구성 | 화면 없는 계획 실행 |
| `build_review_plan` | UI 없이 공통 계획 생성 | 공유 planner |
| `ConfirmedAnalysisContext.from_plan` | 실행 계약·기간 문맥 구성 | 공통 실행 모델 |

### 핵심 코드: baseline_response_payload

화면이 없는 경로에서도 불완전한 계획을 실행하지 않도록 합니다.

**동작:** 계획의 필수값·미해결 조건·조회 불가 사유를 확인하고 필요하면 clarification으로 반환합니다.

**설계:** 단계별 실행 게이트입니다. 사용자 검토 생략과 계약 검증 생략을 혼동하지 않도록 합니다.

**예:** 집계 대상 필드가 미해결이면 SQL 실행 대신 확인 메시지를 반환합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/execution/baseline/service.py](service.py#L64). 아래는 실제 코드의 64~73행 발췌이며 앞뒤는 생략했습니다.

```python
if review_plan.missing_fields or analysis_plan.unresolved_constraints or review_plan.infeasible:
    reasons = analysis_plan.unresolved_constraints or [item.reason for item in review_plan.infeasible]
    answer = '조회에 필요한 조건을 확인해 주세요. ' + ('; '.join(reasons) or ', '.join(review_plan.missing_fields))
    return ChatResponse(answer=answer, thread_id=thread_id, input_source='baseline',
        execution_result={'kind':'clarification','input_source':'baseline','answer':answer,
                          'normalized_spec':{'original_question':question}}).model_dump(mode='json')
execution_question = contextual_request(question, thread_id) if routing_context is None else question
if routing_context:
    execution_question += "\n\nSelected previous result (use only to resolve this follow-up):\n" + json.dumps(
        [compact_context_record(record) for record in routing_context], ensure_ascii=False)
```

</details>

### 다른 기능과 연결되는 순서

chat.dispatch가 선택한 이전 결과만 routing_context에 전달할 수 있습니다. baseline_response_payload는 공통 execute_schema_question 뒤 analysis_result_to_surface로 결과를 조립합니다.

### 확인한 범위와 한계

planner·스키마·모델 품질에 의존하며 UI가 없다는 이유로 비용이나 지연이 항상 작다고 단정할 수 없습니다. 실제 모델 비교 성능은 별도 측정이 필요합니다.

관련 검증: [test_baseline_plan.py](../../../tests/a2ui/test_baseline_plan.py), [test_sql_tools.py](../../../tests/execution/test_sql_tools.py).

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)
