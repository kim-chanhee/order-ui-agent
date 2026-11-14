# `app/execution/sql` · SQL AST 및 계약 검증

사용자가 확정한 분석 조건과 LLM이 만든 SQL이 일치하는지 구조적으로 검사하는 계층입니다. SQL이 실행된다는 사실만으로 요청한 집계 단위·필터·기간이 맞다고 볼 수 없으므로, 구문 분석과 계획 계약·스키마·지표 검증을 분리합니다. Baseline도 내부 분석 계획을 만들어 같은 검증 경로를 사용합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [sql_ast.py](sql_ast.py) | SQLite SQL 파싱, 공통 계약 예외, 스코프 기반 물리 테이블·조건 값 추출. |
| [sql_contract.py](sql_contract.py) | 계약 검사 조율과 그룹·정렬·개수 제한·명시적 필터·업무 조건 검사. |
| [sql_metric_contract.py](sql_metric_contract.py) | 집계 함수·필드·중복 제거·집계 단위와 등록된 의미 지표 검사. |
| [sql_schema_contract.py](sql_schema_contract.py) | 확인된 라이브 스키마 설명과 SQL의 테이블·컬럼 참조 대조. |
| [sql_safety.py](sql_safety.py) | 읽기 전용 SQL 경계와 DB 연결에서 데이터 변경 차단. |
| [sql_builder.py](sql_builder.py) | 검증된 SQL의 DB 실행, 실행 계획 확인과 기본 표 형식 제공. |

## 핵심 개념과 관련 함수

| 핵심 기술 | 관련 함수 | 문서에서 확인할 내용 |
|---|---|---|
| AST | `parse_sql_ast()` | SQL을 문자열이 아닌 문법 구조로 분석하는 이유. |
| CTE와 스코프 | `extract_physical_tables()`, `physical_tables_from_tree()` | 실제 테이블과 이름이 붙은 임시 조회 참조의 구분. |
| Predicate | `extract_filter_literals()` | 조건식 안의 문자열 상수 추출과 근거 검사 연결. |
| SQL Contract | `validate_sql_contract()` | 분석 계획과 SQL의 일치 여부를 검사하는 전체 흐름. |
| Grouping | `_validate_grouping()` | 그룹 기준과 날짜 버킷 검사. |
| Sort & Limit | `_validate_sort_and_limit()` | 최종 정렬 방향·필드와 결과 개수 검사. |
| Filter Validation | `_validate_explicit_filters()` | 지원하는 명시적 필터의 필드·연산자·값 검사. |
| Metric Validation | `validate_metrics()` | 출력 집계 함수·개수·필드·DISTINCT와 건수 단위 검사. |
| Semantic Metrics | `validate_semantic_metrics()` | 등록된 업무 지표의 분자·분모와 모집단 의미 검사. |
| Schema Validation | `validate_schema_references()` | 실제 스키마 설명에 근거한 테이블·컬럼 참조 검사. |

## AST: SQL을 구조로 분석하는 이유

AST(Abstract Syntax Tree, 추상 구문 트리)는 SQL의 조회·집계·조건·테이블 참조를 노드로 표현합니다. 문자열에서 `COUNT`나 테이블 이름이 보이는지만 검사하면 주석, 출력용 상수, CTE, 다른 하위 질의에 있는 표현을 실제 분석 조건으로 오해할 수 있습니다.

`parse_sql_ast()`는 SQLGlot의 SQLite 방언으로 파싱하고, 비어 있지 않은 문장이 정확히 하나이며 조회형 `exp.Query`인지 확인합니다. 문법 오류, 여러 문장, 조회형이 아닌 입력은 `SqlContractViolation`으로 보고합니다. AST 파싱만으로 읽기 전용 실행이 완성되는 것은 아니며, 실제 실행에는 별도의 SQL 안전성 검사와 읽기 전용 연결을 사용합니다.

예를 들어 `SELECT 'paid' AS label FROM orders`의 `'paid'`는 표시용 상수이고, `WHERE status = 'paid'`의 `'paid'`는 조건식에 참여하는 값입니다. AST는 이 위치 차이를 구분할 근거를 제공합니다.

## CTE: 실제 테이블과 임시 참조

CTE(Common Table Expression)는 `WITH` 절로 이름을 붙여 같은 SQL 안에서 참조하는 조회입니다. 별도의 영구 테이블이 아니며, CTE 이름이 물리 테이블 이름과 같을 수도 있습니다.

