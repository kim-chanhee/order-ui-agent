# `app/static/js/modes` · 관리자·사용자 접속 모드

> **한눈에 보기** · 관리자·참가자 접속 방식과 Baseline·Agent2UI 분석 방식을 구분합니다. 각 방식에 맞게 요청 정보를 준비합니다.

**기본 흐름:** 접속·분석 방식 확인 → 참가 정보 추가 → 요청·대화 ID 관리

관리자 모드와 사용자 모드의 진입·프로필·요청 데이터·응답 반영 방식을 구분합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [admin-mode-data.js](admin-mode-data.js) | 관리자 모드 진입과 요청·응답 데이터 처리. |
| [mode-data.js](mode-data.js) | 접속 모드에 맞는 관리자·사용자 동작 선택. |
| [user-mode-data.js](user-mode-data.js) | 참가자 번호 검증·프로필·세션 저장과 사용자 모드 요청 처리. |

## 핵심 개념과 동작

admin/user는 접속·실험 프로필 구분이고 baseline/agent2ui는 분석 입력 방식 구분입니다. 모드별 요청 어댑터가 참가자 ID·프로필을 덧붙이고, 응답에서 입력 방식별 thread_id를 갱신합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `modeDataFor` | 모드별 요청/응답 어댑터 선택 | Strategy pattern |
| `buildUserRequest` | 참가자 프로필과 요청 결합 | 모드 어댑터 |
| `normalizeParticipantId` | 참가자 식별자 정규화 | 입력 정리 |
| `isValidParticipantId` | P와 숫자 형식 확인 | 형식 검증 |

### 핵심 코드: normalizeParticipantId()

입력 대소문자·공백 차이를 줄이고 참가자 ID 형식을 검사합니다.

**동작:** 문자열을 trim·대문자화하고 P 뒤 최소 3자리 숫자 패턴으로 검사합니다.

**설계:** 정규식 기반 클라이언트 입력 검증입니다. 기록마다 같은 참가자가 다른 문자열로 나타나는 것을 줄입니다.

**예:** " p001 " → "P001"이며 형식 검사 결과는 true입니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/static/js/modes/user-mode-data.js](user-mode-data.js#L48). 아래는 실제 코드의 48~54행 발췌이며 앞뒤는 생략했습니다.

```javascript
export function normalizeParticipantId(value) {
  return String(value || "").trim().toUpperCase();
}

export function isValidParticipantId(value) {
  return /^P\d{3,}$/.test(value);
}
```

</details>

### 다른 기능과 연결되는 순서

app.js와 review-controller는 modeDataFor를 통해 요청을 구성합니다. sessionStorage에 참가자 ID를 보존하되 저장 접근 실패는 빈 값/false로 처리합니다. 실제 실험 조건·과제 권한은 서버 세션에서 확인합니다.

### 확인한 범위와 한계

참가자 ID 패턴과 접속 모드는 인증 수단이 아닙니다. 현재 모드 어댑터·sessionStorage·프로필 DOM 전체에 대한 별도 자동 테스트는 제공하지 않습니다.

## 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../../README.md)
- [프로젝트 소개](../../../../README.md)
