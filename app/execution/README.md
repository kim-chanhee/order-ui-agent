# `app/execution` · SQL 생성·검증·실행

> **한눈에 보기** · 분석 계획을 실제 조회 결과로 바꾸는 공통 실행부입니다. Baseline과 Agent2UI가 함께 사용합니다.

**기본 흐름:** 계획 → SQL 생성 → 검사 → 조회 → 결과 검사

분석 계획을 실행 문맥으로 바꾸고 스키마 탐색, SQL 생성, 계약 검증, 읽기 전용 실행과 결과 검사를 수행합니다.

## 역할별 구성

| 폴더 | 역할 |
|---|---|
| [agent/](agent/README.md) | LLM 추론과 Tool 호출 제어 |
| [tools/](tools/README.md) | DB 스키마 탐색과 SQL 도구 |
| [sql/](sql/README.md) | SQL 구문 분석·생성·검증 |
| [semantics/](semantics/README.md) | 업무 의미와 집계 규칙 |
| [results/](results/README.md) | 실행 결과의 검증과 응답 구성 |
| [baseline/](baseline/README.md) | 프롬프트 모드의 계획 생성·즉시 실행 응답 |
| [a2ui/](a2ui/README.md) | 사용자가 확정한 계획의 실행 응답 |

## 공통 실행 진입점

| 파일 | 역할 |
|---|---|
| [confirmed_context.py](confirmed_context.py) | 분석 계획을 SQL 생성기와 검증기가 공유하는 실행 기준으로 정리한다. |
| [confirmed_execution.py](confirmed_execution.py) | 공통 실행을 시작하고 성공·실패 결과를 표준화한다. |

두 파일은 Baseline과 Agent2UI가 공유하므로 execution/ 바로 아래에 둡니다. confirmed는 사용자 확인 화면의 유무를 뜻하지 않습니다.

## SQL Agent 및 Tool Calling 상세

- [Agent의 실행 흐름과 판단](agent/README.md): 주요 함수·클래스, ReAct와 Tool Calling, 복잡도 분류, SQL 후보 선택, 실행 제한·재시도와 결과 통계.
- [Tool의 검증과 실행 상태](tools/README.md): 검사·실행 Tool 생성, SqlToolState 공유, 검사 이력과 실행 직전 재검증, 스키마 탐색, 결과 미리보기·반환 상한.

Agent가 다음 행동을 선택하고 Tool이 검증·실행을 담당합니다. 후보 점수는 정답 판정이 아닌 보조 기준이며, SQL과 결과의 계약 검증을 통과한 조회를 대상으로 적용합니다.

## SQL AST 및 계약 검증 상세

[SQL AST 및 계약 검증](sql/README.md)에서는 AST·CTE·Predicate의 차이, 계획과 SQL의 실행 계약, 그룹·정렬·LIMIT·필터 검증, COUNT(*)와 COUNT(DISTINCT)의 집계 단위, 등록 비율 지표의 분자·분모, 라이브 스키마 참조 검사와 현재 검증 범위를 설명합니다.

## Schema Retrieval 및 DB 구조 탐색 상세

- [스키마 검색과 관계 탐색](tools/README.md#schema-retrieval-질문과-관련된-스키마-우선-검색): 주요 함수, 관련도 점수, n-gram·문자열 유사도, 그래프의 최단 연결 경로, 상세 메타데이터와 fingerprint.
- [JOIN의 의미적 유효성](semantics/README.md#join의-의미적-유효성): 식별자 역할 설정, CTE 투영 추적, 역할 충돌 차단 조건과 검증 한계.

## 핵심 개념과 동작

ConfirmedAnalysisContext는 **실행에 필요한 계획과 조건을 모은 데이터**입니다. SQL을 만드는 쪽과 검사하는 쪽이 같은 조건을 사용합니다.

사전 등록 지표는 정의된 규칙으로 SQL을 만듭니다. 나머지는 LLM을 사용하며, 두 경로 모두 같은 도구로 SQL과 결과를 검사합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `ConfirmedAnalysisContext` | 질문·확정 계획·화면 버전·기간 기준 묶음 | 공통 실행 계약 |
| `TemporalExecutionContext` | 상대 기간과 데이터 기준 날짜 정보 | Temporal anchor |
| `execute_schema_question` | 등록 지표/SQL Agent 선택과 실패 분류 | 실행 오케스트레이션 |
| `ConfirmedExecutionResult` | 응답과 실행 데이터·실패 메타데이터 표준화 | 결과 응답 형식 |

### 핵심 코드: execute_schema_question

두 입력 방식과 두 SQL 생성 경로를 공통 결과 계약에 연결합니다.

**동작:** 등록 지표 실행을 먼저 시도하고 해당하지 않으면 SQL Agent를 호출하며 예외는 실패 분류로 포장합니다.

**설계:** 동일한 실행 문맥을 공유하는 경로 선택입니다. 등록된 모집단 정의가 모델의 임의 SQL로 바뀌지 않도록 별도 경로로 처리합니다.

**예:** semantic_id가 등록 모집단 정의를 가리키면 execution_route=registered_metric이 될 수 있습니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/execution/confirmed_execution.py](confirmed_execution.py#L97). 아래는 실제 코드의 97~110행 발췌이며 앞뒤는 생략했습니다.

```python
try:
    from app.execution.semantics.registered_metrics import try_registered_metric
    result = try_registered_metric(confirmed_context)
    if result is None:
        result = try_fast_sql_answer(
            question,
            confirmed_context=confirmed_context,
            cached_context=cached_context,
        )
    if result is None:
        raise RuntimeError("SQL agent produced no result")
except Exception as exc:
    error = sanitize_fallback_error(str(exc))
    failure = classify_failure_message(error)
```

</details>

### 다른 기능과 연결되는 순서

`baseline/service 또는 a2ui/service → ConfirmedAnalysisContext → execute_schema_question → registered_metrics 또는 agent → tools → sql/semantics → results` 순서입니다. 기간 미리보기는 계획 확정 전 UI에도 제공되며 실제 SQL에서 데이터 기준 anchor를 다시 검사합니다.

### 확인한 범위와 한계

confirmed는 공통 실행 문맥의 이름이며 Baseline 사용자가 화면을 확정했다는 뜻이 아닙니다. 생성 실패·계약 실패·모델 장애는 서로 구분하지만 자동 실행 성공이 의미적 정답을 보장하지는 않습니다.

관련 검증: [test_sql_tools.py](../../tests/execution/test_sql_tools.py), [test_registered_metrics.py](../../tests/execution/test_registered_metrics.py).

## 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)
