# `app/execution/semantics` · 업무 의미와 집계 규칙

업무 의미와 집계 규칙를 담당합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [analysis_semantics.py](analysis_semantics.py) | 업무 의미 설정을 읽고 엔터티 생애주기·식별자 역할·관계 범위 조건을 제공하고 검사한다. |
| [semantic_aliases.py](semantic_aliases.py) | 사용자 표현과 DB 표준 값의 별칭 및 표시 라벨을 제공한다. |
| [registered_metrics.py](registered_metrics.py) | 등록된 모집단·부분집합 지표를 공통 SQL로 컴파일하고 동일한 검사·실행 도구로 실행한다. |
| [join_contract.py](join_contract.py) | 설정된 식별자 역할에 따라 CTE를 포함한 잘못된 연결을 검사한다. |
| [temporal_policy.py](temporal_policy.py) | 상대 기간의 데이터 기준일과 날짜 조건을 검사하고 필요한 날짜 상한을 교정한다. |

## 연결 흐름

업무 설정은 Data/docs/ 또는 환경 변수로 선택한 파일에서 읽습니다. planning과 tools/가 의미 문맥을 사용하고, sql/의 계약 검사와 공통 실행 경로가 업무·기간 규칙을 적용합니다.

## 함께 읽기

- [실행 계층 안내](../README.md)
- [앱 전체 구조](../../README.md)
