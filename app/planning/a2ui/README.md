# `app/planning/a2ui` · 계획 검토·추가 조건·편집 검증

## 1. 이 폴더의 역할

> **한눈에 보기** · 사용자가 바꾼 조건을 계획에 반영합니다. 화면 편집과 자연어 수정 모두 서버가 허용한 항목과 값인지 확인합니다.

**기본 흐름:** 조건 수정 → 허용 범위·값 검사 → 계획 갱신

## 2. 해결하려는 문제

화면에서 일부 조건만 바꿨는데 다른 조건까지 바뀌거나 지표의 분자·분모가 어긋날 수 있습니다. 허용된 수정만 반영하고 연관 항목을 함께 맞춥니다.

## 3. 핵심 기술

검토 중 편집은 전체 계획을 무조건 교체하는 작업이 아닙니다. 카드 편집과 자연어 수정 모두 서버가 허용한 경로·선택지로 검증합니다. 자연어는 RefinementPatch로 받아 요청한 필드 변경과 필터 추가·삭제만 반영하고, 지표 변경에 따른 분자·분모·단위는 별도로 파생시킵니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `RefinementPatch` | 제한된 경로 업데이트와 필터 변경 모델 | 구조화 패치 |
| `refine_dynamic_analysis` | 추가 조건을 패치로 해석 | LLM Structured Output |
| `apply_plan_update` | 허용 변경을 원본에 투영하고 의미 검사 | 편집 권한 검증 |
| `normalize_metric_dependencies` | 대표 지표에 따른 종속 필드 갱신 | 의존성 정규화 |
| `refresh_dynamic_plan` | 변경 계획의 선택지와 필수값 재발급 | 동적 카탈로그 |

### 핵심 코드: apply_plan_update

상위 객체 교체를 이용해 편집 권한 밖의 값을 바꾸는 요청을 막습니다.

**동작:** 원본·요청 값의 변경 경로를 구한 뒤 서버 발급 경로에 해당하는 변경만 원본 사본에 투영합니다.

**설계:** 재귀 diff와 허용 경로 검사, 파생 값 정규화가 결합됩니다. metric.kind 변경에 필요한 종속 수정은 허용하면서 execution_policy 같은 보호값 변경은 거절합니다.

**예:** 허용 경로가 metric.kind뿐인데 질문 원문까지 바꾸면 ValueError가 발생합니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/planning/a2ui/validator.py](validator.py#L249). 아래는 실제 코드의 249~268행 발췌이며 앞뒤는 생략했습니다.

```python
paths = {b.field_path for b in blocks if b.field_path} | {'field_metadata'}
if 'date_range' in paths: paths.add('date_anchor')
raw = candidate.model_dump(mode='json')
initial = original.model_dump(mode='json')
# Project requested writable changes onto the original, then derive dependencies.
projected = original.model_dump(mode='json')
changes = _changed_paths(initial,raw)
for issued in sorted(paths,key=len):
    if any(_path_is_allowed(path,{issued}) for path in changes):
        set_plan_path(projected,issued,value_at_path(raw,issued))
if 'metric.kind' in paths and candidate.metric is None:
    projected['metric'] = None
projected = normalize_metric_dependencies(original,AnalysisPlan.model_validate(projected),catalog or {})
expected = projected.model_dump(mode='json')
forbidden = [path for path in _changed_paths(initial,raw)
             if not _path_is_allowed(path,paths) and value_at_path(raw,path) != value_at_path(expected,path)]
if forbidden:
    raise ValueError('analysis plan contains changes outside editable fields: '+', '.join(forbidden))
if not catalog:
    validate_choice_values(updated,blocks)
```

</details>

### 핵심 코드: _filter_id

필터 삭제에서 목록 순서나 표시 이름 대신 안정적인 대상을 사용합니다.

**동작:** source를 제외한 값을 정렬된 JSON으로 직렬화하고 SHA-256 앞 16자리를 반환합니다.

**설계:** 정규 JSON과 내용 기반 식별자입니다. 출처만 바뀌어도 같은 필터를 삭제·중복 판단할 수 있도록 합니다.

**예:** field/operator/value가 같고 source만 다르면 필터 ID는 같습니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/planning/a2ui/refinement.py](refinement.py#L109). 아래는 실제 코드의 109~116행 발췌이며 앞뒤는 생략했습니다.

```python
def _filter_id(filter_spec: Any) -> str:
    """필터 출처를 제외한 내용을 정렬해 해시하고 필터 비교·삭제에 쓸 안정적인 ID를 만든다."""

    payload = filter_spec.model_dump(mode="json") if hasattr(filter_spec, "model_dump") else filter_spec
    payload = dict(payload)
    payload.pop("source", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
```

</details>

### 다른 기능과 연결되는 순서

`review.refine_review_plan → refinement.refine_dynamic_analysis → _merge_refinement_patch → apply_plan_update`로 수정합니다. 카드 저장도 같은 apply_plan_update를 사용합니다. 저장은 불완전 초안을 허용하지만 최종 validate_ui_plan은 누락·미해결·조회 불가·질문 불일치를 차단합니다.

## 5. 구현 결과와 한계

**현재 구현:** 허용된 경로의 변경만 반영하며, 자연어 필터 수정에는 식별자를 사용합니다.

여기서 SQL은 실행하지 않습니다. 자연어 모델 연결 장애는 기존 계획을 유지하는 오류이고, 해석 실패는 미해결 조건으로 남을 수 있습니다. 클라이언트의 선택지나 카탈로그는 신뢰 근거로 사용하지 않고 서버 저장값을 적용합니다.

관련 검증: [test_refinement.py](../../../tests/a2ui/test_refinement.py), [test_review_update.py](../../../tests/a2ui/test_review_update.py).

<details>
<summary>파일 목록과 관련 문서 보기</summary>

### 보충 안내

Agent2UI 검토 화면 응답을 구성하고 자연어 추가 조건을 계획에 반영하며 허용된 편집 범위를 검사합니다.

### 주요 파일

| 파일 | 역할 |
|---|---|
| [models.py](models.py) | A2UI 검토 중 허용되는 추가 조건 수정 패치 모델. |
| [refinement.py](refinement.py) | A2UI 전용 자연어 추가 조건을 서버가 허용한 필드·필터 수정 패치로 반영한다. |
| [review.py](review.py) | A2UI 전용 검토 화면 응답 조립과 추가 조건 반영을 담당한다. |
| [validator.py](validator.py) | A2UI 전용 계획 확정 검증과 서버가 허용한 편집 범위 검사. |

### 함께 읽기

- [상위 폴더 안내](../README.md)
- [앱 전체 구조](../../README.md)
- [프로젝트 소개](../../../README.md)

</details>
