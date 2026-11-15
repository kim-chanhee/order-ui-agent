# `app/core` · 모델 연결 설정과 시작 점검

> **한눈에 보기** · 어떤 모델과 DB를 사용할지 정하고, 모델 호출 제한과 사용량을 관리합니다. 여러 기능이 같은 설정을 사용하도록 모읍니다.

**기본 흐름:** 설정 읽기 → 모델·데이터 선택 → 호출 제한·사용량 관리

환경 변수에서 LLM 연결 설정을 읽고 앱 기동에 필요한 DB·상태 저장소·실험 설정을 점검합니다.

## 주요 파일

| 파일 | 역할 |
|---|---|
| [llm_settings.py](llm_settings.py) | SQL 에이전트가 쓸 OpenAI 호환 LLM 연결 값을 환경 변수에서 고른다. |
| [model_errors.py](model_errors.py) | 공급자 오류를 분류하고 일시적 오류만 제한 재시도한다. |
| [llm_usage.py](llm_usage.py) | 요청별 호출 상한과 실제 보고 토큰을 관리한다. 프롬프트·키는 기록하지 않는다. |
| [startup_checks.py](startup_checks.py) | 앱 기동 시 로컬 자원이 쓸 수 있는지 검사한다. |

## 핵심 개념과 동작

Structured Output은 **모델의 답을 정해진 데이터 형식으로 받는 방식**입니다. 모델 공급자마다 지원 방식이 달라 공통 설정에서 이를 맞춥니다.

요청별 사용량은 ContextVar로 따로 집계합니다. 여러 요청이 동시에 처리되어도 각 요청의 기록을 구분하기 위한 장치입니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `structured_output_options` | 공급자에 맞는 구조화 응답 옵션 선택 | JSON Schema / Tool Calling |
| `chat_model_kwargs` | 출력 상한·사용량 callback·재시도 옵션 구성 | 공통 모델 어댑터 |
| `UsageCallback` | 모델 호출 시작 전 한도와 입력 크기 검사 | ContextVar |
| `apply_data_profile` | DB와 의미 설정을 함께 선택 | 원자적 설정 적용 |
| `run_startup_checks` | DB·상태 저장·과제·의미 설정 점검 | 시작 단계에서 오류 확인 |

### 핵심 코드: structured_output_options

공급자별 지원 차이를 각 호출처가 반복 처리하지 않도록 합니다.

**동작:** strict OpenAI 경로는 JSON Schema, 그 외에는 function calling을 사용하고 LM Studio에는 required를 설정합니다.

**설계:** 공급자 적응형 Structured Output입니다. 응답 모델 선언과 실제 전송 프로토콜이 일치하도록 합니다.

**예:** strict=True이고 OpenAI이면 method=json_schema와 strict=True가 반환됩니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/core/llm_settings.py](llm_settings.py#L18). 아래는 실제 코드의 18~26행 발췌이며 앞뒤는 생략했습니다.

```python
def structured_output_options(*, strict: bool = False) -> dict:
    """LM Studio는 이름을 지정한 tool_choice 대신 required 문자열을 받는다."""

    if strict and _normalized_provider() == "openai":
        return {"method": "json_schema", "strict": True}
    options = {"method": "function_calling"}
    if _normalized_provider() == "lm_studio":
        options["tool_choice"] = "required"
    return options
```

</details>

### 핵심 코드: apply_data_profile

새 DB에 예전 업무 설정이 섞이지 않도록 합니다.

**동작:** 모든 파일 존재와 상태 DB 분리를 검증한 뒤 환경 변수를 한 번에 업데이트합니다.

**설계:** 검증 후 commit에 해당하는 설정 적용 패턴입니다. 일부 경로만 바뀌어 서로 다른 도메인의 설정이 혼합되는 것을 방지합니다.

**예:** 잘못된 profile.json이면 ORDER_UI_DB_PATH를 포함한 기존 설정을 부분 변경하지 않습니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/core/data_profile.py](data_profile.py#L28). 아래는 실제 코드의 28~40행 발췌이며 앞뒤는 생략했습니다.

```python
resolved = {}
for key, env in PROFILE_FIELDS.items():
    value = Path(payload[key]).expanduser()
    value = (source.parent / value).resolve() if not value.is_absolute() else value.resolve()
    if key != 'state_database' and not value.is_file():
        raise ValueError(f'Data profile file is missing: {key}')
    resolved[env] = str(value)
if resolved['ORDER_UI_DB_PATH'] == resolved['ORDER_UI_STATE_DB_PATH']:
    raise ValueError('Query database and state database must be separate')
# Apply atomically after validation. One selection overrides stale per-file
# settings together, so a new database never inherits the old domain docs.
os.environ.update(resolved)
return payload
```

</details>

### 다른 기능과 연결되는 순서

`server.load_dotenv → database.apply_data_profile → 설정 모듈 초기화 → lifespan.run_startup_checks` 순서입니다. 모델 호출은 chat_model_kwargs의 callback을 사용하며 track_llm_request는 같은 요청 안에서 중첩되면 기존 계측 범위를 재사용합니다.

### 확인한 범위와 한계

한도는 요청 수·입력 크기·출력 토큰에 대한 제한이며 금액 예산 보장은 아닙니다. 공급자의 usage 응답 누락은 usage_complete로 구분합니다. 시작 점검은 네트워크 모델 호출을 수행하지 않아 API 연결 품질을 확인하지는 않습니다.

관련 검증: [test_data_profile.py](../../tests/test_data_profile.py), [test_llm_usage.py](../../tests/test_llm_usage.py), [test_gpt_structured_transport.py](../../tests/test_gpt_structured_transport.py), [test_local_llm_transport.py](../../tests/test_local_llm_transport.py), [test_model_errors.py](../../tests/test_model_errors.py).

## 함께 읽기

- [앱 전체 구조](../README.md)
- [프로젝트 소개](../../README.md)
