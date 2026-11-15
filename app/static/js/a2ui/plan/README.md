# `app/static/js/a2ui/plan` · 분석 계획 편집 UI

> **한눈에 보기** · 서버가 정한 편집 항목을 화면에 표시하고, 사용자가 바꾼 값을 계획에 반영합니다. 지표를 바꾸면 연관된 항목도 함께 맞춥니다.

**기본 흐름:** 계획·화면 정의 → 입력 UI → 값·연관 항목 갱신 → 확정 전 검사

분석 계획을 정규화하고 입력 블록·안내 문장·변경 차이·필수값 검사를 구성합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [condition-evaluator.js](condition-evaluator.js) | UI 블록의 표시·필수 입력 조건 평가. |
| [plan-diff.js](plan-diff.js) | 최초 계획과 수정 계획의 변경 값·필드 계산. |
| [plan-labels.js](plan-labels.js) | 단위·지표·기간·집계 기준의 한글 표시 이름과 조사 처리. |
| [plan-normalizer.js](plan-normalizer.js) | 계획·UI 블록·집계 기준·필드 간 의존성 정규화. |
| [plan-renderer.js](plan-renderer.js) | 계획 카드·입력 블록 렌더링과 수정·확정 요청 데이터 구성. |
| [plan-sentence.js](plan-sentence.js) | 현재 계획의 분석 의미를 사용자 안내 문장으로 표현. |
| [plan-validation.js](plan-validation.js) | 확정 전 필수값·미해결 조건·계획 유효성 검사. |

## 카드 검토 화면

결과 지표(다중 지표 포함), 집계 기준, 분석 기간, 대상 이벤트를 네 카드로 묶습니다.
선택한 카드의 서버 발급 입력만 펼치고 나머지 입력은 세부 조건에서 제공합니다.
`변경 저장`은 서버 검증과 revision 갱신을 수행하며, 실행 버튼도 미저장 변경을 먼저 저장합니다.
최초 추천 스냅샷과 마지막 저장 스냅샷을 분리해 변경 표시와 초기화를 유지합니다.
자연어 수정은 공통 채팅창에서 기존 refine API로 전달하고, 새 추천 이후에는 그 계획을 초기화 기준으로 삼습니다.

## 핵심 개념과 동작

계획 렌더러는 서버의 블록 순서·라벨·section을 사용하고 값은 AnalysisPlan에서 읽습니다. 지표 변경은 단순 필드 대입 이후 분자·분모·단위·대표 지표 복사본 같은 의존 필드를 갱신합니다. diff는 정규화된 최초 계획과 현재 계획을 비교해 관찰용 변경 경로를 계산합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `renderPlanCard` | 문장·편집 카드·저장/확정 UI 구성 | 선언형 UI |
| `applyLocalPlanEdit` | 편집값과 지표 종속값 정리 | 의존성 정규화 |
| `evaluateCondition` | all/any와 비교 연산 평가 | 재귀 조건 트리 |
| `diffPlans` | source/confidence 등을 제외한 조건 diff | 재귀 구조 비교 |
| `validatePlanForConfirmation` | 누락·의미·조회 불가 조건 검사 | 클라이언트 사전 검증 |

### 핵심 코드: compareValue()

사용자 편집을 필드별 전후 값으로 기록합니다.

**동작:** 배열은 전체 값으로 비교하고 객체는 키 합집합을 정렬해 재귀 순회하며 원시값은 직접 비교합니다.

**설계:** 구조 diff와 메타데이터 제외 규칙입니다. 조건 변화와 단순 출처·신뢰도 갱신을 구분합니다.