```sql
WITH failed_orders AS (
    SELECT DISTINCT order_id
    FROM order_events
    WHERE event_type = 'failed_delivery'
)
SELECT COUNT(DISTINCT order_id)
FROM failed_orders;
```

이 예시의 실제 테이블은 `order_events`이고 `failed_orders`는 CTE 참조입니다. 스키마 확인 대상과 업무 관계에 필요한 테이블을 판별할 때 둘을 구분해야 합니다.

`extract_physical_tables(sql)`은 파싱한 뒤 `physical_tables_from_tree(tree)`를 호출합니다. 후자는 SQLGlot의 `traverse_scope()`로 각 조회 범위에서 실제 `exp.Table`과 CTE·하위 질의 참조를 구분합니다. SQL 전체에서 CTE 이름을 한꺼번에 빼면 다른 범위의 같은 이름을 가진 실제 테이블까지 누락할 수 있으므로 스코프별로 분석합니다.

SQLite 식별자의 대소문자 비교를 위해 트리 복사본을 정규화합니다. 원본 AST와 반환하는 원래 테이블 이름은 보존합니다. 중첩·재귀 CTE, 스키마 접두사가 있는 테이블, UNION의 별도 조회 범위는 [AST 테스트](../../../tests/execution/test_sql_ast.py)에서 확인합니다.

## Predicate: 조건식에서 필터 값 추출

Predicate는 `=`, `<>`, `IN`, `BETWEEN`, `LIKE` 등 조건 판단에 사용되는 표현입니다. `extract_filter_literals()`는 AST의 `exp.Predicate` 아래에 있는 문자열 리터럴을 모읍니다.

- 문자열 리터럴만 추출하고, 빈 값과 중복을 제거합니다.
- `LIKE`·`ILIKE` 조건에서는 값 양끝의 `%`, `_`를 정리합니다.
- 정규식에 맞는 일·주·월·년 단위 날짜 이동 문자열(예: `'-1 days'`)은 제외합니다.
- 주석이나 단순 출력 상수는 필터 근거로 취급하지 않습니다.

이 결과는 필드·연산자·값을 연결한 완전한 필터 모델이 아니라 **문자열 값 목록**입니다. 함수 인자에 있는 날짜 문자열 등이 포함될 수도 있고, 숫자 조건이나 모든 날짜 수정자를 다루는 것도 아닙니다. [SQL Tool](../tools/README.md)은 추출한 값을 질문·확인한 스키마·별칭과 대조해 근거 없는 조건을 탐지합니다. 날짜 수정자를 제외했다는 사실만으로 업무적 타당성이 보장되지는 않습니다.

## SQL Contract: 분석 계획과 SQL의 실행 계약

SQL Contract는 분석 계획의 지표·집계 기준·필터·정렬·개수 제한·업무 조건이 생성 SQL에 반영되어야 한다는 규칙입니다. Agent2UI에서 사용자가 검토·수정한 계획을 실제 실행과 연결하는 핵심 경계입니다.

`validate_sql_contract()`는 통과하면 입력 SQL을 그대로 반환하고 위반하면 코드와 상세 사유를 담은 `SqlContractViolation`을 발생시킵니다. 날짜 조건 교정은 이 함수가 아니라 별도의 기간 정책에서 수행합니다.

```mermaid
flowchart TD
    A["SQL 파싱"] --> B["식별자 역할 기반 JOIN 검사"]
    B --> C["스키마 문맥이 있으면 참조 검사"]
    C --> D{"분석 계획이 있는가?"}
    D -->|없음| E["입력 SQL 반환"]
    D -->|있음| F{"등록 모집단 지표인가?"}
    F -->|예| G["컴파일된 SQL과 정규화된 표현 비교"]
    G --> E
    F -->|아니오| H["지표 · 등록된 의미 지표 검사"]
    H --> I["그룹 · 정렬 · LIMIT · 필터 검사"]
    I --> J["설정된 업무 조건 검사"]
    J --> E
```

등록 모집단 지표는 [registered_metrics.py](../semantics/registered_metrics.py)가 만든 SQL과 SQLite 방언으로 정규화한 AST 출력이 같아야 합니다. 분모·관계·필터를 임의로 바꾸는 것을 막는 경로이며, 의미적으로 동등한 모든 SQL을 인정하는 비교는 아닙니다.

