# GPT API 운영과 비용 관리

2026-11-01 검토 기준. 현재 모델은 기존 GPT-4.1 mini의 고정 스냅샷 `gpt-4.1-mini-2025-04-14`입니다. API 키는 `.env`에서만 관리하고 기록하지 않습니다.

## 변경한 실행 경계

- 요청 분류: OpenAI에서는 strict JSON Schema 응답을 사용합니다. 로컬 서버의 도구 선택 방식과 분리합니다.
- 분석: `AnalysisDraft`가 공통 분석 의미를 정의하고 `PlannerDraft`가 A2UI의 화면 필드만 추가합니다.
- Baseline: 분석 계획을 검증한 뒤 직접 실행합니다. 생성 UI가 없거나 잘못돼도 UI 파싱 때문에 분석을 재생성하지 않습니다. 미해결 의미·부족한 집계 대상은 실행하지 않습니다.
- A2UI: 기존 동적 UI·선택지·편집 검증과 실행 전 확인을 유지합니다.
- 두 모드: 같은 기간·스키마·집계·관계·결과 계약과 읽기 전용 SQL 실행기를 사용합니다.
- SQL 도구는 모델에게 최대 20개 행만 미리 보여줍니다. 사용자 결과 표에는 기존 반환 한도 내의 전체 검증 행을 유지합니다. 표본으로 전체 통계를 추측하지 않도록 표시합니다.
- 공급자 오류 분류·재시도는 `app/core/model_errors.py`가 담당합니다. 인증·크레딧 소진·앱 호출 한도는 재시도하지 않습니다. 답변 생성의 중첩 재시도를 제거했습니다.

## 설정 위치

`.env` 및 `.env.example`:

```dotenv
AGENT_PROVIDER=openai
AGENT_MODEL=gpt-4.1-mini-2025-04-14
AGENT2UI_PLANNER_MODEL=gpt-4.1-mini-2025-04-14
AGENT_BASE_URL=
AGENT_API_KEY=
OPENAI_API_KEY=your-key
AGENT_TIMEOUT_SECONDS=45
FAST_SQL_TIMEOUT_SECONDS=30
FAST_SQL_TOTAL_TIMEOUT_SECONDS=90
AGENT_RUN_TIMEOUT_SECONDS=240
LLM_MAX_CALLS_PER_REQUEST=12
LLM_MAX_PROMPT_BYTES=120000
LLM_ROUTING_MAX_OUTPUT_TOKENS=700
LLM_PLANNER_MAX_OUTPUT_TOKENS=4000
LLM_REPLY_MAX_OUTPUT_TOKENS=700
FAST_SQL_MAX_TOKENS=1600
```

`AGENT_BASE_URL`이 남아 있으면 `OPENAI_BASE_URL`보다 우선합니다. 로컬 모델에서 복귀할 때는 이 값을 지우고 모델·플래너 모델도 함께 바꿉니다. 설정 후 서버를 재시작합니다. `LM_STUDIO_BASE_URL`은 OpenAI 모드에서는 사용하지 않습니다.

## 제한과 기록의 의미

클라이언트 설정은 `app/core/llm_settings.py`, 요청 사용량과 호출 상한은 `app/core/llm_usage.py`에서 관리합니다. 숨은 SDK 재시도는 비활성화합니다. 앱 재시도를 포함해 요청당 12회 한도를 적용하고 다음 호출을 전송하기 전에 중단합니다. 큰 프롬프트는 도구 스키마까지 포함한 바이트 수로 차단합니다.

이 설정은 호출 수·입력 바이트·출력 토큰 제한이며 **하루 또는 월의 통화 금액 예산 상한이 아닙니다**. 채팅, 확정, 자연어 수정 요청은 각각 별도 요청입니다. 취소·타임아웃으로 로컬 처리가 끝나도 공급자에 이미 전송된 요청의 처리가 취소되거나 과금되지 않는다고 보장할 수 없습니다.

공급자가 보고한 입력·출력·캐시 토큰은 응답의 `execution_result.normalized_spec.llm_usage`와 `<ORDER_UI_LOG_DIR>/llm_usage.jsonl`에 기록합니다. 로그 경로를 지정하지 않으면 상태 DB 옆 `logs/`를 사용합니다. 프롬프트·키·결과 행은 이 사용량 로그에 넣지 않습니다. `responses_with_usage`, `usage_complete`로 누락을 구분합니다. 실패·중단되어 usage가 없는 호출의 비용은 0으로 확정하지 않습니다. 가격을 곱할 때는 실제 모델과 해당 시점 요율, 캐시 입력을 구분합니다.

## 연구 비교

공통 분석 규칙은 같지만 Baseline은 화면 없는 응답 스키마, A2UI는 화면을 포함한 응답 스키마를 사용합니다. 따라서 초기 LLM 계획까지 항상 같다고 주장해서는 안 됩니다. UI의 인과적 효과만 비교하려면 동일한 초기 계획을 고정한 짝 비교를 추가하거나, 초기 생성 차이와 사용자 수정 효과를 나누어 보고합니다. A2UI는 계획 생성·편집·확정 실행의 토큰과 시간을 합산해야 합니다.

개발 중 수정·실패 사례와 최종 평가셋을 분리하고, 과제 외 질문과 새로운 DB도 포함합니다. 모델·스냅샷·프롬프트·양자화·재시도·실행 제한을 기록합니다. 이번 로컬 단위/통합 검증은 실제 모델의 정답률을 대신하지 않습니다.

## 실제 확인 상태

`artifacts/gpt-review-20261101/connection.json`의 최소 연결 확인은 HTTP 429 `provider_quota_exhausted`로 종료했습니다. 재시도 없이 1회 요청 후 중단했습니다. 잔액이 복구되기 전에는 최종 코드의 실제 GPT 질문별 성공을 확인했다고 볼 수 없습니다. 복구 후 새 스레드에서 단순 고객 수, 상품명 목록, 기간 집계, 다중 테이블 조회, 과제 1·2와 후속 질문을 순서대로 비교합니다.

공식 참고: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [GPT-4.1 mini 스냅샷](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
