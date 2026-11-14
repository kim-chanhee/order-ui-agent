# LLM API 연결 코드 검토 — 2026-10-24

## 결론

현재 OpenAI API 연결과 인증은 정상이다. 실제 `gpt-4.1-mini-2025-04-14` 응답 및 토큰 사용량을 확인했다. 분석 계획이 안 나오는 재현 사례는 연결 단절이 아니라 응답의 UI 구조를 검증하는 단계에서 발생한다. 비밀 키 값은 출력하거나 기록하지 않았다.

## 확인 범위

- `app/server.py`의 `.env` 로딩 및 서버 시작 점검
- `app/core/llm_settings.py`의 공급자·키·모델·URL·타임아웃 해석
- `app/chat/turn_router.py`, `app/chat/dispatch.py`의 요청 분류·계획 생성 분기
- `app/planning/planner/`의 API 클라이언트, 응답 파싱, 보정, 재시도
- `app/planning/a2ui/refinement.py`의 자연어 수정 호출
- `app/execution/agent/fast_sql_agent.py`의 확정 후 SQL 에이전트 클라이언트
- 테스트 대역과 실제 SDK 응답 파서 사이의 차이

현재 설정은 provider=openai, model=gpt-4.1-mini, timeout=25초, 사용자 지정 base URL 없음, 키 존재, 동적 플래너 활성화이다. 플래너 모델은 별도 `AGENT2UI_PLANNER_MODEL`이 있으면 이를 우선 사용한다.

## 발견 사항

### P1 — 실제 구조화 응답 파싱에서 계획 전체가 탈락한다

위치: `app/planning/planner/dynamic_planner.py:83`, `app/planning/planner/models.py:58`, `app/planning/ui_models.py:118`.

플래너는 `with_structured_output(PlannerDraft, method="function_calling")`을 사용한다. 실제 SDK는 응답을 `PlannerDraft` 및 엄격한 `UiBlock`으로 먼저 파싱하므로 `_canonicalize_planner_output`과 기존 응답 보정 로직에 도달하기 전에 오류가 발생할 수 있다.

실제 “최근 60일간 고객별 배송 실패율이 높은 순서대로 보여줘.” 요청으로 재현했다.

1. API는 정상 응답했지만 블록 type에 등록 컴포넌트 대신 `group_by`, `metric`, `sort`를 반환했다.
2. 검증 피드백을 전달한 두 번째 응답은 type을 수정했지만 `default`라는 미등록 필드를 블록에 추가했다.
3. 두 차례 모두 파싱에 실패하여 `source=safe_fallback`으로 종료됐다.

이전 브라우저 검증에서도 `props.defaultValue`, `options[].default` 때문에 유사하게 실패했다. 선택값을 AnalysisPlan 한 곳에서 관리하는 원칙은 유지해야 한다. 금지 필드를 허용하거나 검증을 제거하는 방식으로 해결해서는 안 된다. 입력 스키마와 프롬프트를 정합화하고, 실제 실패 응답을 근거로 제한된 구조 복구 또는 응답 재생성을 검증해야 한다.

### P2 — 테스트가 실제 SDK 파싱 단계를 우회한다

위치: `tests/a2ui/test_dynamic_blueprint.py:26`.

가짜 Model의 `with_structured_output()`은 자기 자신을 반환하고, `invoke()`는 Python dict를 바로 돌려준다. 실제 LangChain의 `PlannerDraft` 파싱과 다른 경로다. 그래서 기존 테스트가 모두 통과해도 위 오류를 잡지 못한다.

실제 tool-call 메시지를 SDK 파서에 통과시키는 네트워크 없는 회귀 테스트가 필요하다. 미등록 type, 블록의 default, options의 default, props.defaultValue를 각각 포함하고, 검증 실패 후 수정 응답까지 검사하는 것이 적절하다. 정상 A/B/C 고정 응답 테스트만으로 실제 LLM 생성 안정성을 판단할 수 없다.

### P2 — API 장애와 계획 검증 오류의 사용자 안내가 구분되지 않는다

위치: `app/planning/planner/dynamic_planner.py:118`, `app/planning/planner/dynamic_planner.py:159`, `app/planning/a2ui/refinement.py:41`.

플래너는 호출·파싱·의미 검증 예외를 같은 재시도 경로로 처리하고, 최종적으로 “원하는 기준을 추가 조건에 적어 주세요”라는 계획을 만든다. 수정 경로도 호출 예외를 미해결 분석 조건으로 바꾼다. 인증 실패·호출 제한·타임아웃 등은 사용자가 분석 조건을 바꿔도 해결되지 않는다. 현재 환경에서 해당 API 장애를 일으키지는 않았으며 이 항목은 코드 경로 검토 결과다.

통신/인증 오류, 구조 파싱 오류, 분석 의미 검증 오류를 분리하고 사용자 안내 및 재시도 정책도 구분할 필요가 있다. 기존 실행 차단은 유지해야 한다.

## 실제 호출 결과

| 질문 | 실제 API 응답 | 최종 계획 | 호출 횟수 |
| --- | --- | --- | --- |
| 60일 동안 배송 실패한 총 건수는? | 정상 수신 | llm_dynamic_planner, UI Block 1개 | 2 |
| 최근 60일간 고객별 배송 실패율이 높은 순서대로 보여줘. | 두 응답 모두 정상 수신 | UI 구조 파싱 실패, safe_fallback | 2 |

각 API 응답은 약 2.5~5.8초였다. 첫 질문도 한 번의 추가 시도가 필요했다. 모델 응답이 존재한다는 사실과 계획 검증 통과 여부는 별도 지표로 봐야 한다.

이번 실제 호출 검증은 계획 생성 단계에 한정해 분석 SQL을 실행하지 않았다. 앞선 브라우저 검증에서는 60일 배송 실패 고유 주문 수 4건의 결과를 확인한 바 있다.

## 테스트 및 한계

- `python -m pytest tests -q`: 67개 통과.
- 실제 플래너 호출 2개 질문, 총 4회 API 응답 확인.
- 실제 응답 추적 자료: `.codex_tmp/llm-connection-review.json` (임시 로컬 파일).
- `/health`와 시작 로그는 설정·로컬 자원 점검이며 실제 API 인증 성공을 보장하지 않는다. 이번에는 실제 모델 응답으로 연결을 확인했다.
- 라우팅·자연어 수정·SQL 실행의 모든 분기를 이번 검토에서 실시간 호출로 전수 검사한 것은 아니다.
- 이 검토에서는 애플리케이션 동작 코드를 수정하지 않았다.
