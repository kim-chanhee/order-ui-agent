# 프론트엔드 공통·A2UI 코드 배치

> **한눈에 보기** · 브라우저에서 질문 입력, 계획 편집, 결과 표시를 담당합니다. 서버가 보낸 데이터에 맞춰 화면을 갱신합니다.

**기본 흐름:** 사용자 입력 → API 요청 → 응답 확인 → 화면 갱신

`app.js`에는 사용자 모드, 채팅 전송, 결과 표시만 두고, A2UI 계획 검토 본문은 전용 모듈로 위임한다. HTTP 주소와 요청 필드는 유지한다.

| 위치 | 역할 |
|---|---|
| `js/app.js` | 공통 진입점, 모드 선택, 채팅과 결과 표시 |
| `js/api.js` | 공통 JSON 전송·HTTP 오류 처리·채팅·실행 취소 |
| `js/state.js` | 사용자·모드별 대화 ID·활성 실행·결과 상태 |
| `js/surfaces/` | 두 모드의 화면 전송 규격 검증과 결과 렌더링, 계획 화면 위임 |
| `js/components/registry.js` | 공통 컴포넌트 등록과 지원 목록 |
| `js/components/components.js` | 공통 결과 텍스트·안내·미지원 컴포넌트 표시 |
| `js/components/a2ui/` | 계획 입력 위젯과 전용 컴포넌트 등록 |
| `js/results/` | 두 모드 공통 결과 정규화·표·차트 |
| `js/results/a2ui/` | A2UI 결과에만 연결하는 후속 분석 버튼 처리 |
| `js/a2ui/review-controller.js` | 검토 화면 표시·추가 조건 수정·확정 실행 흐름 |
| `js/a2ui/api.js` | 계획 수정·확정 HTTP 호출 |
| `js/a2ui/state.js` | 편집 계획·초기 스냅샷·현재 검토 화면·확정 계획 |
| `js/a2ui/surfaces.js` | 계획 화면을 편집 상태에 설치하고 지원 동작 연결 |
| `js/a2ui/plan/` | 계획 정규화·문장·카드·조건·차이·확정 검증 |
| `js/modes/` | 관리자·참여자 프로필과 요청·응답 데이터 처리 |
| `styles.css` | 공통 레이아웃·채팅·결과 표·차트 스타일 |
| `a2ui/review.css` | 계획 카드·편집 입력·확정 상태·후속 버튼 스타일 |

[두 입력 방식의 실제 화면 비교](../../README.md#어떤-문제를-해결하나요)

## 하위 폴더 안내

| 폴더 | 역할 |
|---|---|
| [a2ui/](a2ui/README.md) | 계획 검토 화면 스타일 |
| [js/](js/README.md) | 브라우저 앱과 공통 화면 제어 |

## 핵심 개념과 동작

프론트엔드는 번들러 없이 ES Modules로 파일을 연결합니다. app.js는 채팅·모드·결과 표시를 조율하고 계획 편집은 전용 컨트롤러에 위임합니다. DOM 생성은 공통 createElement와 textContent를 사용해 모델의 문자열을 HTML로 직접 해석하지 않도록 합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `ask` | 실행 ID를 붙여 요청하고 현재 실행의 응답만 수용 | 비동기 상태 제어 |
| `renderSurface` | 계획·결과 화면으로 위임 | 선언형 렌더링 |
| `createReviewController` | 검토 중 저장·수정·확정 순서 관리 | 컨트롤러 분리 |
| `createElement` | 텍스트 노드 중심 DOM 구성 | HTML 주입 억제 |

### 핵심 코드: createElement()

LLM 출력과 DB 값을 임의 HTML로 실행하지 않고 표시합니다.

**동작:** DOM 노드를 만들고 문자열은 textContent, 허용된 호출부의 속성은 setAttribute로 적용합니다.

**설계:** 브라우저 DOM API 기반 렌더링입니다. 모델 텍스트와 실행 가능한 마크업을 분리합니다.

**예:** `text="<script>..."`는 createElement의 text 옵션에서는 글자로 표시됩니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/static/js/utils.js](js/utils.js#L6). 아래는 실제 코드의 6~14행 발췌이며 앞뒤는 생략했습니다.

```javascript
export function createElement(tag, options = {}) {
  const element = document.createElement(tag);
  if (options.className) element.className = options.className;
  if (options.text !== undefined) element.textContent = String(options.text);
  for (const [key, value] of Object.entries(options.attrs || {})) {
    if (value !== undefined && value !== null && value !== false) element.setAttribute(key, String(value));
  }
  return element;
}
```

</details>

### 다른 기능과 연결되는 순서

`templates/index.html → js/app.js → surfaces/runtime.js → 결과 렌더러 또는 a2ui 컨트롤러`로 연결합니다. CSS는 공통 styles.css 뒤에 a2ui/review.css를 로드합니다.

### 확인한 범위와 한계

Node 테스트는 순수 함수 위주이며 실제 DOM 조작·키보드·모바일 레이아웃·실제 fetch와 서버 연계를 모두 검증하지 않습니다. createElement의 임의 속성까지 자동 정화하는 범용 HTML sanitizer는 아닙니다.

관련 검증: [review-plan.test.js](../../tests/js/review-plan.test.js).

## 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)
