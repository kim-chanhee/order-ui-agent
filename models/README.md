# Local model

> **한눈에 보기** · 앱을 LM Studio의 로컬 모델 서버에 연결하는 방법과 제약을 설명합니다. 모델 파일은 LM Studio가 실행하고 앱은 HTTP로 요청합니다.

**기본 흐름:** 로컬 모델 서버 실행 → 앱 연결 설정 → 모델 호출

- Model: Qwen2.5-Coder-7B-Instruct
- File: `qwen2.5-coder-7b-instruct-q4_k_m.gguf`
- Quantization: Q4_K_M
- SHA-256: `509287f78cb4d4cf6b3843734733b914b2c158e43e22a7f4bf5e963800894d3c`
- Source: https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF

The GGUF file is excluded from Git. LM Studio also retains the original downloaded file; this folder contains a copy.

## Run with LM Studio

The model must be loaded and the local server running before starting the application:

```sh
lms load qwen2.5-coder-7b-instruct --identifier qwen2.5-coder-7b-instruct --context-length 32768 --gpu max --yes
lms server start --port 1234
```

Project `.env` settings:

```dotenv
AGENT_PROVIDER=lm_studio
AGENT_BASE_URL=http://127.0.0.1:1234/v1
AGENT_API_KEY=not-needed
AGENT_MODEL=qwen2.5-coder-7b-instruct
AGENT2UI_PLANNER_MODEL=qwen2.5-coder-7b-instruct
AGENT_TIMEOUT_SECONDS=180
FAST_SQL_TIMEOUT_SECONDS=120
FAST_SQL_TOTAL_TIMEOUT_SECONDS=240
```

Restart the application after changing settings. Routing, planning, SQL generation, and response generation share the local endpoint. The structured routing/planning adapter uses `tool_choice="required"` because this LM Studio runtime rejects a named tool-choice object. Plan validation remains enabled.

The current planner can exceed 23,000 prompt tokens, so 16K context is insufficient. Larger context does not guarantee that a 7B model will produce a valid or correct plan. See `artifacts/local-baseline-20261101` for development test results, including failures. These are smoke tests, not a controlled study or a reproduction of another paper's reported accuracy.

## 핵심 개념과 동작

로컬 모델 경로는 OpenAI 호환 HTTP 어댑터를 공유합니다. 모델 가중치 자체를 Python 코드에서 직접 로드하지 않으며, LM Studio가 제공하는 엔드포인트에 LangChain 클라이언트로 접근합니다. 공급자별 structured output 지원 차이는 공통 옵션으로 처리합니다.

### 주요 함수·클래스

| 함수·클래스 | 구체적인 역할 | 관련 기술 |
|---|---|---|
| `resolve_agent_llm_settings` | 로컬 URL·키·모델·시간 제한 선택 | 호환 HTTP 클라이언트 |
| `structured_output_options` | required 방식의 Tool 선택 옵션 | 전송 호환성 |

### 핵심 코드: resolve_agent_llm_settings

로컬 공급자를 같은 모델 호출 계약에 연결합니다.

**동작:** provider를 정규화하고 lm_studio일 때 URL·API 키·모델 이름과 timeout을 반환합니다.

**설계:** 모델 서버와 앱 프로세스의 분리입니다. 라우터·planner·SQL이 각기 다른 연결 설정을 사용하는 문제를 줄입니다.

**예:** AGENT_PROVIDER=lm_studio이고 URL 미설정이면 localhost:1234/v1이 기본값입니다.

<details>
<summary>실제 코드와 원본 위치 보기</summary>

원본: [app/core/llm_settings.py](../app/core/llm_settings.py#L51). 아래는 실제 코드의 51~64행 발췌이며 앞뒤는 생략했습니다.

```python
provider = _normalized_provider()
timeout = float(_env("AGENT_TIMEOUT_SECONDS", default="120"))

if provider == "lm_studio":
    return (
        provider,
        _env("AGENT_BASE_URL", "LM_STUDIO_BASE_URL", default="http://127.0.0.1:1234/v1").rstrip("/"),
        _env("AGENT_API_KEY", "LM_STUDIO_API_KEY", default="not-needed"),
        _env("AGENT_MODEL", default="local-model"),
        timeout,
    )

if provider == "openai":
    api_key = _env("OPENAI_API_KEY", "AGENT_API_KEY")
```

</details>

### 다른 기능과 연결되는 순서

LM Studio의 로컬 HTTP 서버 → core.llm_settings → routing/planning/SQL/reply 클라이언트로 연결됩니다. GGUF 파일의 존재만으로 서버 준비나 Tool Calling 지원이 증명되는 것은 아닙니다.

### 확인한 범위와 한계

기존 23,000 토큰·16K 문맥 관련 문구는 개발 당시 입력에 대한 관찰이며 모든 현재 요청의 고정 크기 기준이 아닙니다. 전송 테스트는 실제 로컬 모델의 의미 정확도나 처리 속도를 측정하지 않습니다.

관련 검증: [test_local_llm_transport.py](../tests/test_local_llm_transport.py).
