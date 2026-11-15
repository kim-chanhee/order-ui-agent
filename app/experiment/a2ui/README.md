# `app/experiment/a2ui` · Agent2UI 확정 실행의 실험 기록

## 1. 이 폴더의 역할

> **한눈에 보기** · 계획을 얼마나 수정했고 실행에 얼마나 걸렸는지 공통 실험 기록에 옮깁니다.

**기본 흐름:** 화면 편집·확정·실행 정보 → 실험 기록

## 2. 해결하려는 문제

화면 편집 시간과 서버 실행 시간을 섞으면 무엇에 시간이 걸렸는지 해석하기 어렵습니다. 측정 출처를 구분해 공통 실험 기록에 넣습니다.

## 3. 핵심 기술

확정 실행의 편집 지표와 실행 지표를 공통 실험 interaction 형식에 매핑합니다. 사용자가 화면을 보고 확정하기까지의 시간은 브라우저가 측정한 값이고, 실행 소요 시간은 서버가 잰 값이라 출처를 구분해야 합니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `record_confirm_interaction` | 확정 계획·diff·편집 시간과 실행 결과 기록 | 관찰 로그 어댑터 |

### 핵심 코드: record_confirm_interaction

계획 수정과 실행을 하나의 확정 상호작용에 연결합니다.

**동작:** 실행 응답에서 분석 payload를 꺼내고 client_metrics와 식별자를 공통 record_interaction에 전달합니다.

**설계:** 클라이언트 측정과 서버 측정의 명시적 매핑입니다. UI 수정 효과와 모델 실행 시간을 별도로 분석할 근거를 보존합니다.

**예:** client_metrics가 없으면 changed_fields는 []이고 편집 시간은 0으로 기록합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/experiment/a2ui/interactions.py](interactions.py#L27). 아래는 실제 코드의 27~31행 발췌이며 앞뒤는 생략했습니다.

```python
execution_result = result.get("execution_result") or {}
normalized = execution_result.get("normalized_spec") or {}
analysis_payload = normalized.get("analysis_execution") or {}
metrics = payload.client_metrics
now = _now_iso()
```

</details>

### 다른 기능과 연결되는 순서

`routes.a2ui.confirm_review → record_confirm_interaction → experiment.store.record_interaction`입니다. 일반 채팅·계획 생성 기록은 상위 interactions.py에서 처리합니다.

## 5. 구현 결과와 한계

**현재 구현:** 화면 편집 지표와 실행 지표를 공통 실험 기록 형식으로 전달합니다.

클라이언트 시간·diff는 측정 보고값이며 변경 불가능한 감사 기록이 아닙니다. 현재 제공 테스트에는 이 기록 함수의 모든 필드 매핑을 직접 검증하는 사례가 없습니다.

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

계획 확정 실행에서 발생한 편집 시간·수정 내역·실행 결과를 실험 상호작용 기록으로 만듭니다.

### 주요 파일

| 파일 | 역할 |
|---|---|
| [interactions.py](interactions.py) | A2UI 전용 계획 확정 실행을 실험 상호작용 기록으로 변환한다. |

### 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)

</details>
