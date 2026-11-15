# `app/static/js` · 브라우저 앱과 공통 화면 제어

> **한눈에 보기** · 화면 상태와 서버 통신을 연결하는 JavaScript 코드입니다. 늦게 도착한 이전 응답이 새 화면을 덮지 않도록 구분합니다.

**기본 흐름:** 입력 → 요청 식별 → 서버 응답 → 현재 화면에 반영

모드 선택·참가자 입력·채팅 전송·실행 상태·결과 표시를 조합하는 프론트엔드 진입점입니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [api.js](api.js) | 공통 JSON 요청·채팅 전송·실행 취소·HTTP 오류 처리. |
| [app.js](app.js) | 모드 선택·프로필·채팅 전송·결과 표시와 검토 컨트롤러 연결. |
| [state.js](state.js) | 모드별 대화 ID·현재 실행·결과 화면의 공통 상태. |
| [utils.js](utils.js) | DOM 생성·텍스트 처리·객체 복사·중첩 경로 접근 도구. |

## 하위 폴더 안내

| 폴더 | 역할 |
|---|---|
| [a2ui/](a2ui/README.md) | 계획 검토 전용 프론트엔드 |
| [components/](components/README.md) | UI 컴포넌트 등록과 공통 요소 |
| [modes/](modes/README.md) | 관리자·사용자 접속 모드 |
| [results/](results/README.md) | 조회 결과 정규화와 표시 |
| [surfaces/](surfaces/README.md) | 서버 화면 정의의 검증과 렌더링 |

## 핵심 개념과 동작

공통 상태(appState)와 계획 편집 상태(reviewState)를 나눕니다. 실행마다 run_id를 생성해 늦게 도착한 이전 응답이 새 화면을 덮지 않도록 현재 ID와 취소 ID를 비교합니다. postJson은 서버의 오류 응답 형식를 화면에 사용할 Error 객체로 정규화합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `beginRun` | 실행 ID와 상태 시작 | 비동기 경합 제어 |
| `endRun` | 같은 실행일 때만 상태 해제 | 응답 일관성 |
| `postJson` | JSON 요청과 공통 HTTP 오류 변환 | fetch 어댑터 |
| `pathParts` | 위험한 객체 경로 토큰 차단 | Prototype pollution 방어 |

### 핵심 코드: pathParts()

필드 경로를 이용한 프로토타입 변경을 막습니다.

**동작:** 배열 표기를 점 경로로 바꾸고 남은 괄호·금지 토큰이 있으면 예외를 발생시킵니다.

**설계:** 경로 기반 접근의 allow/deny 검증입니다. UI 데이터 경로를 자바스크립트 객체의 특별 속성에 연결하지 않게 합니다.

**예:** filters[0].value는 허용 경로로 분해되고 __proto__.x는 오류입니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/static/js/utils.js](utils.js#L22). 아래는 실제 코드의 22~31행 발췌이며 앞뒤는 생략했습니다.

```javascript
export function pathParts(path) {
  const normalized = String(path || "").replace(/\[(\d+)\]/g, ".$1");
  if (normalized.includes("[") || normalized.includes("]")) throw new Error("Unsafe object path rejected");
  const parts = normalized.split(".").filter(Boolean);
  if (parts.some((part) => BLOCKED_PATH_PARTS.has(part))) {
    throw new Error("Unsafe object path rejected");
  }
  return parts;
}

```

</details>

### 다른 기능과 연결되는 순서

공통 app.js는 modeDataFor로 요청 모드를 구성하고 postJson으로 전송합니다. Surface 런타임은 appState의 결과만 갱신하며 계획 상태는 a2ui 모듈이 관리합니다. 소스 import의 쿼리 문자열은 파일 버전 구분에 쓰이고 서버 API 버전 관리 체계와는 다릅니다.

### 확인한 범위와 한계

브라우저 내부 상태 검사만으로 서버 권한을 보장하지 않습니다. 요청 취소는 서버 cancel API와 함께 동작하며 네트워크 응답 무시와 실제 워커 종료는 별개입니다.

관련 검증: [review-plan.test.js](../../../tests/js/review-plan.test.js).

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)
