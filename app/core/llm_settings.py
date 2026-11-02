"""SQL 에이전트가 쓸 OpenAI 호환 LLM 연결 값을 환경 변수에서 고른다.

호출처가 provider, base URL, API key, model, timeout을 한 번에 받도록
접속 값과 구조화 응답 옵션을 제공한다. 비밀 값은 여기서 로그하지 않는다.
"""

from __future__ import annotations

import os

_PROVIDER_ALIASES = {
    "lmstudio": "lm_studio",
    "local": "lm_studio",
    "openai_compatible": "openai",
}


def structured_output_options(*, strict: bool = False) -> dict:
    """LM Studio는 이름을 지정한 tool_choice 대신 required 문자열을 받는다."""

    if strict and _normalized_provider() == "openai":
        return {"method": "json_schema", "strict": True}
    options = {"method": "function_calling"}
    if _normalized_provider() == "lm_studio":
        options["tool_choice"] = "required"
    return options


def _env(*names: str, default: str = "") -> str:
    """앞에서부터 비어 있지 않은 환경 변수 값을 고른다."""

    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _normalized_provider() -> str:
    """AGENT_PROVIDER가 비어 있거나 auto이면 OpenAI 키 유무로 공급자를 고른다."""

    provider = _env("AGENT_PROVIDER").lower()
    if provider in {"", "auto"}:
        return "openai" if _env("OPENAI_API_KEY", "AGENT_API_KEY") else "lm_studio"
    return _PROVIDER_ALIASES.get(provider, provider)


def resolve_agent_llm_settings() -> tuple[str, str, str, str, float]:
    """provider, base URL, API key, model, timeout을 반환한다."""

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
        if not api_key:
            raise RuntimeError("AGENT_PROVIDER=openai but OPENAI_API_KEY is not set")
        return (
            provider,
            _env("AGENT_BASE_URL", "OPENAI_BASE_URL").rstrip("/"),
            api_key,
            _env("AGENT_MODEL", default="gpt-4.1-mini"),
            timeout,
        )

    raise ValueError(f"Unsupported AGENT_PROVIDER: {provider}")


def chat_model_kwargs(purpose: str, *, settings=None, model: str | None = None, timeout=None, max_tokens: int | None = None) -> dict:
    """모든 단계에 같은 공급자·재시도 정책·출력 상한·사용량 계측을 적용한다."""
    from app.core.llm_usage import UsageCallback
    _, base_url, api_key, configured_model, configured_timeout = settings or resolve_agent_llm_settings()
    selected = model or configured_model
    limits = {'routing': 700, 'planner': 4000, 'reply': 700, 'sql': 1600}
    limit = max_tokens or int(_env(f'LLM_{purpose.upper()}_MAX_OUTPUT_TOKENS', default=str(limits[purpose])))
    if limit < 1:
        raise ValueError('LLM output token limit must be positive')
    kwargs = {'model': selected, 'api_key': api_key, 'timeout': timeout or configured_timeout,
              'max_retries': 0, 'max_completion_tokens': limit, 'callbacks': [UsageCallback(purpose, selected)]}
    if base_url:
        kwargs['base_url'] = base_url
    if not selected.startswith(('gpt-5', 'gpt-6')):
        kwargs['temperature'] = 0
    return kwargs
