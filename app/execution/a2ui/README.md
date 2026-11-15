# `app/execution/a2ui` · 확정된 Agent2UI 계획 실행

> **한눈에 보기** · 사용자가 확정한 계획을 마지막으로 검사하고 공통 실행부에 전달합니다.

**기본 흐름:** 확정 요청 → 계획·선택값 검사 → 공통 SQL 실행

사용자가 확정한 계획을 검증하고 이전 분석 참조를 실행 문맥에 연결한 뒤 결과 응답을 구성합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [service.py](service.py) | 사용자가 확인한 A2UI 계획을 검증·실행하고 응답을 조립한다. |

## 핵심 개념과 동작

확정 서비스는 요청 계획을 깊은 복사로 분리한 뒤 누락·질문 일치·카탈로그·참조 문맥을 검증합니다. HTTP revision 검사와 서버 UI 스키마 적용은 routes/a2ui가 담당하며 이 서비스는 검증된 분석 의미를 실행 문맥으로 바꿉니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `confirm_response_payload` | 확정 계획과 선택 이전 결과의 실행 | 계획 실행 경계 |
| `validate_confirmed_plan` | UiPlan과 선택적 최상위 계획의 일치 검사 | 중복 payload 일관성 |

### 핵심 코드: validate_confirmed_plan

서로 다른 두 분석 계획이 한 요청에 섞여 들어오지 않게 합니다.

**동작:** UiPlan을 검증하고 별도 analysis_plan이 있으면 같은 모델로 정규화해 전체 딕셔너리를 비교합니다.

**설계:** 모델 정규화 이후의 값 동등성 검사입니다. UI에서 확정한 조건과 실행용 조건이 달라지는 모순을 방지합니다.

**예:** plan.analysis_plan의 limit=5와 별도 analysis_plan의 limit=10은 ValueError입니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/execution/a2ui/service.py](service.py#L111). 아래는 실제 코드의 111~127행 발췌이며 앞뒤는 생략했습니다.

```python
def validate_confirmed_plan(
    plan: UiPlan,
    *,
    question: str = "",
    explicit_plan: dict | None = None,
) -> dict:
    """UiPlan의 분석 계획을 공통 검증기로 검사하고 JSON 호환 딕셔너리로 반환한다.

    최상위 analysis_plan도 전달됐다면 정규화한 두 계획을 대조하며 다르면 ValueError를 발생시킨다.
    """

    review = validate_ui_plan(plan, question).model_dump(mode="json")
    if explicit_plan is not None:
        explicit = AnalysisPlan.model_validate(explicit_plan).model_dump(mode="json")
        if explicit != review:
            raise ValueError("top-level analysis_plan and plan.analysis_plan disagree")
    return review
```

</details>

### 다른 기능과 연결되는 순서

`routes.a2ui.confirm_review 또는 runtime.a2ui.worker → confirm_response_payload → execute_schema_question`입니다. 결과는 ConfirmDraftResponse로 반환하고 라우터가 기록합니다.

### 확인한 범위와 한계

이 서비스를 직접 호출하면 HTTP 계층의 revision·서버 UI 교체 검사를 자동으로 수행하는 것은 아닙니다. 요청 추적은 모델 한도를 적용하지만 의미 정확성을 평가하는 장치는 아닙니다.

관련 검증: [test_sql_tools.py](../../../tests/execution/test_sql_tools.py), [test_review_update.py](../../../tests/a2ui/test_review_update.py).

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)
