# `app/experiment` · 사용자 실험 진행과 상호작용 기록

## 1. 이 폴더의 역할

> **한눈에 보기** · 사용자 연구의 참가 세션과 과제 진행을 관리합니다. 질문·수정·실행 기록을 남겨 이후 분석에 사용합니다.

**기본 흐름:** 세션 시작 → 과제 수행 → 실행·행동 기록 → 다음 과제

## 2. 해결하려는 문제

과제 순서나 성공 기록이 일관되지 않으면 사용자 행동을 비교하기 어렵습니다. 단계 이동 조건과 기록 형식을 정하고 중복 기록을 구분합니다.

## 3. 핵심 기술

상태 기계(State Machine)는 **진행 가능한 단계와 이동 규칙을 정해 두는 방식**입니다. 실험 세션이 과제를 정해진 순서로 진행하도록 사용합니다.

A/B 조건 순서는 현재 세션 수를 균형 있게 배정하며 무작위 배정은 아닙니다. 세션 생성과 시도 번호 계산은 DB 트랜잭션으로 보호합니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `start_session` | 기존 참가자 세션 복구 또는 조건 순서 배정 | 트랜잭션 |
| `validate_active_task` | 현재 단계와 입력 모드 일치 검사 | 상태 기계 |
| `complete_current_task` | 성공 상호작용 기록 후 과제 완료 | 상태 전이 게이트 |
| `record_interaction` | 중복 run/interaction 방지와 시도 번호 저장 | 멱등 기록 |
| `score_result_accuracy` | 과제 설정의 최소 행 수 기준 평가 | 제한적 자동 평가 |
| `append_experiment_csv` | 편집·계획·결과·인구통계 CSV 기록 | 측정 로그 |

### 핵심 코드: complete_current_task

아무 상호작용 없이 과제를 완료하는 진행을 막습니다.

**동작:** 현재 세션과 모드를 검사하고 성공 기록이 없으면 거절한 뒤 완료 테이블에 UPSERT합니다.

**설계:** 상태 전이 조건과 SQLite 트랜잭션입니다. 과제 진행과 성공 상호작용의 연결 근거를 남깁니다.

**예:** 기록이 없으면 ValueError, 이미 완료된 단계는 같은 키로 완료 시각을 갱신합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/experiment/store.py](store.py#L148). 아래는 실제 코드의 148~163행 발췌이며 앞뒤는 생략했습니다.

```python
def complete_current_task(participant_id: str) -> ExperimentSession:
    with closing(_connect()) as conn:
        with conn:
            session = _require_session_in_conn(conn, participant_id)
            condition, task_id = validate_active_task(session, "agent2ui" if session.current_condition == "agent2ui" else "baseline")
            if not _has_successful_interaction(conn, participant_id, condition, task_id):
                raise ValueError("current task cannot be completed before a successful interaction is recorded")
            conn.execute(
                """
                INSERT INTO experiment_task_completions (participant_id, step, condition, task_id, completed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(participant_id, step) DO UPDATE SET completed_at = excluded.completed_at
                """,
                (participant_id, session.current_step, condition, task_id, _now_iso()),
            )
            return _fetch_session(conn, participant_id)  # type: ignore[return-value]
```

</details>

### 핵심 코드: score_result_accuracy

자동 평가 필드가 실제로 무엇을 측정하는지 명확히 합니다.

**동작:** task의 expected_result.min_row_count가 있으면 반환 행 수와 비교하고 없으면 None입니다.

**설계:** 연구자 설정에 따른 제한적 검증입니다. 실행 성공·최소 결과 존재·업무 정답을 서로 구분해야 합니다.

**예:** min_row_count=1이면 행이 한 개 이상일 때 True지만 값 자체의 정답은 비교하지 않습니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/experiment/tasks.py](tasks.py#L49). 아래는 실제 코드의 49~60행 발췌이며 앞뒤는 생략했습니다.

```python
def score_result_accuracy(result_payload: dict[str, Any] | None, task_id: str | None) -> bool | None:
    """Return a coarse automated result check from researcher criteria."""

    task = get_task(task_id)
    if not task or not isinstance(result_payload, dict):
        return None
    expected = task.get("expected_result") or {}
    min_rows = expected.get("min_row_count")
    if min_rows is None:
        return None
    rows = result_payload.get("rows") or []
    return isinstance(rows, list) and len(rows) >= int(min_rows)
```

</details>

### 다른 기능과 연결되는 순서

라우트는 experiment_context로 현재 모드·과제·고정 thread_id를 확인하고, 실행 후 공통 또는 a2ui 전용 interaction 변환기를 통해 DB에 기록합니다. CSV와 SQLite 로그는 저장 목적·스키마가 다릅니다. 별도 통계 분석은 [Data/A2UI](../../Data/A2UI/README.md)에서 수행합니다.

## 5. 구현 결과와 한계

**현재 구현:** 성공한 상호작용 기록을 확인한 뒤 과제 완료 처리를 하고 진행 단계를 갱신합니다.

execution_success는 현재 기록 코드에서 analysis_payload의 존재 여부를 사용하며 통계적 정답을 뜻하지 않습니다. 과제 정확도는 최소 행 수 같은 조잡한 기준으로 제한됩니다. 실험 세션 진행·CSV 다중 프로세스 동시 기록에 대한 포괄 자동 테스트는 현재 없습니다. CSV의 threading.Lock은 프로세스 간 잠금이 아닙니다.

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

참가자 세션·현재 과제·진행 단계를 관리하고 질문·계획·실행 결과를 연구용 상호작용으로 기록합니다.

### 주요 파일

| 파일 | 역할 |
|---|---|
| [context.py](context.py) | 채팅·계획 검토에서 공유하는 활성 실험 과제와 대화 식별자 조회. |
| [interactions.py](interactions.py) | 두 모드의 채팅 결과를 공통 실험 상호작용 기록으로 변환한다. |
| [log.py](log.py) | 실험 상호작용을 공통 필드의 CSV로 기록. |
| [store.py](store.py) | 실험 세션·과제 진행·상호작용의 SQLite 저장과 조회. |
| [tasks.json](tasks.json) | 연구자가 조정하는 과제·질문·평가 기준 설정. |
| [tasks.py](tasks.py) | 과제 설정 로딩과 계획·결과의 기준 검사. |

### 하위 폴더 안내

| 폴더 | 역할 |
|---|---|
| [a2ui/](a2ui/README.md) | Agent2UI 확정 실행의 실험 기록 |

### 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)

</details>
