# `app/execution/sql` · SQL 구문 분석·생성·검증

SQL 구문 분석·생성·검증를 담당합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [sql_ast.py](sql_ast.py) | SQLite SQL 파싱, 공통 계약 예외와 스코프 기반 물리 테이블·필터 값 추출을 제공한다. |
| [sql_builder.py](sql_builder.py) | 검증된 SQL을 읽기 전용 DB 연결로 실행하고 기본 표 형식과 실행 계획을 제공한다. |
| [sql_contract.py](sql_contract.py) | 분석 계획의 그룹·정렬·개수 제한·필터·업무 조건 검사를 조율한다. |
| [sql_safety.py](sql_safety.py) | 단일 조회문과 읽기 전용 연결로 데이터 변경을 차단한다. |
| [sql_schema_contract.py](sql_schema_contract.py) | 테이블·컬럼 참조를 확인된 라이브 스키마와 대조한다. |
| [sql_metric_contract.py](sql_metric_contract.py) | 집계 종류·건수 단위와 등록된 비율 지표의 계약을 검사한다. |

## 연결 흐름

tools/sql_tools.py가 안전성·계약 검사를 호출하고 검증된 SQL을 실행합니다. sql_contract.py는 semantics/의 업무 규칙도 사용합니다. LLM의 SQL 생성과 도구 호출 제어는 agent/fast_sql_agent.py에서 담당합니다.

## 함께 읽기

- [실행 계층 안내](../README.md)
- [앱 전체 구조](../../README.md)
