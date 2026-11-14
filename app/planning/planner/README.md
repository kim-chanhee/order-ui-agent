# `app/planning/planner` · 공통 LLM 계획 생성기

질문을 구조화된 분석 계획으로 바꾸는 공통 모델 호출·응답 복구·문맥 상속·의미 검증을 담당합니다. Baseline은 `AnalysisDraft`와 `include_ui=False`로 화면 없이 계획을 만들고, A2UI는 `PlannerDraft`로 동적 UI와 추천 조건을 추가합니다. UI 검증 실패가 Baseline의 실행 조건이 되지 않습니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [context.py](context.py) | 후속 분석의 참조 후보 선택·조건 상속·식별자 필터 근거를 처리한다. |
| [controls.py](controls.py) | 검토용 UI의 선택지·기본 입력·중복·배치와 스키마 근거를 정리한다. |
| [dynamic_planner.py](dynamic_planner.py) | Baseline과 A2UI가 공유하는 LLM 분석 계획 생성 진입점. |
| [models.py](models.py) | 계획 생성 응답과 후속 분석 맥락을 표현하는 모델. |
| [prompt.py](prompt.py) | 질문·스키마·이전 분석 후보를 계획 및 UI 생성 프롬프트로 구성한다. |
| [response.py](response.py) | LLM 응답의 구조·타입·필드·UI 원시 값을 복구하고 모델로 검증한다. |
| [semantics.py](semantics.py) | 분석 지표·관계 범위를 정리하고 분석 의미와 날짜 안내의 일관성을 검증한다. |

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)
