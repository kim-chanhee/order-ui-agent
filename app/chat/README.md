# `app/chat` · 대화 요청 분류와 문맥

자연어 한 턴을 분석·확인 질문·일반 대화·기존 결과 설명으로 분류하고 모드에 맞는 서비스로 전달합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [dispatch.py](dispatch.py) | 요청을 분류하고 분석 실행·계획 확인·저장 결과 활용 경로로 전달한다. |
| [responses.py](responses.py) | 대화·확인 질문·화면 안내 문구를 LLM으로 작성하는 공통 응답 계층. |
| [service.py](service.py) | 채팅 요청을 공통 대화 처리기로 전달하는 진입점. |
| [summary.py](summary.py) | 저장된 분석 결과를 공통 LLM 응답 계층으로 요약하는 호환 진입점. |
| [thread_context.py](thread_context.py) | 대화(thread) 맥락 관리. |
| [turn_router.py](turn_router.py) | 분석 계획 생성 전에 사용자 요청을 분류하고 저장된 결과 기반 응답을 만든다. |

## 연결 흐름

routes/chat.py → service.py → dispatch.py 순서로 들어옵니다. turn_router.py가 이전 결과를 참조할지 판단하고, 분석이면 execution/baseline 또는 chat/a2ui로 연결합니다.

## 하위 폴더 안내

| 폴더 | 역할 |
|---|---|
| [a2ui/](a2ui/README.md) | Agent2UI 계획 검토 응답 |

## 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)
