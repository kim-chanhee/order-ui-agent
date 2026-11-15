# README 기술 문서 개선 결과

이번 작업은 로컬 소스를 기준으로 기존 README 41개를 보완하고 README 4개를 새로 작성했습니다. 이 보고서는 별도 문서입니다. GitHub 반영 대상은 README 44개와 이 보고서이며, 공개 노트북이 없는 `Data/order_analysis/README.md`는 로컬에만 둡니다.

## 변경 범위

최상위 README는 문제 정의·공통 처리 흐름·기술 스택·상세 문서 탐색·실행과 테스트 안내를 제공합니다. 하위 문서는 핵심 기술, 주요 함수 표, 실제 소스 발췌, 목적·동작 원리·기술적 특징·구현 근거·입출력 예, 연결 관계와 검증 한계를 설명합니다.

### 보완한 기존 README

- [Data/A2UI/README.md](../Data/A2UI/README.md)
- [Data/README.md](../Data/README.md)
- `Data/order_analysis/README.md` (로컬 전용)
- [README.md](../README.md)
- [app/README.md](../app/README.md)
- [app/a2ui/README.md](../app/a2ui/README.md)
- [app/chat/README.md](../app/chat/README.md)
- [app/chat/a2ui/README.md](../app/chat/a2ui/README.md)
- [app/core/README.md](../app/core/README.md)
- [app/data/README.md](../app/data/README.md)
- [app/execution/README.md](../app/execution/README.md)
- [app/execution/a2ui/README.md](../app/execution/a2ui/README.md)
- [app/execution/agent/README.md](../app/execution/agent/README.md)
- [app/execution/baseline/README.md](../app/execution/baseline/README.md)
- [app/execution/results/README.md](../app/execution/results/README.md)
- [app/execution/semantics/README.md](../app/execution/semantics/README.md)
- [app/execution/sql/README.md](../app/execution/sql/README.md)
- [app/execution/tools/README.md](../app/execution/tools/README.md)
- [app/experiment/README.md](../app/experiment/README.md)
- [app/experiment/a2ui/README.md](../app/experiment/a2ui/README.md)
- [app/planning/README.md](../app/planning/README.md)
- [app/planning/a2ui/README.md](../app/planning/a2ui/README.md)
- [app/planning/planner/README.md](../app/planning/planner/README.md)
- [app/routes/README.md](../app/routes/README.md)
- [app/routes/a2ui/README.md](../app/routes/a2ui/README.md)
- [app/runtime/README.md](../app/runtime/README.md)
- [app/runtime/a2ui/README.md](../app/runtime/a2ui/README.md)
- [app/static/README.md](../app/static/README.md)
- [app/static/a2ui/README.md](../app/static/a2ui/README.md)
- [app/static/js/README.md](../app/static/js/README.md)
- [app/static/js/a2ui/README.md](../app/static/js/a2ui/README.md)
- [app/static/js/a2ui/plan/README.md](../app/static/js/a2ui/plan/README.md)
- [app/static/js/components/README.md](../app/static/js/components/README.md)
- [app/static/js/components/a2ui/README.md](../app/static/js/components/a2ui/README.md)
- [app/static/js/modes/README.md](../app/static/js/modes/README.md)
- [app/static/js/results/README.md](../app/static/js/results/README.md)
- [app/static/js/results/a2ui/README.md](../app/static/js/results/a2ui/README.md)
- [app/static/js/surfaces/README.md](../app/static/js/surfaces/README.md)
- [app/templates/README.md](../app/templates/README.md)
- [models/README.md](../models/README.md)
- [tests/execution/README.md](../tests/execution/README.md)

### 새로 작성한 README

- [scripts/README.md](../scripts/README.md)
- [tests/README.md](../tests/README.md)
- [tests/a2ui/README.md](../tests/a2ui/README.md)
- [tests/js/README.md](../tests/js/README.md)

## 폴더별 핵심 기술과 코드 발췌

각 행의 문서에서 개념 설명과 코드별 해설을 함께 확인할 수 있습니다. 발췌는 실제 소스의 연속된 구간이며 앞뒤 생략 여부와 원본 경로를 표시했습니다. 들여쓰기는 문서 표시를 위해 정리했습니다.

