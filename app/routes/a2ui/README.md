# `app/routes/a2ui` · 계획 수정·확정 HTTP API

## 1. 이 폴더의 역할

> **한눈에 보기** · 계획 수정·확정 요청을 받습니다. 오래된 화면에서 보낸 요청이나 허용되지 않은 수정은 거절합니다.

**기본 흐름:** 요청 → 서버 원본·버전 확인 → 수정 또는 확정 처리

## 2. 해결하려는 문제

오래된 화면이나 임의로 바꾼 화면 정의로 요청하면 최신 계획을 잘못 덮어쓸 수 있습니다. 서버에 저장한 원본·버전·허용 편집 범위를 기준으로 검사합니다.

## 3. 핵심 기술

서버는 **자신이 저장한 화면과 계획을 기준**으로 수정 요청을 검사합니다. 브라우저가 보낸 화면 구조를 그대로 믿지 않습니다.

`surface_id`·`plan_id`·`revision`으로 원본과 버전을 찾습니다. 허용된 항목과 선택값만 반영하고, 저장 직전에도 다른 수정이 먼저 반영됐는지 확인합니다.

## 4. 핵심 함수와 실제 코드

### 카드 편집 저장

`POST /api/review/update`는 현재 화면의 `plan`, `surface_id`, `plan_id`, `revision`, `question`을 받습니다.
서버에 저장된 입력 스키마로 편집 권한과 선택값을 검사하고, 이전 revision이 여전히 최신일 때만 원자적으로 새 revision을 저장합니다.
필수값이 덜 채워진 초안도 저장할 수 있지만 실행은 `/confirm`의 전체 검증을 통과해야 합니다. 저장 요청으로 SQL을 실행하지 않습니다.
`/refine`도 저장 시 버전 충돌을 검사합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `_validate_surface_revision` | 최신 화면·계획·버전 확인 | 낙관적 동시성 |
| `_with_authoritative_ui_schema` | 서버 UI 스키마로 요청을 재구성 | 신뢰 경계 |
| `update_review` | 불완전 초안 저장과 revision 증가 | 원자적 변경 |
| `refine_review` | 자연어 추가 조건을 계획에 반영 | 구조화 패치 |
| `confirm_review` | 유효한 계획의 실행과 결과·로그 연결 | 최종 실행 경계 |

### 핵심 코드: _validate_surface_revision

오래된 화면으로 확정하거나 수정하는 요청을 거절합니다.

**동작:** surface ID를 조회하고 plan ID와 revision을 서버 저장값과 비교하여 409 오류를 반환합니다.

**설계:** HTTP 수준의 revision 계약입니다. 확정한 조건이 현재 검토 화면과 같다는 근거를 확보합니다.

**예:** 서버 revision이 3인데 요청은 2이면 PLAN_REVISION_CONFLICT와 server_revision을 반환합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/routes/a2ui/review.py](review.py#L218). 아래는 실제 코드의 218~234행 발췌이며 앞뒤는 생략했습니다.

```python
def _validate_surface_revision(payload: ConfirmDraftRequest | RefineDraftRequest | UpdateDraftRequest) -> dict:
    """클라이언트가 보낸 surface/plan/revision이 서버에 저장한 최신 화면과 같은지 본다."""

    surface = get_plan_surface(payload.surface_id)
    if not surface:
        raise_api_error(409, PLAN_REVISION_CONFLICT, "최신 분석 화면을 찾을 수 없습니다.", retryable=True)
    if payload.plan_id and payload.plan_id != surface["plan_id"]:
        raise_api_error(409, PLAN_REVISION_CONFLICT, "분석 화면의 plan_id가 최신 상태와 다릅니다.", retryable=True)
    if payload.revision != surface["revision"]:
        raise_api_error(
            409,
            PLAN_REVISION_CONFLICT,
            "오래된 분석 화면입니다. 최신 계획을 다시 확인해 주세요.",
            retryable=True,
            details={"server_revision": surface["revision"]},
        )
    return surface
```

</details>

### 다른 기능과 연결되는 순서

`/update`와 `/refine`은 분석을 실행하지 않고 화면을 새 버전으로 저장합니다. `/confirm`은 편집·전체 계획 검증 후 execution/a2ui로 전달합니다. 저장 시 expected_revision을 사용하며 충돌은 409, 입력/계획 위반은 422로 구분합니다.

## 5. 구현 결과와 한계

**현재 구현:** 서버의 최신 화면 버전과 요청 버전이 다르면 충돌 응답을 반환합니다.

revision은 변경 충돌을 검출하며 사용자 인증 자체가 아닙니다. 카드 저장의 불완전 초안 허용과 실행 가능 여부는 서로 다르며 confirm에서 전체 검증을 다시 수행합니다.

관련 검증: [test_review_update.py](../../../tests/a2ui/test_review_update.py).

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

브라우저가 보내는 Agent2UI 계획 수정·확정 요청을 받고 서버가 발급한 화면 ID·버전을 확인합니다.

### 주요 파일

| 파일 | 역할 |
|---|---|
| [review.py](review.py) | A2UI 전용 분석 계획 확정·수정과 서버 발급 화면 검증 HTTP 라우터. |
| [schemas.py](schemas.py) | A2UI 전용 계획 확정·수정 요청과 응답 모델. |

### 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)

</details>
