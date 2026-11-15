# `app/execution/results` · 실행 결과의 검증과 응답 구성

## 1. 이 폴더의 역할

> **한눈에 보기** · 조회 결과의 컬럼과 행이 요청한 결과 형태에 맞는지 확인합니다. 검사 결과는 응답 데이터에 반영합니다.

**기본 흐름:** 조회 결과 → 표시 항목·중복 등 검사 → 응답 구성

## 2. 해결하려는 문제

SQL이 정상 실행돼도 필요한 이름이 빠지거나 같은 대상이 여러 행으로 나올 수 있습니다. 반환된 컬럼과 확인 가능한 중복을 추가로 검사합니다.

## 3. 핵심 기술

결과 계약(Result Contract)은 SQL 구조 검증 이후 반환된 컬럼·행이 요청한 속성과 결과 단위에 맞는지 검사합니다. display_name을 요청했는데 식별자만 노출하거나, 고유 대상 목록에 확인 가능한 중복 키가 있는 경우를 구분합니다. 실패 payload는 성공 데이터가 없는 상황을 명시적으로 표현합니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `validate_result_contract` | 표시 속성·제외 속성·확인 가능한 중복 키 검사 | 결과 계약 |
| `ResultContractViolation` | 안정적인 오류 코드와 사유 | 계약 예외 |
| `_failed_payload` | 빈 실패 데이터와 실패 메타데이터 생성 | 실패 응답 모델 |

### 핵심 코드: validate_result_contract

검증할 계획·요청 속성이 없는 상황을 전체 검사 통과와 혼동하지 않도록 범위를 정합니다.

**동작:** 계획을 매핑으로 만들고 요청 속성이 없으면 반환하며, 있으면 설정된 속성 역할과 결과 컬럼을 대조합니다.

**설계:** 업무 속성별 선택적 후조건 검증입니다. SQL 실행 자체로는 표시 이름·결과 단위 적합성을 알 수 없기 때문입니다.

**예:** requested_attributes=["display_name"]인데 *_name/설정된 표시 필드가 없으면 missing_display_name입니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/execution/results/result_contract.py](result_contract.py#L49). 아래는 실제 코드의 49~66행 발췌이며 앞뒤는 생략했습니다.

```python
plan = _as_mapping(confirmed_plan)
if not plan:
    return
requested = {_normalize(value) for value in plan.get("requested_attributes", []) if value}
if not requested:
    return

semantics = load_analysis_semantics()
roles = {
    _normalize(role): {_normalize(field) for field in fields if field}
    for role, fields in (semantics.get("attribute_roles") or {}).items()
    if isinstance(fields, list)
}
normalized_columns = {_normalize(column): column for column in columns}

if "display_name" in requested:
    display_fields = set(roles.get("display_name", set()))
    entity = _entity_definition(plan.get("target_entity"), semantics)
```

</details>

### 다른 기능과 연결되는 순서

execute_query가 DB 행을 읽은 뒤 validate_result_contract를 호출하고, 통과한 조회만 후보 성공 목록에 기록합니다. baseline/a2ui 서비스는 실행 실패 때 _failed_payload를 이용해 공통 Surface로 변환합니다.

## 5. 구현 결과와 한계

**현재 구현:** 요청된 표시 속성과 확인 가능한 고유 키 중복을 검사하고 실패 사유를 구분합니다.

요청 속성이 없으면 이 검사 단계는 생략됩니다. 키가 없거나 설정이 부족한 경우 모든 중복을 증명하지는 못하며 반환 상한에 의해 잘린 행 집합만 검사합니다. 결과 계약은 정답 데이터셋과의 전체 비교가 아닙니다.

관련 검증: [test_sql_tools.py](../../../tests/execution/test_sql_tools.py).

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

실행 결과의 검증과 응답 구성를 담당합니다.

### 주요 파일

| 파일 | 역할 |
|---|---|
| [result_contract.py](result_contract.py) | 반환 컬럼·결과 단위·요청 속성이 분석 계획과 일치하는지 검사한다. |
| [result_payload.py](result_payload.py) | Baseline과 Agent2UI에서 공유하는 실행 실패 응답 데이터를 구성한다. |

### 함께 읽기

- [실행 계층 안내](../README.md)
- [앱 전체 구조](../../README.md)

</details>
