# 자동 검증의 구성과 증거 범위

## 1. 이 폴더의 역할

> **한눈에 보기** · 자동 테스트가 무엇을 확인하는지 정리합니다. Python과 JavaScript 테스트는 실제 모델 평가나 브라우저 전체 검사와 범위가 다릅니다.

**기본 흐름:** 임시 데이터·대체 모델 준비 → 기능 실행 → 기대 결과와 비교

## 2. 해결하려는 문제

테스트 통과를 실제 모델 정확도나 브라우저 전체 동작의 보장으로 오해할 수 있습니다. 테스트 종류와 확인하는 범위를 나눠 설명합니다.

## 3. 핵심 기술

테스트 증거는 계층별로 구분합니다. Python은 pytest로 자료형·계약·편집·라우팅·공급자 전송 옵션을 검증하고, JavaScript는 Node 내장 테스트로 순수 함수를 검증합니다. 임시 DB·대체 모델을 사용하는 테스트와 실제 모델/브라우저 측정은 서로 다릅니다.

## 4. 핵심 함수와 실제 코드

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `pytest fixtures` | 임시 DB·설정·모델 격리 | 테스트 의존성 주입 |
| `monkeypatch` | 외부 호출·환경을 대체 | 격리된 검증 |
| `node:test` | 계획·결과 순수 함수 회귀 검사 | JavaScript 단위 테스트 |

### 핵심 코드: test_invalid_profile_does_not_partially_replace_environment

프로필 적용 실패가 기존 실행 설정을 부분 변경하지 않는지 확인합니다.

**동작:** 잘못된 프로필을 쓰고 기존 DB 환경을 지정한 뒤 예외와 환경값 유지 여부를 assert합니다.

**설계:** 임시 파일과 monkeypatch 기반 회귀 테스트입니다. 실패 경로를 재현해 설정 원자성의 근거를 제공합니다.

**예:** 누락된 필수 필드이면 ValueError이고 ORDER_UI_DB_PATH는 original입니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [tests/test_data_profile.py](test_data_profile.py#L33). 아래는 실제 코드의 33~37행 발췌이며 앞뒤는 생략했습니다.

```python
def test_invalid_profile_does_not_partially_replace_environment(tmp_path,monkeypatch):
    path=tmp_path/'profile.json';path.write_text(json.dumps({'version':1,'database':'missing'}))
    monkeypatch.setenv('ORDER_UI_DB_PATH','original')
    with pytest.raises(ValueError):apply_data_profile(path)
    assert os.environ['ORDER_UI_DB_PATH']=='original'
```

</details>

### 다른 기능과 연결되는 순서

하위 [execution](execution/README.md), [계획·검토](a2ui/README.md), [JS](js/README.md) 문서가 구체적 검증 범위를 설명합니다.

```bash
uv run pytest -q
node --test tests/js/*.test.js
```

## 5. 구현 결과와 한계

**현재 구현:** 임시 DB와 대체 응답을 사용해 Python 기능을 확인하고 Node에서 화면 관련 순수 함수를 검사합니다.

테스트 통과 수는 자연어 정확도·처리량·통계 유의성의 지표가 아닙니다. 현재 브라우저 전체 사용자 흐름과 실제 모델의 일관된 정답률을 자동 검증한 것으로 표현하지 않습니다.

관련 검증: [test_data_profile.py](test_data_profile.py), [test_llm_usage.py](test_llm_usage.py), [test_turn_router.py](test_turn_router.py).
