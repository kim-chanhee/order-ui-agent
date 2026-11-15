# `app/static/js/surfaces` · 서버 화면 정의의 검증과 렌더링

> **한눈에 보기** · 서버가 보낸 화면 데이터의 기본 형식을 확인하고, 계획 또는 결과를 그리는 코드로 전달합니다.

**기본 흐름:** 화면 데이터(Surface) → 형식 확인 → 담당 렌더러 선택

서버의 Surface 데이터를 검사하고 계획 또는 결과 화면의 렌더러로 연결합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [runtime.js](runtime.js) | 검증된 화면을 계획·결과 렌더러로 분기. |
| [validation.js](validation.js) | 화면 식별자·종류·컴포넌트 형식 검증. |

## 핵심 개념과 동작

Surface 런타임은 전송 데이터의 최소 구조를 확인한 뒤 계획과 결과 렌더러로 분기합니다. 모델이 보내는 arbitrary HTML을 렌더하는 대신 등록된 component_type만 데이터와 연결합니다. 결과 상태와 검토 계획 상태는 서로 다른 저장소에 둡니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `validateSurface` | ID·유형·revision·데이터·컴포넌트 형태 검사 | 전송 계약 |
| `renderSurface` | 계획/결과 렌더링과 공통 상태 갱신 | 런타임 디스패치 |

### 핵심 코드: validateSurface()

불완전하거나 잘못된 서버 응답이 렌더러 깊숙이 전파되지 않도록 합니다.

**동작:** 객체·화면 유형·revision·components의 필수 필드를 검사한 뒤 같은 객체를 반환합니다.

**설계:** 런타임 형태 검증입니다. 구조 오류를 표시 진입점에서 구분합니다.

**예:** revision=0 또는 components가 배열이 아니면 Error가 발생합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/static/js/surfaces/validation.js](validation.js#L4). 아래는 실제 코드의 4~16행 발췌이며 앞뒤는 생략했습니다.

```javascript
export function validateSurface(surface) {
  if (!surface || typeof surface !== "object" || Array.isArray(surface)) throw new Error("Surface 형식이 올바르지 않습니다.");
  if (!surface.surface_id || !SURFACE_TYPES.has(surface.surface_type)) throw new Error("Surface 식별자 또는 유형이 올바르지 않습니다.");
  if (!Number.isInteger(surface.revision) || surface.revision < 1) throw new Error("Surface revision이 올바르지 않습니다.");
  if (!surface.data_model || typeof surface.data_model !== "object" || Array.isArray(surface.data_model)) throw new Error("Surface data model이 없습니다.");
  if (!Array.isArray(surface.components)) throw new Error("Surface components가 올바르지 않습니다.");
  for (const component of surface.components) {
    if (!component || typeof component !== "object" || !component.component_id || !component.component_type) {
      throw new Error("Surface component 형식이 올바르지 않습니다.");
    }
  }
  return surface;
}
```

</details>

### 다른 기능과 연결되는 순서

공통 결과/계획 응답은 renderSurface에서 검증하고 plan이면 a2ui/surfaces, result이면 result-normalizer와 result-renderer를 호출합니다. 검증 목록에는 clarification이 있으나 현재 renderSurface는 plan/result만 렌더링합니다.

### 확인한 범위와 한계

validateSurface는 모든 중첩 값·선택지·UI 보안 정책을 검사하는 전체 JSON Schema 검증기가 아닙니다. clarification 객체가 형태 검사를 통과해도 공통 렌더러에서 지원 오류가 날 수 있으며 채팅 응답 경로와 구분해야 합니다.

관련 검증: [review-plan.test.js](../../../../tests/js/review-plan.test.js).

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../../README.md)
- [프로젝트 소개](../../../../README.md)