**예:** limit 5→10은 {field:"limit",before:5,after:10}이고 source만 바뀌면 제외됩니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/static/js/a2ui/plan/plan-diff.js](plan-diff.js#L18). 아래는 실제 코드의 18~34행 발췌이며 앞뒤는 생략했습니다.

```javascript
function compareValue(before, after, path, diffs) {
  if (path && IGNORED_KEYS.has(path.split(".").at(-1))) return;
  if (Array.isArray(before) || Array.isArray(after)) {
    if (JSON.stringify(before || []) !== JSON.stringify(after || [])) diffs.push({ field: path, before, after });
    return;
  }
  if (isObject(before) || isObject(after)) {
    const keys = new Set([...Object.keys(before || {}), ...Object.keys(after || {})]);
    for (const key of [...keys].sort()) {
      if (IGNORED_KEYS.has(key)) continue;
      compareValue(before?.[key], after?.[key], path ? `${path}.${key}` : key, diffs);
    }
    return;
  }
  if (before !== after) diffs.push({ field: path, before, after });
}

```

</details>

### 핵심 코드: applyLocalPlanEdit()

날짜·지표 편집과 종속 상태를 함께 갱신합니다.

**동작:** 기간 변경은 anchor를 초기화하고 지표 종류에 따라 등록 비율 또는 고유 건수 정의를 반영합니다.

**설계:** 카탈로그 기반 의존성 처리입니다. 분모·단위가 이전 지표의 값으로 남는 모순을 줄입니다.

**예:** count로 전환하면 distinct=True를 설정하며 독립적인 추가 지표는 그대로 보존합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/static/js/a2ui/plan/plan-renderer.js](plan-renderer.js#L223). 아래는 실제 코드의 223~241행 발췌이며 앞뒤는 생략했습니다.

```javascript
if (m.kind === "ratio") {
  const entries = Object.entries(catalog?.semantic_metrics || {}).filter(([,d]) => (d.kind || "ratio") === "ratio");
  const selected = entries.find(([id]) => id === m.semantic_id) || (kindChanged && entries.length === 1 ? entries[0] : null);
  if (selected) {
    const [id,d] = selected;
    if (kindChanged && JSON.stringify(plan.event_types || []) === JSON.stringify([d.numerator_event])) plan.event_types = [...d.population_events];
    Object.assign(m,{semantic_id:id,field:d.field,numerator:d.numerator,denominator:d.denominator,unit:d.label,distinct:true});
  }
} else if (m.kind === "count") {
  if (kindChanged) Object.assign(m,{semantic_id:null,numerator:null,denominator:null});
  const units = {order_id:"order",customer_id:"customer",courier_id:"courier",product_id:"product",item_id:"item",event_id:"event",employee_id:"employee",package_id:"package"};
  if (units[m.field]) m.unit = units[m.field];
  m.distinct = true;
} else if (kindChanged) {
  Object.assign(m,{semantic_id:null,numerator:null,denominator:null,distinct:null});
  if (m.kind === "rows" || !(catalog?.numeric_fields || []).some((o) => o.value === m.field)) Object.assign(m,{field:null,unit:null});
}
if (path === "metric.kind" && !value) plan.metric = null;
plan.metrics = (plan.metrics || []).map((metric) => JSON.stringify(metric) === JSON.stringify(previous) ? clone(plan.metric) : metric).filter(Boolean);
```

</details>

### 다른 기능과 연결되는 순서

입력 위젯 update → applyLocalPlanEdit → 필수값 재계산 → 다시 그리기 순서입니다. buildConfirmPayload는 diff·Surface ID·revision을 묶고 서버는 다시 동일한 편집 의미를 검증합니다. 브라우저 계산은 편집 편의를 위한 것이며 서버 권위 값을 대체하지 않습니다.

### 확인한 범위와 한계

JS와 Python의 조건 평가가 모든 자료형에서 완전히 같은 것은 아닙니다. 배열·빈 객체·형 변환 등에 경계가 있으므로 서버 검증이 최종 기준입니다. 프론트 diff는 신뢰된 보안 감사 로그가 아닙니다.

관련 검증: [review-plan.test.js](../../../../../tests/js/review-plan.test.js), [test_dynamic_blueprint.py](../../../../../tests/a2ui/test_dynamic_blueprint.py).

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../../../README.md)
- [프로젝트 소개](../../../../../README.md)
