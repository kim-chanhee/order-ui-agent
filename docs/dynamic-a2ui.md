# LLM 기반 동적 분석 계획 UI

LLM이 `AnalysisPlan`과 `UiBlock[]`을 함께 제안하고, 서버가 스키마·Semantic Catalog로 검증한 구성만 화면에 전달한다. 추천 선택값은 `AnalysisPlan`에만 저장한다. UI의 개수·순서·제목·설명·primary/advanced 배치는 LLM 응답을 따른다. A/B/C별 고정 분기나 고정 카드 묶음은 제품 코드에 추가하지 않았다.

## 이전 방식과 변경 방식

| 항목 | 이전 | 변경 |
|---|---|---|
| 백엔드 Block 구성 | 기본 기간·이벤트·지표·집계·비교·표시 입력을 자동 추가 | LLM Blueprint를 검증하며 일괄 추가하지 않음 |
| 주요 Block 수 | 최대 3개를 primary로 유지 | LLM의 section 유지, primary 개수 제한 없음 |
| 프론트엔드 | 지표·집계·기간·이벤트 4개 카드 고정 | 전달된 Block마다 카드를 만들고 한 번에 하나만 편집 |
| 제목·설명 | 카드 제목이 코드에 고정 | LLM의 label·description 유지 |
| 선택지 | 현재 선택값과 모델의 선택지도 병합 | 실제 스키마·등록 지표에 없는 선택지는 오류로 처리 |
| 세부 조건 | 고급 항목이 없어도 영역 표시 | advanced Block이 있을 때만 표시 |
| 지표 변경 | 대표 metric과 metrics의 중복 항목·unit 불일치 가능 | 기존 대표 지표의 복제만 동기화하고 독립 추가 지표는 유지 |
| 수정 | 직접 수정과 자연어 Patch에서 별도 검사 | `apply_plan_update()`를 공통 사용 |
| 월별 이벤트 비교 차트 | 월 라벨 중복으로 차트 비표시 가능 | 복수 차원 라벨을 결합해 구분 |

Block은 질문에 따라 2개, 4개, 5개 또는 그 이상이 될 수 있다. 전송 모델의 64개 상한은 비정상적으로 큰 응답을 막는 안전 한도이며 화면 템플릿이나 권장 개수가 아니다.

## 호출 흐름

1. `chat/dispatch.py` → 기존 Agent2UI 검토 분기 → `planning/service.py` → `planner/dynamic_planner.py`.
2. `planner/prompt.py`가 스키마와 서버 Catalog, 동적 Blueprint 규칙을 모델에 제공한다.
3. `planner/response.py`는 응답을 기존 모델로 검증한다. 잘못된 의미 필드·미등록 컴포넌트를 조용히 제거하지 않는다.
4. `planner/controls.py::_ensure_plan_controls()`가 순서와 문구를 보존하며 선택지·지표 의미를 검사한다. 실패하면 재시도하고 확인이 필요한 사유를 표시한다.
5. `a2ui/review.py`가 정확한 계획과 UI를 revision과 함께 저장한다.
6. `static/js/a2ui/plan/plan-renderer.js`가 전달받은 Block만 렌더링한다. 숨겨진 이벤트·중복 제거 조건은 계획과 최종 미리보기에 남는다.
7. 직접 수정 `/api/review/update`와 기존 채팅창의 `/api/review/refine`은 공통 `apply_plan_update()`로 권한·종속값·선택지를 검증한다. 기간·집계 변경은 다른 조건을 새로 생성하지 않는다.
8. 서버가 종속 선택지를 다시 발급하고 revision을 올린다. 오래된 revision 확정은 기존처럼 409다.
9. 확정 `/api/review/confirm` 이후에만 분석 SQL 실행 경로로 넘어간다. 계획 준비를 위한 스키마 탐색·기준일 MAX 조회는 기존처럼 유지한다. Baseline의 기존 실행 진입점과 워커 구조는 유지했다.

검토 중인 초안의 자연어 수정은 기존 프론트엔드의 `refineFromChat`이 처리한다. 실행 완료된 결과를 참조하는 새 후속 분석은 `turn_router.py`의 기존 경로를 유지해 새 검토 초안을 만든다. 이미 실행된 결과 기록을 덮어쓰지 않는다.

## Catalog 및 의미 검증

