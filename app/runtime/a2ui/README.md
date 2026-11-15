# `app/runtime/a2ui` · 계획 화면 저장과 확정 워커

## 1. 이 폴더의 역할

> **한눈에 보기** · 계획 화면의 최신 버전을 저장합니다. 다른 요청이 먼저 수정한 계획을 오래된 화면으로 덮어쓰지 못하게 합니다.

**기본 흐름:** 화면 버전 확인 → 같은 버전일 때 저장 → 다르면 충돌 응답

## 2. 해결하려는 문제

두 요청이 같은 계획을 수정하면 나중 요청이 먼저 저장한 내용을 덮어쓸 수 있습니다. 저장할 때도 이전 버전이 여전히 같은지 확인합니다.

## 3. 핵심 기술

revision은 **화면의 버전 번호**입니다. 사용자가 보고 있던 버전과 서버의 최신 버전이 같을 때만 수정 내용을 저장합니다.

이 방식을 낙관적 동시성 제어라고 합니다. 예를 들어 두 요청이 같은 2번 버전을 수정하면 먼저 저장한 요청만 성공하고, 뒤의 요청은 충돌을 알립니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `save_plan_surface` | 계획과 화면 JSON을 같은 버전으로 저장 | 조건부 UPDATE |
| `get_plan_surface` | 최신 화면·계획·참여자·스레드 조회 | 서버가 보관하는 기준 상태 |
| `SurfaceRevisionConflict` | 업데이트 경쟁을 명시적 충돌로 표시 | 동시성 오류 |
| `run_confirmation` | 워커에서 확정 요청 모델과 서비스 연결 | 프로세스 경계 |

### 핵심 코드: save_plan_surface

검증 중 다른 요청이 먼저 저장한 계획을 덮어쓰지 않게 합니다.

**동작:** 화면 ID·계획 ID·이전 버전이 모두 맞는 행만 수정합니다. 실제로 수정된 행이 하나인지 확인합니다.

**설계:** “확인한 버전이 아직 같으면 저장”을 하나의 DB 작업으로 처리합니다. 읽기와 저장 사이에 다른 요청이 먼저 수정하는 경우도 잡을 수 있습니다.

**예:** revision=2를 예상한 두 저장 중 먼저 성공한 요청 뒤의 요청은 충돌을 반환합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/runtime/a2ui/surfaces.py](surfaces.py#L33). 아래는 실제 코드의 33~42행 발췌이며 앞뒤는 생략했습니다.

```python
if expected_revision is not None:
    cursor = conn.execute(
        """UPDATE plan_surfaces SET revision = ?, plan_json = ?, surface_json = ?,
           updated_at = ? WHERE surface_id = ? AND plan_id = ? AND revision = ?""",
        (revision, _json_dumps(plan), _json_dumps(surface), now,
         surface_id, plan_id, expected_revision),
    )
    if cursor.rowcount != 1:
        raise SurfaceRevisionConflict("계획이 변경되었습니다. 최신 화면을 다시 확인해 주세요.")
    return
```

</details>

### 다른 기능과 연결되는 순서

`routes.a2ui.update/refine → a2ui.review.surface_for_plan → save_plan_surface`가 새 revision과 expected_revision을 전달합니다. 확정 서비스는 worker.run_confirmation을 통해 요청을 검증한 뒤 execution.a2ui로 연결할 수 있습니다.

## 5. 구현 결과와 한계

**현재 구현:** 이전 버전을 조건으로 갱신하고, 다른 수정이 먼저 저장됐으면 충돌을 반환합니다.

`expected_revision`을 생략하면 처음 화면을 만들 때 쓰는 저장 방식으로 동작합니다. 해당 행이 없으면 추가하고, 있으면 갱신합니다(UPSERT).

이 테이블에는 최신 버전만 남습니다. 모든 과거 편집본을 보관하지는 않습니다. 버전 확인과 별도로 인증·사용자 소유권 검사가 필요합니다.

관련 검증: [test_review_update.py](../../../tests/a2ui/test_review_update.py).

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

서버가 발급한 계획 화면의 최신 버전을 보관하고 취소 가능한 프로세스에서 확정 요청을 실행합니다.

### 주요 파일

| 파일 | 역할 |
|---|---|
| [surfaces.py](surfaces.py) | 최신 서버 발급 계획 화면과 revision 저장·조회. |
| [worker.py](worker.py) | 취소 가능한 워커에서 A2UI 계획 확정 요청을 검증하고 실행한다. |

### 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)

</details>
