# HTTP API 구조와 Baseline·A2UI의 역할

`app/routes`는 브라우저의 HTTP 요청을 받아 내부 서비스를 호출하고, 결과를 응답하는 계층이다. 공통 API는 폴더 바로 아래에, A2UI 전용 API는 `a2ui/` 아래에 둔다.

사용자 화면에서 부르는 A2UI 모드의 API 필드 값은 `agent2ui`이다. 코드와 요청 예시에서는 이 값을 사용한다.

## 공통 기능과 모드 전용 기능

| 구분 | 공통 | Baseline | A2UI |
|---|---|---|---|
| 질문 접수 | `POST /api/chat` | `input_source="baseline"` | `input_source="agent2ui"` |
| 질문 유형 판단 | `app/chat`에서 분석·대화·결과 설명 등을 구분 | 분석 요청이면 검토 단계 없이 실행 경로로 전달 | 분석 요청이면 계획 검토 화면을 먼저 반환 |
| 검토 중 자연어 조건 추가 | — | 전용 API 없음 | `POST /api/review/refine` |
| 계획 확정 실행 | — | 전용 API 없음 | `POST /api/review/confirm` |
| 실행 취소·실험 관리·요청 형식·오류 처리 | 두 모드가 공유 | 공통 API 사용 | 공통 API 사용 |

Baseline에도 내부 분석 계획 생성 과정이 있다. 차이는 사용자가 계획을 검토·확정하는 HTTP 단계를 거치는지에 있다. 두 모드 모두 일반 대화, 저장된 결과 요약·설명·표시 변경은 새 SQL 실행 없이 처리할 수 있다. 조건이 불명확하면 확인 질문을 반환할 수 있다.

## 파일별 책임

### api.py

`chat.router`, `a2ui.review.router`, `experiment.router`를 하나의 라우터에 등록한다. `app/server.py`가 이 라우터를 FastAPI 앱에 연결한다. 직접 처리하는 요청은 기본 HTML을 반환하는 `/`와 상태 확인용 `/health`이다.

`/health`는 로컬 자원 상태와 LLM 공급자·모델 이름, 별도 서버 주소 설정 여부를 반환한다. API 키는 응답에 포함하지 않는다.

### chat.py

질문을 받아 `app/chat/service.py`의 `chat_response_payload()`에 전달한다. 활성 실험이면 현재 과제에 맞는 대화·과제 ID를 적용한다. 실행 후에는 소요 시간과 로그를 기록하고, 실제 조회 결과를 후속 질문용 대화 상태에 저장한다.

- `thread_id`: 여러 질문과 결과가 이어지는 대화 식별자.
- `run_id`: 취소할 개별 실행 작업의 식별자.
- `_chat_stage()`: 결과를 계획 생성·실행·대화·요약 등의 로그 단계로 분류한다.
- `_should_record_execution_result()`: 기존 결과 설명·요약 등을 새 조회 결과로 중복 저장하지 않도록 구분한다.

현재 일반 채팅은 `run_id`가 있으면 취소 가능한 워커에서 실행한다. 활성 실험의 채팅은 서비스를 직접 호출한다. 취소 API는 실행 관리자에 등록된 워커를 중단한다.

### a2ui/review.py

`confirm_review()`는 계획을 검증한 뒤 실행 서비스에 전달한다. 실행 결과와 후속 질문용 문맥, 편집 시간·변경 필드·계획 차이 등의 로그를 기록한다. `run_id`가 있으면 취소 가능한 워커를 사용한다.

`refine_review()`는 추가 조건을 계획에 반영하고 화면을 다시 생성한다. SQL은 실행하지 않으며, `revision`과 수정 횟수를 하나씩 올린다.

두 요청은 다음 검증 함수를 공유한다.

- `_validate_surface_revision()`: 화면이 저장되어 있는지, 전달된 계획 ID와 버전이 최신 화면과 맞는지 확인한다. 없거나 맞지 않으면 `409 PLAN_REVISION_CONFLICT`를 반환한다.
- `_with_authoritative_ui_schema()`: 분석 값의 변경이 허용된 편집 범위인지 검증하고, UI 구조·요약·경고·확정 필요 여부 등은 서버가 저장한 값으로 적용한다.

`surface_id`는 검토 화면 식별자, `plan_id`는 계획 식별자, `revision`은 화면 버전이다. 예를 들어 조건 추가 후 서버 버전이 2가 되면, 버전 1로 확정하는 요청은 거절한다.

### experiment.py

참여자 세션 생성·복원, 진행 상태 조회, 과제 완료, 다음 단계 이동, CSV 내보내기를 담당한다. 실제 저장과 단계 이동 규칙은 `app/experiment/store.py`에 있다. 성공한 상호작용 없이 과제를 완료하거나, 과제 완료 전에 다음 단계로 넘어가는 요청은 제한된다.

CSV 내보내기의 `researcher_key`는 `ORDER_UI_RESEARCHER_KEY`와 비교한다. 현재 환경 변수 미설정 시 기본값은 `dev`이다.

### schemas.py / errors.py / web_ui.py

| 파일 | 책임 |
|---|---|
| `schemas.py` | Pydantic 모델로 요청·응답 필드, 자료형, 필수 값, 길이·수치 범위를 정의한다. `ClientMetrics`는 편집 시간과 변경 내역을 담는다. |
| `errors.py` | 오류 코드와 `error.code`, `message`, `field_errors`, `retryable`, `details` 형태를 정의한다. 최종 오류 응답 처리는 `app/server.py`가 담당한다. |
| `web_ui.py` | 기본 HTML을 모듈 로딩 시 읽고, 템플릿·정적 파일 경로를 제공한다. `/static` 연결은 `app/server.py`에서 수행한다. |

요청 형식은 `schemas.py`에서 검사하고, 분석 조건의 의미와 편집 가능 범위는 계획 검증 로직에서 검사한다. A2UI 전용 요청·응답 모델은 `a2ui/schemas.py`에 정의하며, 공통 `ClientMetrics`를 참조한다.

## API 목록

| 메서드 | 주소 | 담당 파일 |
|---|---|---|
| GET | `/` | `api.py` |
| GET | `/health` | `api.py` |
| POST | `/api/chat` | `chat.py` |
| POST | `/api/runs/{run_id}/cancel` | `chat.py` |
| POST | `/api/review/refine` | `a2ui/review.py` |
| POST | `/api/review/confirm` | `a2ui/review.py` |
| POST | `/api/experiment/start` | `experiment.py` |
| GET | `/api/experiment/session/{participant_id}` | `experiment.py` |
| POST | `/api/experiment/task/complete` | `experiment.py` |
| POST | `/api/experiment/step/advance` | `experiment.py` |
| GET | `/api/experiment/export` | `experiment.py` |

## 하위 폴더 안내

| 폴더 | 역할 |
|---|---|
| [a2ui/](a2ui/README.md) | 계획 수정·확정 HTTP API |

## 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)
