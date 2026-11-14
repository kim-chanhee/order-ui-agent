# `app/a2ui` · 서버의 화면 전송 모델

분석 계획과 조회 결과를 브라우저가 렌더링할 화면 데이터로 변환합니다. 컴포넌트 종류·동작·클라이언트 지원 기능을 정의합니다.

[화면 전송 모델의 UI 예시](../../docs/system-guide.md#분석-계획에서-확인-ui로)

## 주요 파일

| 파일 | 역할 |
|---|---|
| [adapter.py](adapter.py) | 두 모드의 조회 결과를 공통 A2UI 화면 형식으로 변환한다. |
| [catalog.py](catalog.py) | 지원 UI 컴포넌트와 클라이언트 기능 선언. |
| [models.py](models.py) | 화면·컴포넌트·액션·지원 기능의 Pydantic 전송 모델. |
| [review.py](review.py) | A2UI 전용 검토 계획을 화면 데이터로 변환하고 저장한다. |

## 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)
