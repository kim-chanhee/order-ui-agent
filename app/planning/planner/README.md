# `app/planning/planner` · 공통 LLM 계획 생성기

## 1. 이 폴더의 역할

> **한눈에 보기** · LLM에게 질문을 분석 계획 형식으로 정리하도록 요청합니다. 응답을 받은 뒤 형식과 선택값을 다시 검사합니다.

**기본 흐름:** 질문·스키마 → 모델 응답 → 정리·검사 → 계획

## 2. 해결하려는 문제

자유 형식의 모델 응답은 필드가 빠지거나 존재하지 않는 선택값을 포함할 수 있습니다. 정해진 형식으로 응답을 받고 실제 스키마와 대조합니다.

## 3. 핵심 기술

Structured Output은 **모델의 답을 정해진 형식으로 받는 방식**입니다. 이 프로젝트는 모델 공급자에 맞춰 JSON Schema 또는 함수 호출 형식을 사용합니다. 받은 초안은 다시 정리하고 검사합니다.

Baseline은 `include_ui=False`로 계획만 만듭니다. Agent2UI는 계획과 함께 사용자가 편집할 화면 항목도 준비합니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `plan_dynamic_analysis` | 모델 호출과 정규화·의미 검증 순서 제어 | Structured Output |
| `_canonicalize_planner_output` | 알려진 전송 별칭·불완전한 envelope 복구 | 정규화 |
| `_inherit_followup_scope` | 선택된 이전 계획의 생략 조건만 상속 | 출처 추적 |
| `_ensure_plan_controls` | 스키마 선택지와 중복 블록 검증 | 스키마에 근거한 화면 구성 |
| `safe_clarification_plan` | 실패를 실행 가능한 SQL 대신 조건 확인 계획으로 전환 | 실패 경계 |

### 핵심 코드: plan_dynamic_analysis

스키마와 이전 분석 문맥을 구조화 응답 모델에 연결합니다.

**동작:** 실행 설정을 확인한 후 include_ui에 따라 초안 모델을 고르고 프롬프트와 재시도 한도를 준비합니다.

**설계:** Pydantic 응답 스키마와 공급자별 structured_output_options를 사용합니다. 두 모드의 분석 의미는 공유하고 편집 UI 요구만 분리합니다.

