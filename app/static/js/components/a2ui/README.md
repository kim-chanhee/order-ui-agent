# `app/static/js/components/a2ui` · 계획 입력 위젯

> **한눈에 보기** · 계획 편집에 쓰는 선택 상자·날짜·필터 등의 입력 위젯입니다. 입력값을 읽고 변경을 공통 편집부에 전달합니다.

**기본 흐름:** 입력 정의·현재 값 → 위젯 표시 → 변경 전달

텍스트·숫자·날짜·선택지·체크박스 등 계획 수정에 쓰는 입력 컴포넌트를 렌더링합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [inputs.js](inputs.js) | 계획 편집용 입력 위젯 렌더링과 변경 이벤트 처리. |
| [register.js](register.js) | 계획 검토용 컴포넌트를 공통 레지스트리에 등록. |

## 핵심 개념과 동작

입력 위젯은 block의 선택지·field_path를 사용하고 현재 값은 context.valueFor, 변경은 context.update를 통해 전달합니다. 따라서 각 위젯이 전역 계획 객체의 모든 세부 구조를 직접 관리할 필요가 없습니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `registerReviewComponents` | 입력 유형과 렌더러 연결 | 컴포넌트 등록 |
| `renderSelectComponent` | 값과 표시 라벨을 분리한 선택 입력 | 공통 상태에 연결된 입력 |
| `renderOptionCardsComponent` | 선택 카드와 입력 상태 표현 | 선언형 선택지 |
| `renderDateRangeComponent` | 기간 모드와 날짜 입력 갱신 | 복합 입력 |

### 핵심 코드: renderSelectComponent()

표시 라벨 대신 서버에서 허용한 실제 선택값을 계획에 저장합니다.

**동작:** options를 DOM option으로 만들고 현재 값을 지정하며 change를 context.update로 전달합니다.

**설계:** 데이터 바인딩과 이벤트 콜백입니다. 라벨을 업무 값으로 오인하거나 여러 위젯에 편집 로직을 중복하지 않게 합니다.

**예:** label="주문"이고 value="order_id"인 선택지는 order_id를 저장합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/static/js/components/a2ui/inputs.js](inputs.js#L9). 아래는 실제 코드의 9~20행 발췌이며 앞뒤는 생략했습니다.

```javascript
export function renderSelectComponent(block, context) {
  const wrapper = fieldWrapper(block);
  const select = createElement("select");
  select.disabled = block.disabled;
  select.append(createElement("option", { text: "선택", attrs: { value: "" } }));
  for (const option of block.options || []) select.append(createElement("option", { text: option.label || option.value, attrs: { value: option.value } }));
  select.value = context.valueFor(block) ?? "";
  select.addEventListener("change", () => context.update(context.pathFor(block), select.value || null));
  wrapper.append(select);
  return wrapper;
}

```

</details>

### 다른 기능과 연결되는 순서

a2ui/plan 렌더러가 block을 레지스트리에 전달하고 위젯의 변경 콜백은 applyLocalPlanEdit와 서버 저장으로 연결됩니다. 값·블록 기본값의 권위는 서버 카탈로그와 AnalysisPlan에 있습니다.

### 확인한 범위와 한계

브라우저 select의 값 제한은 서버 검증을 대체하지 않습니다. 키보드·포커스·스크린리더·모바일 조작에 대한 포괄 자동 검증은 없습니다.

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../../../README.md)
- [프로젝트 소개](../../../../../README.md)
