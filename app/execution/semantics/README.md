# `app/execution/semantics` · 업무 의미와 집계 규칙

> **한눈에 보기** · 주문 수와 이벤트 수의 차이처럼, 테이블 구조만으로 알기 어려운 업무 규칙을 관리합니다. 기간의 기준일과 집계 대상도 여기서 정합니다.

**기본 흐름:** 업무 설정 → 집계·관계·기간 규칙 → SQL 생성·검사에 제공

업무 의미와 집계 규칙을 담당합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [analysis_semantics.py](analysis_semantics.py) | 업무 의미 설정을 읽고 엔터티 생애주기·식별자 역할·관계 범위 조건을 제공하고 검사한다. |
| [semantic_aliases.py](semantic_aliases.py) | 사용자 표현과 DB 표준 값의 별칭 및 표시 라벨을 제공한다. |
| [registered_metrics.py](registered_metrics.py) | 등록된 모집단·부분집합 지표를 공통 SQL로 컴파일하고 동일한 검사·실행 도구로 실행한다. |
| [join_contract.py](join_contract.py) | 설정된 식별자 역할에 따라 CTE를 포함한 잘못된 연결을 검사한다. |
| [temporal_policy.py](temporal_policy.py) | 상대 기간의 데이터 기준일과 날짜 조건을 검사하고 필요한 날짜 상한을 교정한다. |

## JOIN의 의미적 유효성

