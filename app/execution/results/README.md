# `app/execution/results` · 실행 결과의 검증과 응답 구성

실행 결과의 검증과 응답 구성를 담당합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [result_contract.py](result_contract.py) | 반환 컬럼·결과 단위·요청 속성이 분석 계획과 일치하는지 검사한다. |
| [result_payload.py](result_payload.py) | Baseline과 Agent2UI에서 공유하는 실행 실패 응답 데이터를 구성한다. |

## 연결 흐름

tools/sql_tools.py는 DB 조회 후 결과 계약을 검사합니다. baseline/service.py와 a2ui/service.py는 실패 응답 데이터를 이용해 모드별 응답을 구성합니다.

## 함께 읽기

- [실행 계층 안내](../README.md)
- [앱 전체 구조](../../README.md)
