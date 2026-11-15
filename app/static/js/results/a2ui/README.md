# `app/static/js/results/a2ui` · Agent2UI 결과의 후속 분석 동작

> **한눈에 보기** · 결과 뒤에 후속 질문 버튼을 붙이기 위한 코드입니다. 현재 추천 목록은 비어 있어 실제 버튼은 생성되지 않습니다.

**기본 흐름:** 추천 목록 확인 → 항목이 있을 때 버튼 생성

조회 결과에서 이어갈 수 있는 후속 질문과 동작 버튼을 구성합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [follow-ups.js](follow-ups.js) | Agent2UI 결과의 후속 질문 문구와 동작 버튼 구성. |

## 핵심 개념과 동작

후속 분석 버튼은 결과 표·차트와 별도의 어댑터입니다. 콜백과 구조화 결과가 있을 때만 생성하도록 되어 있지만 현재 followUpPrompts가 빈 목록을 반환하므로 실제 추천 버튼은 생성되지 않습니다. 확장 지점의 존재와 활성 기능을 구분해야 합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `renderFollowUpActions` | 허용된 추천 목록을 버튼 콜백에 연결 | 선택적 UI |
| `followUpPrompts` | 현재는 빈 추천 목록 반환 | 비활성 확장 지점 |

### 핵심 코드: renderFollowUpActions()

결과와 콜백이 없는 상황에서 동작하지 않는 버튼을 만들지 않게 합니다.

**동작:** 표시 옵션·콜백·구조화 결과를 검사한 뒤 추천 목록이 비면 null을 반환합니다.

**설계:** Guard clause 기반 선택적 렌더링입니다. 기본 결과 렌더링과 후속 질문 추천을 독립적으로 유지합니다.

**예:** 현재 followUpPrompts가 []이므로 조건이 맞아도 null을 반환합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/static/js/results/a2ui/follow-ups.js](follow-ups.js#L4). 아래는 실제 코드의 4~21행 발췌이며 앞뒤는 생략했습니다.

```javascript
export function renderFollowUpActions(result, options) {
  if (options.showFollowUps === false || typeof options.onFollowUp !== "function" || !result.hasStructuredData) return null;
  const prompts = followUpPrompts(result);
  if (!prompts.length) return null;
  const actions = createElement("div", { className: "result-actions", attrs: { "aria-label": "후속 분석" } });
  actions.append(createElement("strong", { text: "다음 분석" }));
  for (const item of prompts) {
    const button = createElement("button", { className: "secondary", text: item.label, attrs: { type: "button" } });
    button.addEventListener("click", () => options.onFollowUp(item.prompt));
    actions.append(button);
  }
  return actions;
}

export function followUpPrompts(result) {
  void result;
  return [];
}
```

</details>

### 다른 기능과 연결되는 순서

상위 결과 렌더러가 이 함수를 호출하고 목록이 있다면 onFollowUp으로 질문을 전달하도록 설계되어 있습니다. 현재는 목록이 없어 새 SQL 실행이나 추천 생성이 여기서 발생하지 않습니다.

### 확인한 범위와 한계

추천 생성 모델·알고리즘이 구현됐다고 설명하면 안 됩니다. 현재 이 비활성 경로의 별도 자동 테스트는 없으며 향후 활성화 시 추천 의미·콜백·기존 결과 보존을 검증해야 합니다.

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../../../README.md)
- [프로젝트 소개](../../../../../README.md)