[SQL Tool](../tools/README.md#검사에서-실행까지)은 계약 검증을 읽기 전용·기간·업무 의미 검사와 연결하며, 실행 직전에도 재검증합니다. 조회 후의 결과 컬럼·단위 검사는 [결과 계약](../results/README.md)이 담당합니다.

## 그룹·정렬·개수 제한·필터

| 검사 | 현재 구현 |
|---|---|
| `_validate_grouping()` | 계획에 그룹 기준이 있으면 SQL의 `GROUP BY`를 요구한다. `day`, `month`, `year`는 실제 컬럼을 참조하는 날짜 버킷 표현을 확인하며, 물리 필드로 판단한 이름은 그룹 표현에 포함되는지 확인한다. |
| `_validate_sort_and_limit()` | 최종 조회의 `ORDER BY` 항목 수와 계획 순서에 따른 방향·지원하는 물리 필드를 확인한다. 계획에 정수 `limit`이 있으면 SQL의 정수 `LIMIT`가 정확히 같아야 한다. |
| `_validate_explicit_filters()` | 단순 식별자 형식의 필터 필드가 조건식에 등장하는지 찾고, 지원하는 연산자·리터럴 값과 일치하는 조건이 있는지 확인한다. |

명시적 필터의 지원 연산자는 `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `between`, `contains`입니다. 예를 들어 계획이 `status eq paid`인데 SQL이 `status = 'pending'` 또는 `status <> 'paid'`이면 `filter_value_mismatch`가 발생합니다. 단순 식별자 필드에 대해 지원하지 않는 표현은 일치로 인정하지 않습니다.

그룹·정렬에서 물리 필드처럼 판단하는 기준은 단순 식별자이면서 언더스코어가 있거나 이름이 `id`인 경우입니다. 그룹 검사는 트리 안의 여러 SELECT에서 그룹 표현을 모으며 일부 비교는 문자열 포함 여부를 사용합니다. 필터 검사는 복잡한 AND·OR·NOT 조합이나 하위 질의 전체의 논리적 동등성을 증명하지 않습니다. 따라서 검사 통과를 모든 SQL 의미의 완전한 일치로 해석하면 안 됩니다.

## COUNT(*)와 COUNT(DISTINCT): 무엇을 세는가

배송 실패 기록이 10행이라고 해서 실패한 주문이 반드시 10개인 것은 아닙니다. 같은 주문에 실패 이벤트가 여러 번 발생하거나 JOIN으로 행이 늘어날 수 있습니다.

| 표현 | 집계 의미 |
|---|---|
| `COUNT(*)` | 조회 조건과 JOIN을 적용한 결과 행 수. |
| `COUNT(order_id)` | `order_id`가 NULL이 아닌 행 수. 같은 주문도 반복해 센다. |
| `COUNT(DISTINCT order_id)` | NULL을 제외하고 중복을 제거한 주문 식별자 수. |
| `COUNT(DISTINCT event_id)` | 중복을 제거한 이벤트 식별자 수. 고유 주문 수와는 다른 단위다. |

실패 기록 10행이 서로 다른 주문 4개의 반복 이력이고 주문 식별자가 모두 있다면, 앞의 두 표현은 10이고 고유 주문 수는 4입니다. DISTINCT를 붙여도 잘못된 식별자를 고르면 집계 단위가 달라집니다.

[MetricSpec](../../planning/analysis_models.py)은 `kind='count'`를 대상 건수로 취급해 `distinct=True`로 정규화합니다. `validate_metrics()`는 계획이 DISTINCT를 요구하면 실제 `COUNT`의 DISTINCT 여부를 확인하고, 기대 필드가 있으면 해당 필드 참조도 확인합니다. 기대 필드가 없는 DISTINCT 건수는 `id`, `*_id` 또는 프로필에 선언한 식별자 컬럼을 요구합니다.

일반 딕셔너리를 직접 전달하는 경우 `MetricSpec`의 정규화가 자동 적용되는 것은 아닙니다. 검증기는 전달된 지표의 `distinct`·`field`·`unit`과 업무 설정을 사용합니다.

## 지표 검증과 업무상 집계 단위

`validate_metrics()`는 최종 출력 표현식에서 `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`의 종류·필요 개수·필드 참조를 확인합니다. 서로 다른 계획 지표를 같은 집계 노드 하나로 중복 충족시키지 않도록 사용한 노드를 구분합니다. 비율 지표는 최종 출력에 명시적인 나눗셈 표현식을 요구합니다.

단순히 트리 어디에나 집계가 있으면 통과시키지는 않습니다. 예를 들어 날짜 기준일을 구하는 유틸리티 CTE의 `MAX(created_at)`은 주문 수 출력 지표가 아닙니다. 현재 검증은 최종 출력 표현식 안의 집계 노드를 확인하며, CTE 출력 별칭을 거슬러 올라가는 일반적인 계보 분석까지 수행하지는 않습니다.

`validate_semantic_metrics()`는 `semantic_id`가 지정된 경우 업무 설정의 등록 정의를 조회합니다. 등록되지 않은 이름, 다른 대상 필드·분자·분모 이름은 거절합니다. 조건부 DISTINCT 비율 경로에서는 아래와 같은 구조를 요구합니다.

```sql
SELECT
    1.0 * COUNT(DISTINCT CASE
        WHEN event_type = 'failed_delivery' THEN order_id
    END) / NULLIF(COUNT(DISTINCT order_id), 0) AS failure_rate
FROM order_events;
```

위 SQL은 구조 설명용 예시입니다. 실제 테이블·필드·실패 이벤트·모집단은 설정과 맞아야 합니다. `1.0` 곱셈 또는 지원하는 실수형 CAST로 정수 나눗셈을 피하고, `NULLIF(..., 0)`으로 분모가 0일 때를 처리하며, 같은 단위의 고유 식별자로 분자와 분모를 셉니다.

실패율을 구하면서 `WHERE event_type = 'failed_delivery'`로 분모까지 실패 대상만 남기면 원래 모집단을 잃습니다. 검증기는 이벤트 조건으로 분모를 좁히는 형태를 확인합니다. 다만 지원하는 조건부 DISTINCT 집계 형태를 대상으로 하며, 동등한 모든 대수 변환이나 CTE 기반 비율식을 허용하지는 않습니다. `population` 정의가 있는 지표는 이 경로 대신 등록 지표 컴파일 경로를 사용해야 합니다.

## 라이브 스키마 참조 검증

`validate_schema_references()`는 `schema_context`에서 `orders(order_id TEXT, status TEXT)`처럼 한 줄에 기술된 스키마를 읽습니다. 각 SQL 스코프에서 실제 테이블·컬럼과 CTE·하위 질의·출력 별칭을 구분하고, 확인된 스키마에 없는 참조는 `unknown_table`, `unknown_column`으로 보고합니다.

이 함수 자체가 DB를 조회하지는 않습니다. 실제 DB에서 수집한 설명을 [schema_tools.py](../tools/schema_tools.py)가 제공하고, 계약 검증기가 그 설명과 대조합니다. 스키마 문맥이 비어 있거나 지원하는 형식으로 읽을 수 없으면 이 검사 단계는 건너뜁니다.

CTE·하위 질의의 출력 참조는 해당 범위의 검사를 활용하며, 모든 출력 계보·모호한 컬럼·알 수 없는 한정자·중첩 비한정 컬럼을 완전히 해석하는 검증기는 아닙니다. 실제 SQL 실행과 결과 계약 검사를 함께 사용해야 합니다.

## 오류 코드와 확인 방법

| 대표 코드 | 의미 |
|---|---|
| `sql_parse_error`, `statement_count`, `not_a_query` | 파싱 실패, 문장 수 위반, 조회형이 아닌 입력. |
| `unknown_table`, `unknown_column` | 확인된 스키마와 참조 불일치. |
| `missing_metric`, `metric_projection_mismatch`, `count_unit_mismatch` | 출력 집계 종류·개수·집계 단위 불일치. |
| `missing_group_by`, `temporal_group_mismatch` | 그룹 누락 또는 날짜 버킷 불일치. |
| `sort_direction_mismatch`, `limit_mismatch` | 정렬 방향 또는 개수 제한 불일치. |
| `missing_filter`, `filter_value_mismatch` | 필터 누락 또는 지원하는 조건의 연산자·값 불일치. |
| `semantic_ratio_population`, `registered_metric_query` | 등록된 비율 모집단 또는 컴파일된 지표 SQL 계약 위반. |

[AST 테스트](../../../tests/execution/test_sql_ast.py), [SQL Tool 통합 테스트](../../../tests/execution/test_sql_tools.py), [JOIN 계약 테스트](../../../tests/execution/test_join_contract.py), [등록 지표 테스트](../../../tests/execution/test_registered_metrics.py)에서 관련 사례를 확인할 수 있습니다.

## 함께 읽기

- [SQL Agent 및 Tool Calling](../agent/README.md)
- [SQL Tool과 공유 상태](../tools/README.md)
- [업무·기간·집계 규칙](../semantics/README.md)
- [실행 결과 계약](../results/README.md)
- [실행 계층 안내](../README.md)
