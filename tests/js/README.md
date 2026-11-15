# 브라우저 순수 함수 회귀 검증

> **한눈에 보기** · 계획 편집과 결과 표시를 돕는 JavaScript 함수를 검사합니다. 실제 브라우저를 띄우는 테스트는 아닙니다.

**기본 흐름:** 입력 데이터 준비 → 함수 실행 → 값·표시 정보 비교

## 핵심 개념과 동작

Node 내장 node:test와 assert로 순수 함수 중심의 프론트엔드 회귀를 검사합니다. 실제 브라우저를 띄우지 않고 결과 컬럼 분리·계획 스냅샷·지표 의존성·확정 가능 여부 같은 데이터 계약을 확인합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `test` | 작은 회귀 사례 선언 | node:test |
| `partitionTableColumns` | 0 지표 보존 확인 대상 | 결과 표시 계약 |
| `installPlanSurface` | 최초/저장 스냅샷 확인 대상 | 상태 일관성 |

### 핵심 코드: test('constant zero metrics

같은 숫자 지표가 공통 조건으로 숨겨지는 회귀를 막습니다.

**동작:** 두 그룹에 0인 지표와 dimension/metric 메타데이터를 넣고 컬럼 분리 결과를 비교합니다.

**설계:** 브라우저 없이 실행하는 순수 함수 테스트입니다. 0도 유효한 결과이므로 누락시키지 않는 표시 규칙을 고정합니다.

**예:** 두 그룹 모두 rate=0이어도 rate 컬럼은 detailColumns에 남습니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [tests/js/review-plan.test.js](review-plan.test.js#L9). 아래는 실제 코드의 9~21행 발췌이며 앞뒤는 생략했습니다.

```javascript
test('constant zero metrics remain visible beside each group', () => {
  const result = {columns:['customer','event','rate'],metadata:{},rows:[
    {customer:'A',event:'failed delivery',rate:0},
    {customer:'B',event:'failed delivery',rate:0},
  ]};
  assert.deepEqual(partitionTableColumns(result,result.columns), {
    commonColumns:['event'],detailColumns:['customer','rate'],
  });
  result.metadata.column_metadata=[{name:'rate',role:'metric'}];
  result.rows.forEach((row) => {row.rate='0';});
  assert.ok(partitionTableColumns(result,result.columns).detailColumns.includes('rate'));
});

```

</details>

### 다른 기능과 연결되는 순서

테스트 모듈이 JS 순수 함수를 import하여 실제 결과를 assert합니다. 실행은 프로젝트 루트에서 `node --test tests/js/*.test.js`입니다.

### 확인한 범위와 한계

DOM 레이아웃·fetch 네트워크·저장 버튼 클릭·키보드 접근성·서버 통합 E2E는 이 테스트 범위에 포함하지 않습니다.

관련 검증: [review-plan.test.js](review-plan.test.js).