- 지표 종류·집계 기준·식별자·이벤트는 실제 스키마를 바탕으로 발급한다. 모델의 현재 선택값 자체를 유효성의 근거로 사용하지 않는다.
- `day`, `month`, `year`는 시간 컬럼이 확인될 때만 제안한다. 월별 SQL도 실제 월 버킷을 사용하는지 AST로 검사한다.
- 수치 필드가 없으면 합계·평균·최솟값·최댓값을 제공하지 않는다. 식별자와 시간 컬럼을 일반 수치 집계 필드로 취급하지 않는다.
- 등록된 비율은 `MetricSpec.semantic_id`로 참조한다. 현재 기본 설정에는 `shipment_failure_rate`를 추가했다.
- 이 지표는 **선택 기간에 배송 이력이 있는 고유 주문 중 배송 실패 이력이 있는 고유 주문의 비율**이다. 분자는 `failed_delivery_orders`, 분모는 `shipment_orders`다. 상품별 분해처럼 등록된 정의가 지원하지 않는 집계는 차단한다.
- 비율 SQL은 조건부 `COUNT(DISTINCT CASE WHEN ... THEN order_id END)`와 전체 모집단 `COUNT(DISTINCT order_id)`, 실수 나눗셈, 0분모 방지를 확인한다. 실패 이벤트만 남겨 분모를 좁힌 쿼리는 거절한다.
- 필드 편집 권한을 우회한 변경은 거절한다. 서버가 계산한 종속 변경과 정확히 일치하는 unit·지표 복제·모집단 변경만 허용한다.
- 자연어 Patch는 스키마가 지원하는 숨겨진 필드를 명시적으로 변경할 수 있다. 직접 UI 요청이 임의로 숨겨진 조건을 바꾸는 것은 허용하지 않는다.
- 별도 자연어 입력창은 추가하지 않았다. 구조화 실패도 기존 채팅창에서 확인하도록 안내한다.

## 주요 변경 파일

| 파일 | 역할 |
|---|---|
| `planning/analysis_models.py`, `planning/ui_models.py` | 기존 모델 확장: semantic_id, 서버 UI 상태, 전송 한도·단일 선택값 원칙 |
| `planning/option_catalog.py` | 타입·테이블 연결 근거·기간 버킷·등록 지표 선택지 |
| `planning/planner/controls.py`, `prompt.py`, `response.py`, `dynamic_planner.py` | 동적 Blueprint 보존, 모델 지침, 엄격한 응답 검증·확인 사유 |
| `planning/service.py` | 서버 Catalog를 기존 UiPlan에 연결 |
| `planning/a2ui/validator.py`, `refinement.py`, `models.py`, `review.py` | 공통 수정·종속값·Patch·선택지 재발급 |
| `routes/a2ui/review.py` | 서버 발급 스키마를 통한 직접 수정·확정 검증 |
| `execution/sql/sql_contract.py` | 월별 집계·등록 실패율의 SQL 계약 검사 |
| `Data/docs/analysis_semantics.json` | 배송 실패율 Semantic Metric 정의 |
| `static/js/a2ui/plan/plan-renderer.js`, `plan-validation.js`, `plan-labels.js`, `plan-sentence.js` | 가변 카드, 실시간 종속값·검증·미리보기·월별 이름 |
| `static/js/results/result-renderer.js`, `static/a2ui/review.css` | 복수 차원 차트 및 카드 편집 배치 |
| `static/js/`의 모듈 import와 `templates/index.html` | 같은 버전(`dynamic-blueprint-v1`)으로 캐시 갱신 |
| `tests/a2ui/test_dynamic_blueprint.py`, `tests/js/review-plan.test.js` | 생성·수정·권한·SQL·렌더링 회귀 검증 |

## 검증

최종 자동 검증: Python 67개, JavaScript 8개 통과(총 75개). Python 검증 중 외부 네트워크 연결을 차단했다.

외부 모델 API 없이 대체 LLM 응답으로 실제 계획 생성/검증 파이프라인을 테스트한다. 대체 응답에는 A/B/C뿐 아니라 7개 primary Block 구성과 잘못된 선택지·미등록 타입·잘못된 비율 정의도 포함한다.

```sh
.venv/bin/python -m pytest tests -q
node --test tests/js/review-plan.test.js
```

브라우저에서는 로컬 데이터와 대체 LLM을 사용해 A 2개·B 4개·C 5개 카드, A의 기간 직접 수정 및 채팅 Patch, 확정 후 SQL 조회, B의 등록 실패율, C의 월별 복수 이벤트 차트를 확인했다. 확인용 서버는 8004번 포트이며 제품의 실제 모델 연결 서버와 구분한다.

## 제약

- 실제 LLM 응답 품질·성공률·지연은 API를 사용하지 않아 검증하지 않았다. 예시별 개수는 대체 모델 응답을 실제 파이프라인이 보존하는지 확인한 결과다.
- 기본 등록 비율은 배송 실패율 하나다. 다른 비율과 평균 배송 시간은 검증된 데이터·관계·정의가 추가되어야 하며 임의로 계산하지 않는다.
- 등록 비율 SQL 검사는 지원하는 조건부 집계 형식에 보수적으로 제한한다. 동등한 다른 CTE/대수식도 거절될 수 있으며 SQL 에이전트가 안내된 형식으로 다시 작성해야 한다.
- 테이블 연결 후보는 공유되는 업무 식별자 중심으로 보수적으로 구성한다. 같은 의미의 컬럼명이 다르거나 복잡한 다대다 관계는 Catalog/의미 정의 확장이 필요할 수 있다.
- 일반 SQL 계약 검사는 완전한 관계 대수 동치 증명이 아니다. 기존 스키마·기간·지표·그룹·정렬·필터 필드 검사에 등록 비율과 시간 버킷 검사를 추가한 것이다.
- 차트는 기존의 단일 수치 막대 차트이며 앞 12개 행만 표시한다. 월·이벤트는 복합 라벨로 구분하며 다중 시리즈 꺾은선 차트는 추가하지 않았다.