**예:** include_ui=False는 AnalysisDraft, True는 PlannerDraft를 요청합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/planning/planner/dynamic_planner.py](dynamic_planner.py#L75). 아래는 실제 코드의 75~88행 발췌이며 앞뒤는 생략했습니다.

```python
question = question.strip()
context = schema_context or build_planner_schema_context(question)
candidates = _normalize_context_candidates(previous_plan, context_candidates)
if not planner_enabled() and llm is None:
    return _ensure_plan_controls(
        safe_clarification_plan(question, reason="LLM planner is not configured"),
        context,
    )
model = llm or _planner_llm()
structured = model.with_structured_output(PlannerDraft if include_ui else AnalysisDraft, **structured_output_options())
prompt = _planner_prompt(question, context, context_candidates=candidates, include_ui=include_ui)
last_error: Exception | None = None
attempt_prompt = prompt
max_attempts = max(1, int(os.environ.get("AGENT2UI_PLANNER_MAX_ATTEMPTS", "2")))
```

</details>

### 핵심 코드: _ensure_plan_controls

LLM의 화면 구성 제안과 실제 허용 선택값을 분리합니다.

**동작:** 계획으로 카탈로그를 생성·검증하고 Baseline이면 블록을 비운 뒤 필요한 집계 필드만 누락으로 기록합니다.

**설계:** 서버 발급 카탈로그에 기반한 UI 검증입니다. 임의의 고정 UI를 삽입하거나 허용되지 않은 선택값을 승인하지 않도록 합니다.

**예:** count 지표에 field가 없고 include_ui=False이면 missing_fields에 metric.field를 추가합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/planning/planner/controls.py](controls.py#L69). 아래는 실제 코드의 69~86행 발췌이며 앞뒤는 생략했습니다.

```python
from app.planning.a2ui.validator import normalize_metric_dependencies, validate_dynamic_semantics, validate_choice_values
plan = output.analysis_plan
catalog = build_plan_option_catalog(schema_context.text, plan)
plan = normalize_metric_dependencies(plan, plan, catalog_snapshot(catalog))
output.analysis_plan = plan
catalog = build_plan_option_catalog(schema_context.text, plan)
snapshot = catalog_snapshot(catalog)
validate_dynamic_semantics(plan, snapshot, allow_incomplete=True)
if not include_ui:
    output.ui_blocks = []
    output.ui_state = {'semantic_catalog': snapshot}
    output.missing_fields = compute_missing_fields(plan, [])
    if plan.metric and plan.metric.kind in {'count','sum','avg','min','max'} and not plan.metric.field:
        output.missing_fields.append('metric.field')
    return output
if not output.ui_blocks:
    raise ValueError('분석 목적에 필요한 UI Block을 하나 이상 제안해 주세요.')
paths, keys = set(), set()
```

</details>

### 다른 기능과 연결되는 순서

`prompt → 모델 호출 → response 정규화 → semantics 보정 → context 상속 → controls 선택지 검사 → 기간 미리보기 → 의미 검증` 순서입니다. 구조 오류(ValueError/TypeError)는 피드백을 붙여 기본 2회 시도하고, 공급자 장애는 공통 일시 오류 재시도 후 조건 확인 계획으로 돌아갑니다. 현재 질문에서 명시·덮어쓰기한 필드는 상속하지 않습니다.

## 5. 구현 결과와 한계

**현재 구현:** 모델 응답 초안을 계획 모델로 정리하고 모드에 따라 검토 UI를 구성합니다.

응답 복구는 알려진 필드·별칭 처리이며 누락된 업무 의미를 정답으로 추측하는 기능이 아닙니다. confidence는 모델 응답 값이고 정확도 측정치가 아닙니다. 모델 API 장애와 구조 오류의 복구 가능성을 구분합니다.

관련 검증: [test_baseline_plan.py](../../../tests/a2ui/test_baseline_plan.py), [test_prompt_compaction.py](../../../tests/a2ui/test_prompt_compaction.py), [test_dynamic_blueprint.py](../../../tests/a2ui/test_dynamic_blueprint.py), [test_gpt_structured_transport.py](../../../tests/test_gpt_structured_transport.py).

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

질문을 구조화된 분석 계획으로 바꾸는 공통 모델 호출·응답 복구·문맥 상속·의미 검증을 담당합니다. Baseline은 `AnalysisDraft`와 `include_ui=False`로 화면 없이 계획을 만들고, A2UI는 `PlannerDraft`로 동적 UI와 추천 조건을 추가합니다. UI 검증 실패가 Baseline의 실행 조건이 되지 않습니다.

### 주요 파일

| 파일 | 역할 |
|---|---|
| [context.py](context.py) | 후속 분석의 참조 후보 선택·조건 상속·식별자 필터 근거를 처리한다. |
| [controls.py](controls.py) | 검토용 UI의 선택지·기본 입력·중복·배치와 스키마 근거를 정리한다. |
| [dynamic_planner.py](dynamic_planner.py) | Baseline과 A2UI가 공유하는 LLM 분석 계획 생성 진입점. |
| [models.py](models.py) | 계획 생성 응답과 후속 분석 맥락을 표현하는 모델. |
| [prompt.py](prompt.py) | 질문·스키마·이전 분석 후보를 계획 및 UI 생성 프롬프트로 구성한다. |
| [response.py](response.py) | LLM 응답의 구조·타입·필드·UI 원시 값을 복구하고 모델로 검증한다. |
| [semantics.py](semantics.py) | 분석 지표·관계 범위를 정리하고 분석 의미와 날짜 안내의 일관성을 검증한다. |

### 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)

</details>
