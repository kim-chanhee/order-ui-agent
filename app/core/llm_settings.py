"""SQL 에이전트가 쓸 OpenAI 호환 LLM 연결 값을 환경 변수에서 고른다.

호출처가 provider, base URL, API key, model, timeout을 한 번에 받도록
`resolve_agent_llm_settings`만 공개한다. 비밀 값은 여기서 로그하지 않는다.
"""

from __future__ import annotations

import os

_PROVIDER_ALIASES = {
    "lmstudio": "lm_studio",
    "local": "lm_studio",
    "openai_compatible": "openai",
}


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
