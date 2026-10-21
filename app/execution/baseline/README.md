# `app/execution/baseline` · 프롬프트 모드 즉시 실행

프롬프트 질문의 내부 분석 계획을 생성하고 바로 실행해 응답을 구성합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [service.py](service.py) | Baseline 요청의 계획 생성·즉시 실행·응답 조립을 담당한다. |

## 연결 흐름

chat/dispatch.py → baseline_response_payload → 공통 planning 서비스 → 공통 SQL 실행 계층 순서입니다. 사용자에게 계획 확인 화면을 제시하는 HTTP 단계는 생략합니다.

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)
