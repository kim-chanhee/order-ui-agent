# `app/planning` · 분석 계획과 편집 UI 정의

질문·DB 스키마·이전 분석을 기간·대상·지표·필터·집계 기준으로 구조화하고 검토용 UI 정의를 만듭니다.

[분석 계획이 UI로 연결되는 예시](../../docs/system-guide.md#분석-계획에서-확인-ui로)

## 주요 파일

| 파일 | 역할 |
|---|---|
| [analysis_models.py](analysis_models.py) | SQL과 분리된 의미 기반 분석 계획을 Pydantic 모델로 정의한다. |
| [option_catalog.py](option_catalog.py) | 스키마와 현재 분석 계획에 근거한 확인 화면 선택지를 만든다. |
| [schema_context.py](schema_context.py) | 실제 데이터베이스에서 질문과 관련된 계획 수립용 스키마 맥락을 수집한다. |
| [service.py](service.py) | Baseline과 A2UI가 공유하는 분석 계획 생성 서비스. |
| [ui_models.py](ui_models.py) | 두 모드가 공유하는 선언형 UI와 분석 계획 응답 모델. |
| [validator.py](validator.py) | 두 모드가 공유하는 UI 조건 평가와 필수 입력 필드 계산. |

## 연결 흐름

service.py가 스키마 문맥과 이전 분석 후보를 모아 planner/를 호출합니다. 생성된 AnalysisPlan과 UI 블록을 UiPlan으로 묶습니다. 두 입력 모드가 이 계획 생성 계층을 공유합니다.

## 하위 폴더 안내

| 폴더 | 역할 |
|---|---|
| [a2ui/](a2ui/README.md) | 계획 검토·추가 조건·편집 검증 |
| [planner/](planner/README.md) | 공통 LLM 계획 생성기 |

## 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)