| 문서 | 추가한 기술·설계 개념 | 발췌한 함수·코드 |
|---|---|---|
| [Data/A2UI/README.md](../Data/A2UI/README.md) | 척도 점수 전처리 · 연구 설계 · 선형 모형 · 모형 진단 · 재현 근거 | `fit_anova`, `test_residual_assumptions` |
| [Data/README.md](../Data/README.md) | 메타데이터 추출 · 도메인 격리 | `create_profile` |
| `Data/order_analysis/README.md` (로컬 전용) | SQLite · pandas · Schema introspection · 집계 단위 · 참조 무결성 | `query` |
| [app/README.md](../app/README.md) | FastAPI lifespan · 오류 경계 · Uvicorn | `validation_error_handler` |
| [app/a2ui/README.md](../app/a2ui/README.md) | Pydantic 전송 모델 · 결과 어댑터 · 선언형 UI · 권위 상태 · Capability fallback | `_supported_type` |
| [app/chat/README.md](../app/chat/README.md) | 의도 라우팅 · 서비스 분기 · Bounded context · SHA-256 · 대화 문맥 | `_decision_issues`, `context_record_id` |
| [app/chat/a2ui/README.md](../app/chat/a2ui/README.md) | 계획 검토 경계 | `review_response` |
| [app/core/README.md](../app/core/README.md) | JSON Schema / Tool Calling · 공통 모델 어댑터 · ContextVar · 원자적 설정 적용 · Fail fast | `structured_output_options`, `apply_data_profile` |
| [app/data/README.md](../app/data/README.md) | 환경 설정 우선순위 · 조기 실패 · 경로 안정성 | `_resolve_default_database_path` |
| [app/execution/README.md](../app/execution/README.md) | 공통 실행 계약 · Temporal anchor · 실행 오케스트레이션 · 결과 envelope | `execute_schema_question` |
| [app/execution/a2ui/README.md](../app/execution/a2ui/README.md) | 계획 실행 경계 · 중복 payload 일관성 | `validate_confirmed_plan` |
| [app/execution/agent/README.md](../app/execution/agent/README.md) | ReAct / Tool Calling · 휴리스틱 선택 | `_run_react_tool_loop`, `_select_best_success` |
| [app/execution/baseline/README.md](../app/execution/baseline/README.md) | 화면 없는 계획 실행 · 공유 planner · 공통 실행 모델 | `baseline_response_payload` |
| [app/execution/results/README.md](../app/execution/results/README.md) | 결과 계약 · 계약 예외 · 실패 응답 모델 | `validate_result_contract` |
| [app/execution/semantics/README.md](../app/execution/semantics/README.md) | 설정 캐시 무효화 · 의미 grounding · CTE 역할 계보 · Temporal anchor · 정의 기반 지표 | `validate_relative_time_sql`, `try_registered_metric` |
| [app/execution/sql/README.md](../app/execution/sql/README.md) | SQLGlot Scope · 실행 계약 · DB 권한 경계 | `physical_tables_from_tree`, `create_read_only_connection` |
| [app/execution/tools/README.md](../app/execution/tools/README.md) | 검사 후 실행 · 실행 게이트 · BFS | `execute_query`, `_shortest_path` |
| [app/experiment/README.md](../app/experiment/README.md) | 트랜잭션 · 상태 기계 · 상태 전이 게이트 · 멱등 기록 · 제한적 자동 평가 · 측정 로그 | `complete_current_task`, `score_result_accuracy` |
| [app/experiment/a2ui/README.md](../app/experiment/a2ui/README.md) | 관찰 로그 어댑터 | `record_confirm_interaction` |
| [app/planning/README.md](../app/planning/README.md) | Pydantic · 선언형 UI · 문맥 기반 계획 · 재귀 조건 평가 · Schema grounding | `compute_missing_fields` |
| [app/planning/a2ui/README.md](../app/planning/a2ui/README.md) | 구조화 패치 · LLM Structured Output · 편집 권한 검증 · 의존성 정규화 · 동적 카탈로그 | `apply_plan_update`, `_filter_id` |
| [app/planning/planner/README.md](../app/planning/planner/README.md) | Structured Output · 정규화 · 출처 추적 · Grounded blueprint · 실패 경계 | `plan_dynamic_analysis`, `_ensure_plan_controls` |
| [app/routes/README.md](../app/routes/README.md) | FastAPI 라우트 · API 오류 계약 · Pydantic 요청 모델 · 실행 증거 구분 | `_should_record_execution_result` |
| [app/routes/a2ui/README.md](../app/routes/a2ui/README.md) | 낙관적 동시성 · 신뢰 경계 · 원자적 변경 · 구조화 패치 · 최종 실행 경계 | `_validate_surface_revision` |
| [app/runtime/README.md](../app/runtime/README.md) | 프로세스 격리 · 취소 제어 · SQLite 영속성 · 신뢰 경계 | `run_cancelable`, `get_similar_sql_examples` |
| [app/runtime/a2ui/README.md](../app/runtime/a2ui/README.md) | 조건부 UPDATE · 서버 권위 상태 · 동시성 오류 · 프로세스 경계 | `save_plan_surface` |
| [app/static/README.md](../app/static/README.md) | 비동기 상태 제어 · 선언형 렌더링 · 컨트롤러 분리 · HTML 주입 억제 | `export function createElement(` |
| [app/static/a2ui/README.md](../app/static/a2ui/README.md) | CSS Grid · 접근성 상태 · 상태 기반 스타일 | `.plan-choice-chips` |
| [app/static/js/README.md](../app/static/js/README.md) | 비동기 경합 제어 · 응답 일관성 · fetch 어댑터 · Prototype pollution 방어 | `export function pathParts(` |
| [app/static/js/a2ui/README.md](../app/static/js/a2ui/README.md) | UI 상태 기계 · 불변 사본 · 요청 정규화 | `export function installPlanSurface(` |
| [app/static/js/a2ui/plan/README.md](../app/static/js/a2ui/plan/README.md) | 선언형 UI · 의존성 정규화 · 재귀 조건 트리 · 재귀 구조 비교 · 클라이언트 사전 검증 | `function compareValue(`, `export function applyLocalPlanEdit(` |
| [app/static/js/components/README.md](../app/static/js/components/README.md) | Registry pattern · 동적 디스패치 · Capability 목록 | `export function renderComponent(` |
| [app/static/js/components/a2ui/README.md](../app/static/js/components/a2ui/README.md) | 컴포넌트 등록 · Controlled input · 선언형 선택지 · 복합 입력 | `export function renderSelectComponent(` |
| [app/static/js/modes/README.md](../app/static/js/modes/README.md) | Strategy pattern · 모드 어댑터 · 입력 정리 · 형식 검증 | `export function normalizeParticipantId(` |
| [app/static/js/results/README.md](../app/static/js/results/README.md) | Adapter · 표 정보 배치 · 다차원 라벨 · 차트 적합성 | `export function partitionTableColumns(` |
| [app/static/js/results/a2ui/README.md](../app/static/js/results/a2ui/README.md) | 선택적 UI · 비활성 확장 지점 | `export function renderFollowUpActions(` |
| [app/static/js/surfaces/README.md](../app/static/js/surfaces/README.md) | 전송 계약 · 런타임 디스패치 | `export function validateSurface(` |
| [app/templates/README.md](../app/templates/README.md) | 정적 셸 제공 · 초기화 캐시 | `<!doctype html>` |
| [models/README.md](../models/README.md) | 호환 HTTP 클라이언트 · 전송 호환성 | `resolve_agent_llm_settings` |
| [scripts/README.md](../scripts/README.md) | 스키마 introspection · 재현 가능한 입력 · 공개용 변환 · 오프라인 기준 비교 · 서비스 smoke test | `create_profile`, `public_content` |
| [tests/README.md](../tests/README.md) | 테스트 의존성 주입 · 격리된 검증 · JavaScript 단위 테스트 | `test_invalid_profile_does_not_partially_replace_environment` |
| [tests/a2ui/README.md](../tests/a2ui/README.md) | 프롬프트 회귀 검증 · 문맥 압축 | `test_catalog_keeps_all_supported_values_and_types` |
| [tests/execution/README.md](../tests/execution/README.md) | 통합 테스트 도우미 · 매개변수화 테스트 | `test_physical_tables_respect_query_scopes_without_changing_tree` |
| [tests/js/README.md](../tests/js/README.md) | node:test · 결과 표시 계약 · 상태 일관성 | `test('constant zero metrics` |

