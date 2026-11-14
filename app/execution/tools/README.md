# `app/execution/tools` · DB 스키마 탐색과 SQL 도구

모델이 선택한 작업을 실제 코드로 수행하는 Tool 계층입니다. Agent는 다음 행동을 결정하고, Tool은 스키마 탐색·SQL 검사·읽기 전용 조회와 실행 상태 관리를 담당합니다. [Agent의 ReAct·Tool Calling 흐름](../agent/README.md#react와-tool-calling)과 함께 읽을 수 있습니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [schema_tools.py](schema_tools.py) | 실제 SQLite 테이블·컬럼·관계와 샘플 값을 탐색하고 질문에 관련된 스키마를 제공한다. |
| [sql_tools.py](sql_tools.py) | SQL 검사·실행 Tool을 생성하고 검사 이력과 원시 조회 결과를 관리한다. |

## SQL Tool과 공유 상태

| 함수·클래스 | 실제 역할 |
|---|---|
| `make_query_checker_tool()` | 질문·계획·기간 문맥과 상태를 캡처한 `query_checker` Tool을 만든다. 추가 LLM 호출 없이 코드로 검사하며, 통과한 SQL 또는 날짜 상한을 교정한 SQL을 반환한다. |
| `make_execute_query_tool()` | `execute_query` Tool과 성공 조회 목록을 함께 반환한다. Tool은 모델에 결과 문자열을 반환하고, 호출자는 성공 목록에서 SQL·컬럼·행을 얻는다. |
| `SqlToolState` | 두 Tool이 같은 실행 문맥에서 검사 이력·교정 SQL·확인한 스키마·결과 제한 정보를 공유한다. |
| `normalize_sql()` | 인용된 값을 보존하면서 공백과 끝 세미콜론을 정리해 검사·실행 SQL을 비교할 키를 만든다. SQL의 의미적 동등성을 판정하는 함수는 아니다. |
| `_validate_execution_sql()` | 두 Tool이 공유하는 읽기 전용·계획·스키마·기간·업무 조건 검증 순서를 제공한다. |
| `extract_referenced_tables()` | 실행 SQL의 물리 테이블을 AST의 스코프로 구분해 추출한다. 파싱 실패 시 진단용 문자열 추출을 보조적으로 사용한다. |

Agent는 하나의 `SqlToolState(require_schema_inspection=True)`를 만들어 두 생성 함수에 동일하게 전달합니다. 별도로 Tool을 구성할 때도 같은 상태를 전달해야 검사 성공 이력과 실행 허용 판단이 연결됩니다. 상태를 생략하면 각 생성 함수가 자신만의 상태를 만듭니다.

| `SqlToolState` 필드 | 용도 |
|---|---|
| `checked_queries` | 검사에 통과한 최종 SQL의 정규화 키 집합. |
| `checked_rewrites` | 최초 요청 SQL의 키에서 교정된 SQL로 연결하는 매핑. |
| `inspected_tables` | 스키마 확인 이력이 있는 테이블 이름 집합. |
| `schema_context` | 초기 검색과 `get_table_schema` 호출로 모은 스키마 설명. |
| `require_schema_inspection` | 실행 전 모든 참조 테이블의 스키마 확인을 요구할지 결정한다. 클래스 기본값은 `False`이고 Agent는 `True`로 설정한다. |
| `last_result_truncated`, `last_returned_row_count` | 마지막 DB 실행의 결과 제한 여부와 반환 행 수. 후보별 메타데이터 저장소는 아니다. |

## 검사에서 실행까지

1. **필터 근거 검사:** `query_checker`가 후속 질문에 임의로 추가된 범주 조건과 질문·스키마·별칭에 근거가 없는 문자열 조건을 확인합니다.
2. **공통 SQL 검증:** 읽기 전용 SQL → 계획·라이브 스키마 계약 → 상대 기간 → 설정된 업무 의미 순서로 검사합니다. 날짜 상한이 교정될 수 있습니다.
3. **검사 이력 등록:** 최종 SQL의 키와 원래 SQL → 교정 SQL 매핑을 상태에 기록합니다. 실패한 SQL은 등록하지 않습니다.
4. **실행 허용 확인:** `execute_query`는 검사 성공 키 또는 교정 매핑에 있는 SQL만 받습니다. Agent 경로에서는 모든 참조 테이블의 스키마 확인 이력도 요구합니다.
5. **실행 직전 재검증:** 현재 계획·스키마·기간·업무 조건으로 공통 검증을 다시 수행한 뒤 읽기 전용 DB 연결로 실행합니다.
6. **결과 계약 검사:** 컬럼·요청 속성·결과 단위를 검사하고, 통과한 `(SQL, 컬럼, 행)`을 성공 목록에 추가합니다. 이 목록을 Agent의 후보 선택에 전달합니다.

예를 들어 `query_checker`가 `status = 'paid'`인 SQL을 검사한 후 모델이 `status = 'pending'`으로 바꾸면, 바뀐 SQL을 다시 검사해야 합니다. 날짜 조건이 검사 과정에서 교정된 경우에는 등록된 매핑을 통해 원래 SQL을 제출해도 교정된 SQL을 실행할 수 있습니다.

날짜 수정자(`'-1 days'` 등)를 필터 값 추출에서 제외하는 것은 보조 처리입니다. 그것만으로 필터의 업무적 타당성이 보장되지는 않으며 [SQL 계약](../sql/sql_contract.py)과 [업무·기간 규칙](../semantics/README.md)을 함께 적용합니다. 계약 검사도 지원하는 조건 범위 안에서 동작하므로 모든 SQL의 의미적 정확성을 보장하지 않습니다.

## 스키마 탐색과 오류 복구

`schema_tools.py`는 테이블 목록, 컬럼·값 확인, 관련 스키마 검색, 업무 의미 조회와 관계 후보 탐색을 제공합니다. 초기 스키마 검색은 코드에서 먼저 수행하고, 모델은 필요하면 `get_table_schema`, `get_semantic_context`, `discover_relationships`를 추가 호출합니다. 업무 문서는 보조 근거이며 물리 테이블·컬럼의 존재는 실제 DB 스키마로 확인합니다.

SQL 검사·실행 오류는 `Error:` 문자열로 반환하고, Tool 호출 중 예외는 Agent가 `Tool error:` 메시지로 바꿔 모델에 전달합니다. 모델은 오류를 근거로 SQL을 수정하거나 스키마를 추가 확인할 수 있습니다. SQL Tool 자체가 LLM을 호출하거나 자동으로 SQL을 재작성하는 것은 아닙니다. 반복과 모델 오류 재시도는 [Agent](../agent/README.md#실행-제한과-오류-복구)가 관리합니다.

## 결과 미리보기와 반환 상한

- DB 반환 상한은 `SQL_MAX_RESULT_ROWS`로 설정하며 코드 기본값은 200행입니다. 양수일 때 한 행을 추가로 읽어 잘림 여부를 확인하고 상한까지 보존합니다. 0 이하이면 이 도구의 행 수 상한을 적용하지 않습니다.
- 모델에는 최대 20행의 미리보기를 보여줍니다. UI와 성공 목록에는 DB 반환 상한 내에서 보존한 전체 결과를 전달합니다. 모델 미리보기만으로 전체 건수를 계산하면 안 됩니다.
- 결과가 비면 범주값과 연결 경로를 확인하고 한 번 더 시도하라는 안내를 모델에 반환합니다. 이는 자동 재실행이 아니라 모델에 제공하는 수정 지침입니다.
- 결과 계약을 통과한 빈 조회도 성공 목록에 들어갈 수 있습니다. 실행 성공은 데이터가 존재한다거나 업무적 정답이라는 뜻은 아닙니다.

## 관련 검증

[실행 테스트](../../../tests/execution/test_sql_tools.py)는 검사 이력 없는 실행 차단, 스키마 확인, 계획·필터 재검증, 날짜 상한 교정, 결과 계약, 모델 미리보기와 UI 결과 보존을 확인합니다. [AST 테스트](../../../tests/execution/test_sql_ast.py)는 중첩·재귀 CTE와 물리 테이블 구분을 확인합니다.

## 함께 읽기

- [SQL Agent 및 Tool Calling](../agent/README.md)
- [SQL 파싱·검증·실행](../sql/README.md)
- [업무·기간·집계 규칙](../semantics/README.md)
- [결과 검증과 응답 구성](../results/README.md)
- [실행 계층 안내](../README.md)
