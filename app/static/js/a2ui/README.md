# `app/static/js/a2ui` · 계획 검토 전용 프론트엔드

> **한눈에 보기** · 계획 화면의 현재 값과 되돌리기 기준을 관리합니다. 저장·추가 수정·확정 동작을 연결합니다.

**기본 흐름:** 계획 받기 → 편집 상태 관리 → 저장·수정·확정

계획 화면의 설치·표시·추가 조건·확정 요청과 편집 상태를 관리합니다.

[계획 검토 화면 예시](../../../../README.md#어떤-문제를-해결하나요)

## 주요 파일

| 파일 | 역할 |
|---|---|
| [api.js](api.js) | 계획 수정(refine)·확정(confirm) 요청 전송. |
| [review-controller.js](review-controller.js) | 계획 표시 → 조건 추가 → 확정 실행의 사용자 동작 조정. |
| [state.js](state.js) | 검토 계획·처음 계획·현재 화면·확정 계획의 편집 상태. |
| [surfaces.js](surfaces.js) | 서버 화면 정의를 UiPlan으로 변환하고 검토 화면 설치·표시. |

## 하위 폴더 안내

| 폴더 | 역할 |
|---|---|
| [plan/](plan/README.md) | 분석 계획 편집 UI |

## 핵심 개념과 동작

스냅샷은 **특정 시점의 계획을 복사해 둔 값**입니다. 현재 편집값, 처음 값, 서버에 저장한 값을 구분합니다.

카드 저장 뒤에도 처음 값은 유지해 되돌리기에 사용합니다. 자연어 수정으로 새 추천 계획이 오면 `resetInitial`로 처음 값의 기준을 새로 잡습니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `createReviewController` | 활성 화면·저장 경합·확정 요청 관리 | UI 상태 기계 |
| `installPlanSurface` | 계획·스냅샷·화면 데이터 동기화 | 불변 사본 |
| `buildUiPlanRequest` | 서버 요청용 계획 envelope 구성 | 요청 정규화 |

### 핵심 코드: installPlanSurface()

저장 결과가 기존 최초 스냅샷을 무조건 덮어쓰지 않도록 합니다.

**동작:** Surface를 복사·검증하고 같은 plan_id인지 확인해 resetInitial 또는 새 계획일 때만 최초 스냅샷을 교체합니다.

**설계:** 명시적 상태 설치와 스냅샷 분리입니다. 카드 저장 뒤에도 처음 제시된 계획과의 차이·되돌리기 근거를 보존합니다.

**예:** 같은 plan_id의 카드 저장은 savedPlanSnapshot만 새로 만들고 resetInitial=true는 최초 기준도 바꿉니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/static/js/a2ui/surfaces.js](surfaces.js#L39). 아래는 실제 코드의 39~54행 발췌이며 앞뒤는 생략했습니다.

```javascript
export function installPlanSurface(surface, { resetInitial = false } = {}) {
  const currentSurface = clone(validateSurface(surface));
  const uiPlan = uiPlanFromSurface(currentSurface);
  currentSurface.data_model.analysis_plan = uiPlan.analysis_plan;
  currentSurface.data_model.ui_state = uiPlan.ui_state;
  uiPlan.analysis_plan = currentSurface.data_model.analysis_plan;
  uiPlan.ui_state = currentSurface.data_model.ui_state;
  const samePlan = reviewState.currentSurface?.plan_id === currentSurface.plan_id;
  reviewState.currentSurface = currentSurface;
  reviewState.currentUiPlan = uiPlan;
  reviewState.currentPlan = currentSurface.data_model.analysis_plan;
  if (resetInitial || !samePlan) reviewState.initialPlanSnapshot = clone(currentSurface.data_model.analysis_plan);
  reviewState.savedPlanSnapshot = clone(currentSurface.data_model.analysis_plan);
  return uiPlan;
}

```

</details>

### 다른 기능과 연결되는 순서

review-controller는 update/refine/confirm API를 호출하고 새 계획 Surface를 설치합니다. 저장 중에는 updating으로 중복 동작을 막고, 확정 응답은 run_id를 확인한 뒤 결과 화면으로 전환합니다.

### 확인한 범위와 한계

스냅샷·단일 활성 컨트롤러는 브라우저 메모리 상태입니다. 네트워크 실패·새 탭·오래된 화면의 충돌은 서버 revision 검사를 함께 사용해야 하며 DOM 전체 동작을 순수 함수 테스트가 보장하지 않습니다.

관련 검증: [review-plan.test.js](../../../../tests/js/review-plan.test.js), [test_review_update.py](../../../../tests/a2ui/test_review_update.py).

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../../README.md)
- [프로젝트 소개](../../../../README.md)