## 일치 여부와 검증 결과

- 코드 발췌 57개를 현재 Python·JavaScript·HTML·CSS 및 노트북 셀 원문과 대조했습니다. 문서에 발췌가 실제로 포함되어 있는지도 확인했습니다.
- 작업 전 기록한 비문서 파일의 SHA-256 비교에서 변경이 없었습니다. Python·JavaScript 실행 로직, API, 테스트, DB 구조를 수정하지 않았습니다. 작업 이전부터 존재한 로컬 변경은 그대로 두었습니다.
- Python 테스트: **142개 통과**. JavaScript 테스트: **10개 통과**.
- README 45개의 상대 링크 대상이 존재하는지 확인했습니다. 외부 사이트 전체의 접속 상태와 GitHub 게시 후 렌더링은 이번 검증에 포함하지 않았습니다.
- Markdown 표 120개의 열 구성을 검사했습니다. GFM 렌더러로 문서 45개를 변환하고, 브라우저에서 코드 블록 71개와 Mermaid 다이어그램 5개의 렌더링을 확인했습니다. 모든 화면 크기의 시각 검사를 수행한 것은 아닙니다.
- 다이어그램의 개념 흐름과 실제 함수 호출 관계를 구분했습니다. 개념 흐름은 외부 호출 추적 결과로 표현하지 않았습니다.

