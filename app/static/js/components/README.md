# `app/static/js/components` · UI 컴포넌트 등록과 공통 요소

## 1. 이 폴더의 역할

> **한눈에 보기** · 화면 요소의 이름과 그리는 함수를 연결합니다. 같은 요소를 여러 화면에서 재사용할 수 있습니다.

**기본 흐름:** 요소 유형 확인 → 등록된 함수 선택 → 화면 요소 생성

## 2. 해결하려는 문제

화면 요소를 그리는 함수를 곳곳에서 직접 고르면 재사용과 지원 유형 관리가 어렵습니다. 유형 이름으로 등록된 함수를 찾아 호출합니다.

## 3. 핵심 기술

레지스트리는 **화면 요소의 이름과 그리는 함수를 짝지은 목록**입니다. Map에서 유형 이름으로 함수를 찾습니다.

공통 결과 요소와 계획 입력 요소를 따로 등록합니다. 등록되지 않은 유형은 `unknown` 렌더러로 표시합니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `registerComponent` | 유형 이름에 렌더러 등록 | Registry pattern |
| `renderComponent` | 유형에 따라 함수 선택 | 동적 디스패치 |
| `supportedComponentTypes` | unknown을 제외한 지원 목록 제공 | Capability 목록 |

### 핵심 코드: renderComponent()

서버 유형 문자열을 실행할 함수 이름으로 직접 평가하지 않도록 합니다.

**동작:** Map에 등록된 렌더러를 조회하고 없으면 unknown으로 대체합니다.

**설계:** eval 없는 함수 레지스트리입니다. 구성 요소 추가와 화면 런타임을 분리할 수 있습니다.

**예:** type="unknown_kind"는 unknown 등록 함수로 전달됩니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/static/js/components/registry.js](registry.js#L7). 아래는 실제 코드의 7~11행 발췌이며 앞뒤는 생략했습니다.

```javascript
export function renderComponent(block, context) {
  const renderer = componentRegistry.get(block.type) || componentRegistry.get("unknown");
  return renderer(block, context);
}

```

</details>

### 다른 기능과 연결되는 순서

app.js가 공통 렌더러와 a2ui/register.js의 입력 렌더러를 등록합니다. Surface 런타임은 renderComponent에 데이터와 결과/계획 문맥을 전달합니다.

## 5. 구현 결과와 한계

**현재 구현:** 유형 이름으로 렌더 함수를 선택하고 미등록 유형은 unknown 처리로 전달합니다.

unknown 렌더러도 초기화되어 있어야 안전하게 대체됩니다. 현재 레지스트리의 중복 등록은 Map 값을 교체하며 플러그인 권한·격리 기능은 아닙니다. 이 레지스트리의 모든 DOM 동작을 직접 검증하는 자동 테스트는 없습니다.

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

서버가 보낸 컴포넌트 종류를 브라우저 렌더링 함수에 연결하고 텍스트·안내·미지원 요소를 표시합니다.

### 주요 파일

| 파일 | 역할 |
|---|---|
| [components.js](components.js) | 텍스트·안내·미지원 컴포넌트의 공통 표시. |
| [registry.js](registry.js) | 컴포넌트 이름별 렌더러 등록·호출과 지원 목록 제공. |

### 하위 폴더 안내

| 폴더 | 역할 |
|---|---|
| [a2ui/](a2ui/README.md) | 계획 입력 위젯 |

### 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../../README.md)
- [프로젝트 소개](../../../../README.md)

</details>
