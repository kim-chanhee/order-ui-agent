# `app/runtime` · 대화 상태와 취소 가능한 실행

> **한눈에 보기** · 오래 걸리는 작업을 별도 프로세스에서 실행하고, 대화와 실행 상태를 저장합니다. 진행 중인 작업의 취소도 관리합니다.

**기본 흐름:** 작업 시작 → 별도 프로세스 실행 → 상태 저장·취소·완료 처리

대화 결과·문맥·검토 화면 상태를 보관하고 별도 워커의 취소·시간 제한을 관리합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [chat_log.py](chat_log.py) | 접속 모드·입력 방식별 채팅 CSV 기록. |
| [run_manager.py](run_manager.py) | 별도 워커 프로세스에서 요청을 실행하고 취소·시간 제한을 관리한다. |
| [state_store.py](state_store.py) | thread별 실행 결과·대화 문맥·검증된 SQL 예시 저장. |

## 하위 폴더 안내

| 폴더 | 역할 |
|---|---|
| [a2ui/](a2ui/README.md) | 계획 화면 저장과 확정 워커 |

## 핵심 개념과 동작

워커는 **주 작업을 대신 수행하는 별도 프로세스**입니다. 오래 걸리는 모델 요청을 맡고, 필요하면 종료할 수 있습니다.

`spawn` 방식의 워커는 부모 메모리를 공유하지 않아 대화와 화면 상태를 DB에 저장합니다. SQLite의 WAL과 `busy_timeout`은 동시 접근을 돕는 설정이며, 여러 서버의 작업을 배분하는 기능까지 제공하지는 않습니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `run_cancelable` | spawn 워커·Queue 결과와 시간 제한 관리 | 프로세스 격리 |
| `cancel_run` | 등록된 워커 종료 | 취소 제어 |
| `record_execution_result` | 스레드의 실행 결과 보존 | SQLite 영속성 |
| `get_similar_sql_examples` | 현재 스키마의 승인된 SQL 사례만 검색 | 신뢰 경계 |

### 핵심 코드: run_cancelable

부모가 응답을 기다리는 동안 실행 중인 워커의 취소·타임아웃을 감지합니다.

**동작:** Queue를 짧은 간격으로 확인하고 시간 한도나 워커 종료를 오류로 구분합니다.

**설계:** multiprocessing spawn과 Queue를 사용합니다. 스레드의 논리적 중단 표시만으로 끝내지 않고 실제 워커 종료를 관리합니다.

**예:** 결과 없이 워커가 사라지면 HTTP 499, 제한 초과는 RunTimedOutError입니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/runtime/run_manager.py](run_manager.py#L75). 아래는 실제 코드의 75~87행 발췌이며 앞뒤는 생략했습니다.

```python
while True:
    try:
        # 짧게 polling해야 /cancel이 process를 죽였을 때 빠르게 감지할 수 있다.
        message = result_queue.get(timeout=0.2)
    except queue.Empty:
        if timeout_seconds and perf_counter() - started >= timeout_seconds:
            raise RunTimedOutError(f"run exceeded {timeout_seconds:.1f}s")
        if not process.is_alive():
            raise HTTPException(status_code=499, detail="run was cancelled")
        continue
    if message.get("ok"):
        return message["result"]
    raise HTTPException(status_code=500, detail=message.get("error") or "run failed")
```

</details>

### 핵심 코드: get_similar_sql_examples

실행됐다는 이유만으로 잘못된 SQL 사례를 다시 학습 문맥으로 쓰지 않도록 합니다.

**동작:** 스키마 fingerprint와 명시적으로 승인한 상태만 필터링해 최근 200개 후보를 읽습니다.

**설계:** gold_validated/human_approved 상태와 어휘 점수 기반 검색입니다. executed 상태의 후보와 신뢰된 사례를 구분하는 설계입니다.

**예:** 같은 스키마라도 executed 상태만 가진 사례는 검색 결과에서 제외됩니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/runtime/state_store.py](state_store.py#L420). 아래는 실제 코드의 420~433행 발췌이며 앞뒤는 생략했습니다.

```python
with closing(_connect()) as conn:
    rows = conn.execute(
        """
        SELECT question, sql, tables_json, result_columns_json
        FROM verified_sql_examples
        WHERE schema_fingerprint = ?
          AND verification_status IN ('gold_validated', 'human_approved')
        ORDER BY id DESC
        LIMIT 200
        """,
        (schema_fingerprint,),
    ).fetchall()
query_terms = _memory_terms(question)
scored: list[tuple[float, sqlite3.Row]] = []
```

</details>

### 다른 기능과 연결되는 순서

라우터가 run_id가 있는 요청을 run_cancelable로 전달하며 워커는 chat 또는 confirm 서비스로 분기합니다. 상태 저장은 다음 요청의 chat·planning이 조회합니다. SQL 사례 승격은 set_sql_example_verification의 별도 명시적 작업이며, 사례 검색은 SQL 검증을 대체하지 않습니다.

### 확인한 범위와 한계

RUNS는 한 부모 프로세스의 메모리 목록이므로 여러 서버 인스턴스에 걸친 취소를 보장하지 않습니다. 일반 채팅의 run_id 경로와 확정 실행이 워커를 쓰며 활성 실험 채팅·계획 수정은 경로가 다릅니다. 현재 테스트에는 프로세스 취소·타임아웃의 포괄적 통합 사례가 없습니다.

관련 검증: [test_turn_router.py](../../tests/test_turn_router.py), [test_review_update.py](../../tests/a2ui/test_review_update.py).

## 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)
