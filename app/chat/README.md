# `app/chat` · 대화 요청 분류와 문맥

## 1. 이 폴더의 역할

> **한눈에 보기** · 사용자의 말이 새 분석인지, 이전 결과에 대한 후속 질문인지 판단합니다. 필요한 경우에만 새 분석으로 보냅니다.

**기본 흐름:** 질문 → 요청 종류·이전 결과 확인 → 담당 기능으로 전달

## 2. 해결하려는 문제

“이 결과를 차트로 보여줘” 같은 후속 요청마다 SQL을 다시 실행하면 불필요한 조회가 생깁니다. 새 분석과 기존 결과 활용을 구분하고 참조 대상도 확인합니다.

## 3. 핵심 기술

라우팅은 **요청을 알맞은 처리 기능으로 보내는 일**입니다. 새 분석, 이전 분석 수정, 결과 요약·설명 등을 구분합니다.

TurnDecision은 이 분류 결과를 담습니다. 이전 결과를 참조하면 해당 ID가 실제 저장된 기록인지 확인합니다. 모델의 확신도(`confidence`) 하나만으로 확인 질문을 강제하지는 않습니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `route_turn` | 구조화 분류와 참조 ID 검증·피드백 재분류 | 의도 라우팅 |
| `routed_chat_response` | 분류 결과에 따라 분석 또는 결과 재사용 | 서비스 분기 |
| `compact_context_record` | 최대 20행과 ID값·계획으로 문맥 압축 | 문맥 크기 제한 |
| `context_record_id` | 질문과 SQL의 안정적인 참조 ID | SHA-256 |
| `remember_dialogue` | 모드별 최근 문답과 오류 유형 저장 | 대화 문맥 |

### 핵심 코드: _decision_issues

LLM이 존재하지 않는 결과를 참조하거나 표시 형식을 생략하는 문제를 찾습니다.

**동작:** 실제 기록에서 ID 집합을 만들고 요청 종류별 필수 참조·응답·표시 값을 확인합니다.

**설계:** Pydantic 이후의 업무 규칙에 맞는지 추가로 검사합니다. 분류 형식이 맞아도 실제 실행 증거와 연결되지 않은 요청은 재판단하게 합니다.

**예:** transform_results에 context_reference가 없으면 context_reference_required가 반환됩니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/chat/turn_router.py](turn_router.py#L215). 아래는 실제 코드의 215~223행 발췌이며 앞뒤는 생략했습니다.

```python
if not records:
    issues.append("no_stored_results")
if decision.context_reference and decision.context_reference not in ids:
    issues.append("unknown_context_reference")
if decision.request_kind != "summarize_results" and not decision.context_reference:
    issues.append("context_reference_required")
if decision.request_kind == "transform_results" and not decision.presentation:
    issues.append("presentation_required")
return issues
```

</details>

### 핵심 코드: context_record_id

같은 질문·SQL 조합의 이전 결과에 재현 가능한 참조 이름을 붙입니다.

**동작:** 공백을 정리한 질문과 SQL을 정규 JSON으로 만들고 해시 접두사로 scope ID를 반환합니다.

**설계:** 내용 기반 참조 식별자이며 UUID나 행 번호와 다릅니다. 후속 질문의 선택 대상을 모델이 임의로 만들지 않도록 실제 ID 목록과 대조합니다.

**예:** 같은 질문·SQL에는 같은 scope_ 접두사의 ID가 만들어집니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/chat/thread_context.py](thread_context.py#L105). 아래는 실제 코드의 105~118행 발췌이며 앞뒤는 생략했습니다.

```python
def context_record_id(record: dict) -> str:
    """질문과 SQL을 해시해 동일한 내용의 분석을 참조할 scope 식별자를 반환한다."""

    execution = ((record.get("normalized_spec") or {}).get("analysis_execution") or {})
    payload = json.dumps(
        {
            "question": str(record.get("question") or "").strip(),
            "sql": str(execution.get("sql") or "").strip(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "scope_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
```

</details>

### 다른 기능과 연결되는 순서

`service → dispatch → route_turn` 뒤 requires_analysis이면 Baseline 실행 또는 Agent2UI 검토로 전달합니다. transform_results는 기존 행을 복사해 표시만 바꾸고 새 SQL을 실행하지 않습니다. 요약·설명에는 기록별 최대 100행과 잘림 정보를 제공하며 대화 기록 자체는 실행 증거가 아닙니다.

## 5. 구현 결과와 한계

**현재 구현:** 이전 결과를 참조하는 요청은 실제 기록 ID를 검사합니다. 표시 변경은 저장 결과를 활용합니다.

문답은 모드별 최대 6턴, 분석 문맥은 최근 5건을 중심으로 압축합니다. 표본에 없는 전체 결과나 원인을 모델이 증명할 수는 없습니다. 분류 장애 시 임의 SQL 실행 대신 실패/확인 응답으로 종료합니다.

관련 검증: [test_turn_router.py](../../tests/test_turn_router.py).

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

자연어 한 턴을 분석·확인 질문·일반 대화·기존 결과 설명으로 분류하고 모드에 맞는 서비스로 전달합니다.

### 주요 파일

| 파일 | 역할 |
|---|---|
| [dispatch.py](dispatch.py) | 요청을 분류하고 분석 실행·계획 확인·저장 결과 활용 경로로 전달한다. |
| [responses.py](responses.py) | 대화·확인 질문·화면 안내 문구를 LLM으로 작성하는 공통 응답 계층. |
| [service.py](service.py) | 채팅 요청을 공통 대화 처리기로 전달하는 진입점. |
| [thread_context.py](thread_context.py) | 대화(thread) 맥락 관리. |
| [turn_router.py](turn_router.py) | 분석 계획 생성 전에 사용자 요청을 분류하고 저장된 결과 기반 응답을 만든다. |

### 하위 폴더 안내

| 폴더 | 역할 |
|---|---|
| [a2ui/](a2ui/README.md) | Agent2UI 계획 검토 응답 |

### 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)

</details>
