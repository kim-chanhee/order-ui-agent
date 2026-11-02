# `app/core` · 모델 연결 설정과 시작 점검

환경 변수에서 LLM 연결 설정을 읽고 앱 기동에 필요한 DB·상태 저장소·실험 설정을 점검합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [llm_settings.py](llm_settings.py) | SQL 에이전트가 쓸 OpenAI 호환 LLM 연결 값을 환경 변수에서 고른다. |
| [model_errors.py](model_errors.py) | 공급자 오류를 분류하고 일시적 오류만 제한 재시도한다. |
| [llm_usage.py](llm_usage.py) | 요청별 호출 상한과 실제 보고 토큰을 관리한다. 프롬프트·키는 기록하지 않는다. |
| [startup_checks.py](startup_checks.py) | 앱 기동 시 로컬 자원이 쓸 수 있는지 검사한다. |

## 연결 흐름

server.py의 시작 단계에서 설정과 자원을 검사합니다. routes/api.py의 상태 확인도 이 계층을 사용합니다. 시작 점검은 실제 모델 응답 품질을 측정하지 않습니다.

## 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)
