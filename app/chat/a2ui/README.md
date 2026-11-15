# `app/chat/a2ui` · Agent2UI 계획 검토 응답

> **한눈에 보기** · 분석 요청을 받으면 실행 전 검토할 계획 화면을 준비합니다. 이전 결과를 수정하는 요청이면 해당 결과의 문맥도 전달합니다.

**기본 흐름:** 분석 요청 → 계획 생성 → 검토 화면 응답

Agent2UI 질문에 대한 검토 계획과 안내 응답을 구성합니다. 이전 결과 참조가 불명확하면 확인 질문을 반환합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [review.py](review.py) | A2UI 전용 계획 검토 응답과 참조 불명확 시 확인 질문을 만든다. |

## 핵심 개념과 동작

이 계층은 분류가 끝난 분석 요청을 계획 검토 응답으로 바꿉니다. 새 분석과 이전 결과 수정의 문맥 범위를 전달하고, 선택한 참조를 실제 계획이 동일하게 반영했는지 확인한 뒤 서버 화면을 만듭니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `review_response` | 계획 생성·참조 확인·검토 화면 응답 | 계획 검토 경계 |

### 핵심 코드: review_response

실행할 계획을 만들기 전 이전 결과의 범위를 제한합니다.

**동작:** 요청 종류에 따라 context_records를 선택하고 공통 계획 생성기를 호출합니다.

**설계:** 모드별 어댑터와 공통 planner 조합입니다. 이전 결과의 조건이 무관한 새 질문으로 누출되지 않도록 합니다.

**예:** 새 분석은 빈 후보 목록, refine_analysis는 선택한 이전 기록을 계획 생성기로 전달합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/chat/a2ui/review.py](review.py#L23). 아래는 실제 코드의 23~37행 발췌이며 앞뒤는 생략했습니다.

```python
question = payload.question.strip()
context = selected if decision.request_kind == "refine_analysis" else []
plan = build_review_plan(planning_question or question, thread_id, context_records=context)
# 확인 API와 화면은 사용자가 실제 입력한 질문을 기준으로 계획을 대조한다.
plan.analysis_plan.original_question = question
if plan.analysis_plan.source == 'safe_fallback':
    plan_payload, surface = plan_response_parts(plan, payload, thread_id)
    result = planning_failure_result(question, plan, 'agent2ui')
    return ChatResponse(
        answer=result['answer'], thread_id=thread_id, input_source='agent2ui', plan=plan_payload,
        a2ui_surface=surface,
        execution_result=result,
    ).model_dump(mode='json')
conversation = recent_dialogue(thread_id, payload.input_source)
reference = plan.analysis_plan.context_reference
```

</details>

### 다른 기능과 연결되는 순서

`chat.dispatch → review_response → planning.build_review_plan → planning.a2ui.review.plan_response_parts`로 연결됩니다. 반환값은 ChatResponse 딕셔너리와 plan Surface이며 실제 DB 실행은 confirm API 이후입니다.

### 확인한 범위와 한계

계획 생성 실패와 참조 불명확성은 실행으로 넘어가지 않습니다. 라우팅 테스트는 대체 모델 중심이며 전체 검토 화면의 실제 브라우저 동작을 모두 검증하지 않습니다.

관련 검증: [test_turn_router.py](../../../tests/test_turn_router.py).

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)
