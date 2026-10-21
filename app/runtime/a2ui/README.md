# `app/runtime/a2ui` · 계획 화면 저장과 확정 워커

서버가 발급한 계획 화면의 최신 버전을 보관하고 취소 가능한 프로세스에서 확정 요청을 실행합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [surfaces.py](surfaces.py) | 최신 서버 발급 계획 화면과 revision 저장·조회. |
| [worker.py](worker.py) | 취소 가능한 워커에서 A2UI 계획 확정 요청을 검증하고 실행한다. |

## 연결 흐름

surfaces.py는 화면 ID별 계획·revision을 저장·조회합니다. worker.py는 확정 요청을 전용 모델로 검증한 뒤 실행 서비스에 전달합니다.

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)
