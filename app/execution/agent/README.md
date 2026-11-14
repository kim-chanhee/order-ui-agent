# `app/execution/agent` · LLM 추론과 Tool 호출 제어

LLM 추론과 Tool 호출 제어를 담당합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [fast_sql_agent.py](fast_sql_agent.py) | LLM 응답을 해석하고 스키마 탐색·SQL 검사·실행 도구 호출을 조정한다. |

## 연결 흐름

confirmed_execution.py가 에이전트를 호출하며, 에이전트는 tools/의 도구를 통해 SQL을 검사하고 실행합니다. 등록된 모집단 지표는 semantics/registered_metrics.py에서 공통 도구로 직접 실행할 수도 있습니다.

## 함께 읽기

- [실행 계층 안내](../README.md)
- [앱 전체 구조](../../README.md)
