# `app/a2ui` · 서버의 화면 전송 모델

> **한눈에 보기** · 서버가 화면에 무엇을 보여줄지 데이터로 정합니다. 브라우저는 이 데이터를 받아 미리 준비된 화면 요소를 그립니다.

**기본 흐름:** 계획·조회 결과 → 화면 데이터(Surface) → 브라우저 표시

분석 계획과 조회 결과를 브라우저가 렌더링할 화면 데이터로 변환합니다. 컴포넌트 종류·동작·클라이언트 지원 기능을 정의합니다.

[화면 전송 모델의 UI 예시](../../docs/system-guide.md#분석-계획에서-확인-ui로)

## 주요 파일

| 파일 | 역할 |
|---|---|
| [adapter.py](adapter.py) | 두 모드의 조회 결과를 공통 A2UI 화면 형식으로 변환한다. |
| [catalog.py](catalog.py) | 지원 UI 컴포넌트와 클라이언트 기능 선언. |
| [models.py](models.py) | 화면·컴포넌트·액션·지원 기능의 Pydantic 전송 모델. |
| [review.py](review.py) | A2UI 전용 검토 계획을 화면 데이터로 변환하고 저장한다. |

## 핵심 개념과 동작

Surface는 서버가 보내는 **화면 설명 데이터**입니다. Component는 선택 상자나 표처럼 화면을 이루는 요소입니다.

서버는 실행할 HTML 대신 JSON 데이터를 보냅니다. 브라우저가 지원하는 요소와 서버에 등록된 요소 중에서 사용할 것을 고릅니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `A2UISurface` | 화면 ID·revision·데이터·컴포넌트·액션 모델 | Pydantic 전송 모델 |
| `analysis_result_to_surface` | 두 모드 결과를 같은 화면 계약으로 변환 | 결과 어댑터 |
| `schema_review_surface` | UiBlock을 편집 액션이 있는 컴포넌트로 변환 | 선언형 UI |
| `surface_for_plan` | 서버가 발급한 계획과 화면을 함께 저장 | 권위 상태 |
| `_supported_type` | 지원하지 않는 유형의 대체 표현 선택 | 지원하는 화면 요소로 대체 |

### 핵심 코드: _supported_type

클라이언트가 모르는 컴포넌트 때문에 전체 결과 표시가 실패하지 않도록 합니다.

**동작:** 지원 유형이면 그대로 쓰고 아니면 카탈로그 대체형과 안전한 지원 유형을 고른 뒤 변환 내역을 남깁니다.

**설계:** Capability negotiation의 제한된 구현입니다. 계획/결과 데이터와 렌더러 지원 차이를 분리합니다.

**예:** bar_chart가 없고 table이 지원되면 카탈로그 규칙에 따라 table 등으로 대체됩니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/a2ui/adapter.py](adapter.py#L88). 아래는 실제 코드의 88~98행 발췌이며 앞뒤는 생략했습니다.

```python
def _supported_type(component_type: str, supported: set[str], fallbacks: list[dict[str, str]]) -> str:
    if component_type in supported:
        return component_type
    fallback = COMPONENT_FALLBACKS.get(component_type, "review")
    if fallback not in supported:
        fallback = next(
            (candidate for candidate in ("text", "review", "notice", "table") if candidate in supported),
            sorted(supported)[0],
        )
    fallbacks.append({"from": component_type, "to": fallback})
    return fallback
```

</details>

### 다른 기능과 연결되는 순서

planning의 UiPlan은 review.schema_review_surface를 거쳐 계획 Surface가 되고, 실행 결과는 adapter.analysis_result_to_surface를 거쳐 결과 Surface가 됩니다. 브라우저의 js/surfaces/runtime.js가 이를 검증·렌더링합니다.

### 확인한 범위와 한계

이름은 Agent2UI이지만 외부 A2UI 규격과 완전 호환을 검증한 구현은 아닙니다. 지원 목록은 표현 능력에 대한 정보이며 권한·SQL 실행 허가가 아닙니다. 자료형 검증과 런타임 렌더링 검증 범위도 다릅니다.

관련 검증: [test_sql_tools.py](../../tests/execution/test_sql_tools.py), [test_review_update.py](../../tests/a2ui/test_review_update.py).

## 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)
