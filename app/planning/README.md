# `app/planning` · 분석 계획과 편집 UI 정의

## 1. 이 폴더의 역할

> **한눈에 보기** · 자연어 질문을 기간·필터·지표 같은 분석 조건으로 정리합니다. 이 계획이 화면 편집과 SQL 실행의 공통 기준이 됩니다.

**기본 흐름:** 질문 → 분석 계획 → 값·필수 조건 검사

## 2. 해결하려는 문제

질문을 바로 SQL로 바꾸면 AI가 어떤 조건으로 이해했는지 사람이 확인하기 어렵습니다. 기간·지표·필터를 계획 데이터로 먼저 표현합니다.

## 3. 핵심 기술

AnalysisPlan은 **분석 조건을 담은 데이터**입니다. 기간·필터·지표·집계 기준을 여기에 저장합니다. UiBlock은 사용자가 어떤 항목을 편집할지 정하는 화면 설명입니다.

Pydantic은 값의 형식과 범위를 검사하는 라이브러리입니다. 서버는 여기에 스키마에서 확인한 선택지 목록을 더해 실제로 허용되는 값인지 검사합니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `AnalysisPlan` | 실행할 분석 조건과 출처·미해결 조건 표현 | Pydantic |
| `UiBlock` | 등록 컴포넌트와 편집할 계획 경로 연결 | 선언형 UI |
| `build_review_plan` | 이전 결과 후보와 질문을 계획 생성기에 전달 | 문맥 기반 계획 |
| `compute_missing_fields` | 보이는 필수 입력의 누락 경로 계산 | 재귀 조건 평가 |
| `build_plan_option_catalog` | 확인한 스키마로 선택지 구성 | 실제 스키마에 근거한 값 선택 |

### 핵심 코드: compute_missing_fields

모델이 표시한 필수값 중 사용자가 실제로 채울 수 있는 누락 항목을 찾습니다.

**동작:** 표시 조건을 먼저 평가하고 입력 경로가 없는 안내 블록을 제외한 뒤 빈 값을 모읍니다.

**설계:** 조건 트리와 점·배열 경로 접근을 사용합니다. 표시 전용 안내를 필수 입력으로 처리해 영원히 확정하지 못하는 문제를 피합니다.

**예:** 필수 metric.field가 비었으면 ["metric.field"]; 숨겨진 블록이면 포함하지 않습니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/planning/validator.py](validator.py#L84). 아래는 실제 코드의 84~99행 발췌이며 앞뒤는 생략했습니다.

```python
missing: list[str] = []
data = plan.model_dump(mode="json")
for block in ui_blocks:
    if block.visible_if is not None and not condition_matches(block.visible_if, plan):
        continue
    # review·notice는 정보 표시용이며 분석 계획의 입력 필드와 연결되지 않는다.
    # LLM이 required를 지정했더라도 연결되지 않은 안내 블록을
    # 사용자가 채울 수 없는 필수 입력으로 처리하지 않는다.
    if block.field_path is None and block.type in {"review", "notice"}:
        continue
    if not block_is_required(block, plan):
        continue
    path = block.field_path or block.key
    if value_at_path(data, path) in (None, "", [], {}):
        missing.append(path)
return list(dict.fromkeys(missing))
```

</details>

### 다른 기능과 연결되는 순서

`build_review_plan → build_schema_review_plan → planner.plan_dynamic_analysis`가 UiPlan을 구성합니다. `schema_context`는 실제 스키마를 압축하고 `option_catalog`는 검증 가능한 값 목록을 제공합니다. 계획의 `field_metadata`는 명시·추정·상속·사용자 수정의 출처를 구분합니다.

## 5. 구현 결과와 한계

**현재 구현:** 화면에 표시되고 실제 입력 가능한 필수 항목을 기준으로 누락값을 계산합니다.

구조적 유효성이 업무 해석의 정답을 뜻하지 않습니다. 후속 조건 상속과 비율 정의는 추가 검증을 통과해야 하며, 필수값이나 미해결 조건이 남으면 확정 실행을 차단합니다.

관련 검증: [test_dynamic_blueprint.py](../../tests/a2ui/test_dynamic_blueprint.py), [test_baseline_plan.py](../../tests/a2ui/test_baseline_plan.py), [test_data_profile.py](../../tests/test_data_profile.py).

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

질문·DB 스키마·이전 분석을 기간·대상·지표·필터·집계 기준으로 구조화하고 검토용 UI 정의를 만듭니다.

[분석 계획이 UI로 연결되는 예시](../../docs/system-guide.md#분석-계획에서-확인-ui로)

### 주요 파일

| 파일 | 역할 |
|---|---|
| [analysis_models.py](analysis_models.py) | SQL과 분리된 의미 기반 분석 계획을 Pydantic 모델로 정의한다. |
| [option_catalog.py](option_catalog.py) | 스키마와 현재 분석 계획에 근거한 확인 화면 선택지를 만든다. |
| [schema_context.py](schema_context.py) | 실제 데이터베이스에서 질문과 관련된 계획 수립용 스키마 맥락을 수집한다. |
| [service.py](service.py) | Baseline과 A2UI가 공유하는 분석 계획 생성 서비스. |
| [ui_models.py](ui_models.py) | 두 모드가 공유하는 선언형 UI와 분석 계획 응답 모델. |
| [validator.py](validator.py) | 두 모드가 공유하는 UI 조건 평가와 필수 입력 필드 계산. |

### 하위 폴더 안내

| 폴더 | 역할 |
|---|---|
| [a2ui/](a2ui/README.md) | 계획 검토·추가 조건·편집 검증 |
| [planner/](planner/README.md) | 공통 LLM 계획 생성기 |

### 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)

</details>