컬럼명이 비슷하거나 SQL 문법이 맞아도 업무적으로 올바른 연결이 되는 것은 아닙니다. 예를 들어 주문 식별자를 상품 식별자와 비교하면 우연히 같은 문자열이 있어도 다른 대상을 연결하게 됩니다. [스키마 검색·관계 후보 탐색](../tools/README.md#그래프-기반-관계-탐색)은 가능한 연결을 찾고, [join_contract.py](join_contract.py)의 `validate_join_roles()`는 설정으로 확인된 식별자 역할 사이의 충돌을 검사합니다.

### 주요 함수와 적용 시점

| 함수 | 역할 |
|---|---|
| `validate_join_roles(tree)` | SQL 스코프마다 두 컬럼의 동등 비교를 찾아 업무 역할 집합이 서로 충돌하는지 확인한다. |
| 내부 `roles(column, scope, seen)` | 실제 테이블·설정과 CTE/하위 질의의 직접 투영을 따라 컬럼의 역할 집합을 구한다. 재귀 방문 이력으로 순환 탐색을 막는다. |

[validate_sql_contract()](../sql/sql_contract.py)가 SQL 파싱 직후 호출합니다. 분석 계획이 없더라도 JOIN 역할 검사는 실행되며, 설정된 역할이 없으면 알 수 없는 역할로 남습니다. 검사 대상은 `JOIN ... ON`뿐 아니라 해당 SELECT 범위의 `WHERE` 등에 있는 **컬럼 = 컬럼** 비교도 포함합니다. 비동등 비교나 `USING`, `NATURAL JOIN`을 같은 방식으로 검사하는 것은 아닙니다.

### 식별자 역할 설정

업무 의미 설정의 두 항목을 사용합니다.

| 설정 | 의미 |
|---|---|
| `entity_roles.<entity>.identifier_fields` | 식별자 이름이 어떤 엔터티를 나타내는지 선언한다. 테이블별 규칙이 없을 때 역할 근거로 사용할 수 있다. |
| `column_roles` | 특정 테이블·컬럼의 고정 역할(`entity`) 또는 구분 컬럼(`discriminator`) 값에 따른 역할(`entities`)을 선언한다. |

다음은 방향에 따라 서로 다른 엔터티를 참조하는 관계 테이블의 설정 예시입니다.

```json
{
  "entity_roles": {
    "order": {"identifier_fields": ["order_id"]},
    "item": {"identifier_fields": ["item_id"]}
  },
  "column_roles": [
    {"table": "events", "field": "object_key", "entity": "item"},
    {"table": "links", "field": "source", "discriminator": "kind", "entities": {"contains": "order"}},
    {"table": "links", "field": "target", "discriminator": "kind", "entities": {"contains": "item"}}
  ]
}
```

`links.kind = 'contains'`인 범위에서 `source`는 주문, `target`은 상품 역할로 해석합니다. 구분 조건은 같은 SELECT 범위와 해당 테이블 별칭에 맞는 동등 조건에서 찾습니다. 다른 별칭의 `kind` 조건을 빌려 역할을 확정하지 않습니다.

### CTE 별칭을 따라가는 검증

```sql
WITH x AS (
    SELECT object_key AS item_id
    FROM events
)
SELECT x.item_id
FROM x
JOIN links AS l ON l.target = x.item_id
WHERE l.kind = 'contains';
```

위 설정에서 `events.object_key`는 상품 식별자입니다. 검증기는 `x.item_id`라는 별칭에서 CTE의 직접 투영 컬럼으로 돌아가 원래 역할을 확인합니다. `l.target`도 상품 역할이므로 이 비교에서 역할 충돌을 보고하지 않습니다. 반면 연결을 `l.source = x.item_id`로 바꾸면 주문과 상품 역할이 충돌해 `incompatible_join_keys`가 발생합니다. 이름을 바꿨다는 이유만으로 원래 역할이 사라지지 않도록 하는 처리입니다.

역할 추적은 직접 컬럼 투영, 별칭, 괄호와 CAST를 벗겨낸 직접 컬럼 등을 지원합니다. 모든 함수·수식·`SELECT *`·UNION 출력 계보를 완전히 해석하는 범용 계보 분석기는 아닙니다. 소스가 여러 개인 비한정 컬럼은 선언된 식별자 이름을 역할 근거로 사용할 수 있으므로, 정확한 테이블별 식별을 위해 명시적 별칭을 사용하는 편이 좋습니다.

### 차단 조건과 한계

검증기는 양쪽 역할 집합이 **모두 비어 있지 않고 교집합이 없을 때** 계약 위반을 발생시킵니다. 한쪽 또는 양쪽 역할을 모르면 그 비교만으로 차단하지 않습니다. 같은 역할이거나 일부 역할이 겹쳐도 연결의 모든 업무 조건이 맞다고 증명하는 것은 아닙니다.

- 같은 엔터티 역할이라도 관계 방향·관계 종류·필요한 한정 조건과 모집단은 별도로 확인해야 합니다.
- 이름 기반 역할 선언은 실제 스키마의 컬럼 존재를 증명하지 않습니다. 라이브 스키마 계약 검사와 함께 적용합니다.
- 빈 조회 결과나 실제 값 하나의 일치는 JOIN의 의미적 유효성을 보장하지 않습니다.
- 설정이 부족하거나 잘못되어 있으면 역할 검증이 탐지하지 못하거나 잘못된 역할 근거를 사용할 수 있습니다.

## 핵심 개념과 동작

업무 의미 설정은 **무엇을 한 건으로 세고, 어떤 대상을 연결할지 정한 규칙**입니다. 같은 ID 형식이라도 주문과 패키지는 서로 다른 대상입니다.

비율 지표에서는 전체 대상(population)과 조건에 해당하는 대상(subset)을 나눕니다. LEFT JOIN으로 연결해 해당 건수가 0인 그룹도 남깁니다. 별칭은 현재 질문에 실제로 등장한 표현에만 적용합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `load_analysis_semantics` | 경로·파일 크기·수정 시각으로 의미 설정 캐시 | 설정 캐시 무효화 |
| `canonical_values_for_text` | 질문의 별칭을 표준 값으로 연결 | 의미 grounding |
| `validate_join_roles` | 확인된 식별자 역할 충돌 차단 | CTE 역할 계보 |
| `validate_relative_time_sql` | 필터 없는 데이터 MAX anchor와 날짜 창 검사 | Temporal anchor |
| `compile_registered_metric` | 모집단·부분집합 공통 SQL 컴파일 | 정의 기반 지표 |

### 핵심 코드: validate_relative_time_sql

최근 기간을 실행 머신의 오늘이 아니라 데이터셋의 시간축에 맞춥니다.

**동작:** 확정 기간을 읽고 머신 시계·미지원 INTERVAL을 거절한 뒤 필터 없는 MAX anchor CTE를 찾습니다.

**설계:** 지원 SQL 패턴을 인용·주석 정리와 함께 검증합니다. 실패 이벤트만의 MAX를 기준일로 삼으면 모집단의 기간이 뒤로 이동할 수 있기 때문입니다.

**예:** 최근 2일은 기준일 하루 전부터 시작하며 타임스탬프 상한은 다음날 미만 형태로 교정될 수 있습니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/execution/semantics/temporal_policy.py](temporal_policy.py#L95). 아래는 실제 코드의 95~111행 발췌이며 앞뒤는 생략했습니다.

```python
relative_required, spec = _authoritative_relative_spec(question, temporal_context)
if not relative_required:
    return sql
inspected_sql = _strip_sql_comments(sql)
if _MACHINE_CLOCK_PATTERN.search(inspected_sql):
    raise ValueError(
        "relative time windows must use the relevant data maximum, not the machine clock"
    )
if _INTERVAL_PATTERN.search(inspected_sql):
    raise ValueError("SQLite relative windows must not use unsupported INTERVAL syntax")

anchor = _find_unfiltered_data_anchor(inspected_sql)
if anchor is None:
    raise ValueError(
        "relative time SQL must define an unfiltered anchor CTE shaped like "
        "SELECT MAX(date_column) AS anchor_at FROM relevant_table"
    )
```

</details>

### 핵심 코드: try_registered_metric

등록 지표도 일반 SQL과 같은 실행 경계를 통과시킵니다.

**동작:** 컴파일 SQL의 실제 테이블을 확인하고 공유 상태를 만든 뒤 검사 Tool과 실행 Tool을 호출합니다.

**설계:** LLM 없는 컴파일과 공통 Tool 검증 조합입니다. 등록된 분모·관계 정의를 보존하면서 안전성·스키마·결과 검증을 우회하지 않습니다.

**예:** 등록 비율 지표는 population_count·subset_count·rate 행을 반환하고 경로를 registered_metric으로 남깁니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/execution/semantics/registered_metrics.py](registered_metrics.py#L133). 아래는 실제 코드의 133~145행 발췌이며 앞뒤는 생략했습니다.

```python
tables=sorted(extract_physical_tables(sql))
schema=str(get_table_schema.invoke({'table_names':','.join(tables)}))
state=SqlToolState(inspected_tables=set(tables), schema_context=[schema], require_schema_inspection=True)
kwargs=dict(question=confirmed_context.semantic_validation_text(), confirmed_plan=confirmed_context.confirmed_plan,
            temporal_context=confirmed_context.temporal_context, state=state)
checked=make_query_checker_tool(**kwargs).invoke({'sql':sql})
if checked.startswith('Error:'):
    raise ValueError(checked)
execute, successes=make_execute_query_tool(**kwargs)
result=execute.invoke({'sql':checked})
if not successes:
    raise ValueError(result)
executed, columns, rows=successes[-1]
```

</details>

### 다른 기능과 연결되는 순서

planning의 카탈로그와 실행 문맥이 의미 설정을 공유합니다. timeline_anchor는 기간 미리보기와 SQL 검사에 사용하고, JOIN 역할 검증은 sql_contract 파싱 직후, 등록 지표 컴파일은 confirmed_execution에서 먼저 시도합니다.

### 확인한 범위와 한계

기간 검사는 지원하는 SQL 패턴 중심이며 일반적인 모든 날짜식의 동등성 검증기가 아닙니다. 설정이 누락되면 역할이 미확인 상태로 남을 수 있습니다. 별칭·의미 설정은 실제 스키마나 데이터의 정답 보증이 아닙니다.

관련 검증: [test_registered_metrics.py](../../../tests/execution/test_registered_metrics.py), [test_join_contract.py](../../../tests/execution/test_join_contract.py), [test_data_profile.py](../../../tests/test_data_profile.py).

## 함께 읽기

- [실행 계층 안내](../README.md)
- [앱 전체 구조](../../README.md)
