# `app/static/a2ui` · 계획 검토 화면 스타일

## 1. 이 폴더의 역할

> **한눈에 보기** · 계획 편집 화면의 배치와 스타일을 정합니다. 긴 조건명, 선택 버튼, 키보드 포커스가 보이도록 구성합니다.

**기본 흐름:** 계획 입력 요소 → 배치·줄바꿈·상태 스타일 적용

## 2. 해결하려는 문제

조건명과 선택값이 길면 입력 요소가 넘치거나 키보드 포커스가 잘 보이지 않을 수 있습니다. 배치·줄바꿈·상태별 스타일로 이를 다룹니다.

## 3. 핵심 기술

계획 편집 스타일은 공통 결과 스타일과 분리된 CSS 계층입니다. Grid/Flex의 min-width:0, 줄바꿈과 포커스 상태를 사용해 긴 조건명·선택 라벨을 표시하고 사용자 입력 위젯을 구분합니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `.plan-choice-chips` | 선택 카드의 두 열 Grid 배치 | CSS Grid |
| `.plan-choice-chip:focus-within` | 키보드 포커스 표시 | 접근성 상태 |
| `.msg.confirmed` | 확정 후 편집 영역 숨김 | 상태 기반 스타일 |

### 핵심 코드: .plan-choice-chips

여러 선택값을 카드 형태로 배치하고 긴 라벨의 넘침을 줄입니다.

**동작:** Grid 열을 균등 분할하고 minmax/min-width·overflow-wrap으로 폭과 줄바꿈을 제어합니다.

**설계:** CSS Grid·:has·:focus-within 선택자입니다. 입력 상태와 키보드 포커스를 화면에서 구분할 수 있게 합니다.

**예:** 체크한 카드에는 테두리/배경이 적용되고 포커스가 내부 입력에 있으면 outline이 나타납니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/static/a2ui/review.css](review.css#L11). 아래는 실제 코드의 11~18행 발췌이며 앞뒤는 생략했습니다.

```css
.plan-choice-chips { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 9px; margin-top: 8px; }
.plan-choice-chip { display: flex; align-items: flex-start; gap: 10px; min-height: 44px; padding: 12px; border: 1px solid var(--border); border-radius: 10px; background: #fff; cursor: pointer; }
.plan-choice-chip.is-selected, .plan-choice-chip:has(input:checked) { border-color: var(--accent); background: var(--accent-soft); }
.plan-choice-chip input { flex-shrink: 0; width: 18px; height: 18px; margin: 2px 0 0; accent-color: var(--accent); }
.plan-choice-chip span { display: grid; gap: 3px; min-width: 0; overflow-wrap: anywhere; }
.plan-choice-chip strong { font-size: 13px; font-weight: 650; }
.plan-choice-chip small { color: var(--text-muted); font-size: 12px; font-weight: 400; }
.plan-choice-chip:focus-within { outline: 3px solid var(--accent-ring); outline-offset: 2px; }
```

</details>

### 다른 기능과 연결되는 순서

index.html은 공통 styles.css 다음 이 파일을 로드합니다. JS는 confirmed 등의 클래스를 변경하고 CSS는 표현만 담당합니다.

## 5. 구현 결과와 한계

**현재 구현:** 계획 입력에 배치·줄바꿈·선택·포커스 스타일을 적용합니다.

CSS는 실제 편집 권한을 차단하지 않습니다. :has 지원 브라우저와 반응형·접근성의 실제 시각 검증이 필요하며 현재 자동 화면 회귀 테스트는 없습니다.

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

Agent2UI 계획 카드, 편집 입력, 확정 상태와 후속 동작에 쓰는 CSS를 관리합니다.

### 주요 파일

| 파일 | 역할 |
|---|---|
| [review.css](review.css) | 계획 카드·편집 입력·확정 상태·후속 동작 스타일. |

### 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)

</details>