## 확인한 구현 경계와 추가 권고

- SQL 계약 검증은 지원하는 AST 표현을 검사합니다. 임의의 중첩 질의와 모든 논리식의 의미적 동등성을 증명하지 않습니다.
- SQL Agent의 시간 확인과 런타임 워커의 프로세스 종료를 구분했습니다. 취소·시간 초과·동시 요청의 전체 조합은 추가 검증이 필요합니다.
- Node 테스트는 순수 함수 검증입니다. 질문 → 계획 수정 → 확정 → 결과의 실제 브라우저 자동 검증은 별도 과제입니다.
- `followUpPrompts()`는 현재 빈 목록을 반환하며, 서버에서 허용하는 clarification Surface와 클라이언트 렌더링 분기 사이에도 지원 범위 차이가 있습니다. 구현된 기능처럼 설명하지 않았습니다.
- 실제 모델의 해석 정확도·성능과 사용자 경험 개선 효과는 자동 테스트 통과만으로 입증하지 않습니다. 평가셋·측정 조건·실패 예시를 따로 정리할 수 있습니다.
- 비공개 참가자·설문·행동 로그는 실행하거나 공개하지 않았습니다. 연구 노트북의 전체 실행과 통계 결과 재생성은 이번 작업에 포함하지 않았습니다.
- `Data/order_analysis/`는 로컬 자료를 기준으로 설명했습니다. 공개 저장소에 게시할 때에는 노트북 제공 범위와 링크를 별도로 점검해야 합니다.
- 소스가 바뀌면 코드 발췌와 행 번호도 갱신해야 합니다. 향후 발췌 일치·문서 링크·Mermaid 검사를 CI에 추가할 수 있습니다.

구조 변경이나 실행 코드 리팩터링 없이 문서만 보완했습니다.


## 가독성 보완

후속 요청에 따라 README 45개의 읽기 구성을 보완했습니다.

- 각 모듈 앞에 쉬운 요약과 기본 처리 순서를 추가했습니다.
- 메인 README에 읽는 순서, 대표 질문의 처리 예시, 용어표를 추가했습니다.
- AST·SQL 계약·Surface·revision·워커 등 주요 용어를 해당 문서에서 짧게 풀었습니다.
- 코드 해설을 먼저 배치하고, 원본 코드 57개는 펼쳐서 볼 수 있도록 바꿨습니다. 기술적 특징과 구현 이유는 설계 설명으로 묶었습니다.
- README의 상대 링크, 코드 펼치기 57개, Mermaid 5개를 확인했습니다. 기존 코드 블록 내용과 실행 소스 159개에 변경이 없음을 대조했습니다.

이번 보완은 문서만 변경했습니다. 기존 테스트를 다시 실행하지 않았으며, 앞 절의 테스트 결과는 최초 기술 문서 개선 때 확인한 결과입니다. 공개 대상 문서는 GitHub에 함께 반영하며, `Data/order_analysis/README.md`는 로컬에만 둡니다.


## 다섯 단계로 구성 통일

후속 요청에 따라 하위 README 44개를 역할 → 해결하려는 문제 → 핵심 기술 → 핵심 함수와 실제 코드 → 구현 결과와 한계 순서로 재배치했습니다. 최상위 README의 개요 구성은 유지했습니다.

- 각 폴더가 방지하려는 문제와 현재 구현 동작을 짧게 추가했습니다.
- 파일 목록과 참고 문서는 마지막 펼치기에 모았습니다.
- 코드 발췌 57개와 기존 코드 블록 내용을 보존했습니다.
- 문서 44개의 다섯 단계 구성, 상대 경로, 제목 링크 22개, 코드 펼치기, Mermaid 5개를 확인했습니다.
- 실행 소스 159개의 해시가 작업 전과 같았습니다. 문서 재배치만 수행하여 기능 테스트는 다시 실행하지 않았습니다.

구성 통일 변경도 GitHub에 반영합니다. 공개 대상은 하위 README 43개와 이 보고서이며, `Data/order_analysis/README.md`는 로컬에만 둡니다.
