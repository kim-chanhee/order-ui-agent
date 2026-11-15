# `app/static/js/results` · 조회 결과 정규화와 표시

## 1. 이 폴더의 역할

> **한눈에 보기** · 조회 결과를 표와 차트로 표시합니다. 컬럼과 행의 형식을 맞추고, 그룹 이름과 지표가 제대로 보이게 합니다.

**기본 흐름:** 결과 형식 정리 → 표 컬럼·차트 라벨 구성 → 표시

## 2. 해결하려는 문제

결과 형식이 다르거나 그룹 이름이 차트에서 빠지면 같은 데이터도 잘못 읽힐 수 있습니다. 형식을 통일하고 그룹·지표 정보를 표시합니다.

## 3. 핵심 기술

결과 정규화는 문자열/객체 컬럼과 배열/객체 행을 공통 형태로 바꿉니다. 렌더러는 dimension/metric 메타데이터를 우선 사용하고, 여러 그룹 컬럼은 차트 라벨에 함께 넣습니다. 모든 값이 같은 지표도 결과이므로 공통 조건으로 숨기지 않습니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `normalizeAnalysisData` | 서버 결과 형식과 기본값 정리 | Adapter |
| `partitionTableColumns` | 반복 차원값과 지표 컬럼 구분 | 표 정보 배치 |
| `chartRowLabel` | 그룹 컬럼을 결합한 행 라벨 | 다차원 라벨 |
| `shouldShowChart` | 수치·라벨·표시 요청 조건 검사 | 차트 적합성 |

### 핵심 코드: partitionTableColumns()

0처럼 모든 행에서 같은 지표를 공통 조건으로 숨기는 것을 막습니다.

**동작:** metric 역할과 숫자 컬럼을 제외한 뒤 값이 모두 같은 차원만 공통 패널로 분리합니다.

**설계:** 값과 의미 메타데이터를 결합한 표시 규칙입니다. 반복된 차원 정보는 줄이고 측정 결과는 행 옆에 남깁니다.

**예:** rate=0이 모든 그룹에 반복되어도 metric이면 detailColumns에 유지합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/static/js/results/result-renderer.js](result-renderer.js#L191). 아래는 실제 코드의 191~204행 발췌이며 앞뒤는 생략했습니다.

```javascript
export function partitionTableColumns(result, columns) {
  if (result.rows.length < 2) return { commonColumns: [], detailColumns: columns };
  const commonColumns = columns.filter((column) => {
    // Constant measurements (including zero) are still analysis results.
    const role = (result.metadata.column_metadata || []).find((item) => item.name === column)?.role;
    if (role === "metric" || (role !== "dimension" && result.rows.some((row) => typeof row[column] === "number"))) return false;
    const first = normalizedComparableValue(result.rows[0]?.[column]);
    return result.rows.every((row) => normalizedComparableValue(row?.[column]) === first);
  });
  return {
    commonColumns,
    detailColumns: columns.filter((column) => !commonColumns.includes(column)),
  };
}
```

</details>

### 다른 기능과 연결되는 순서

Surface runtime → normalizeAnalysisData → 등록 table/bar_chart 렌더러 → renderResultWithComponents 순서입니다. 차트는 처음 12행을 보여주고 추가 버튼으로 나머지를 펼치며 조회 자체를 다시 하지 않습니다.

## 5. 구현 결과와 한계

**현재 구현:** 그룹과 지표 정보를 이용해 표 컬럼을 나누고 차트 라벨을 구성합니다.

차트 적합성 검사는 앞의 일부 행과 첫 지표 중심의 휴리스틱입니다. 일반적인 다중 계열·음수·통계 시각화 도구가 아니며 숫자형 데이터의 업무 단위 적합성을 판정하지 않습니다.

관련 검증: [review-plan.test.js](../../../../tests/js/review-plan.test.js).

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

두 모드의 분석 결과를 공통 데이터 형태로 정리하고 설명·표·막대 차트로 렌더링합니다.

[후속 질문과 조회 결과 예시](../../../../docs/system-guide.md#후속-질문--이전-결과의-상세-조회)

### 주요 파일

| 파일 | 역할 |
|---|---|
| [result-normalizer.js](result-normalizer.js) | 서버 실행 결과를 공통 컬럼·행·메타데이터 형태로 정규화. |
| [result-renderer.js](result-renderer.js) | 답변·표·막대 차트·결과 컴포넌트 표시. |

### 하위 폴더 안내

| 폴더 | 역할 |
|---|---|
| [a2ui/](a2ui/README.md) | Agent2UI 결과의 후속 분석 동작 |

### 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../../README.md)
- [프로젝트 소개](../../../../README.md)

</details>
