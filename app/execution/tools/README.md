# `app/execution/tools` · DB 스키마 탐색과 SQL 도구

DB 스키마 탐색과 SQL 도구를 담당합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [schema_tools.py](schema_tools.py) | 실제 SQLite 테이블·컬럼·관계와 샘플 값을 탐색하고 관련 스키마를 제공한다. |
| [sql_tools.py](sql_tools.py) | LLM용 SQL 검사·실행 도구와 공유 상태를 제공하고 실행 직전에도 검증한다. |

## 연결 흐름

agent/가 도구를 호출합니다. 스키마 탐색은 실제 DB를 읽고, SQL 도구는 sql/의 계약·안전성 검사, semantics/의 기간·업무 검사와 results/의 결과 검사를 연결합니다.

## 함께 읽기

- [실행 계층 안내](../README.md)
- [앱 전체 구조](../../README.md)
