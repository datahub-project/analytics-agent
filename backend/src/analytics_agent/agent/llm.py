from __future__ import annotations

from collections.abc import Callable

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr

from analytics_agent.config import settings

# ── Per-provider factory functions ────────────────────────────────────────────


def _make_anthropic(model: str, streaming: bool) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    kwargs: dict = {"model_name": model, "streaming": streaming}
    if settings.anthropic_api_key:
        kwargs["api_key"] = SecretStr(settings.anthropic_api_key)
    return ChatAnthropic(**kwargs)  # type: ignore[call-arg]


def _make_openai(model: str, streaming: bool) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    kwargs: dict = {"model": model, "temperature": 0, "streaming": streaming}
    if settings.openai_api_key:
        kwargs["api_key"] = SecretStr(settings.openai_api_key)
    return ChatOpenAI(**kwargs)


def _make_google(model: str, streaming: bool) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    kwargs: dict = {"model": model, "streaming": streaming}
    if settings.google_api_key:
        kwargs["google_api_key"] = SecretStr(settings.google_api_key)
    return ChatGoogleGenerativeAI(**kwargs)


def _make_bedrock(model: str, streaming: bool) -> BaseChatModel:
    from langchain_aws import ChatBedrockConverse

    kwargs: dict = {"model": model, "region_name": settings.aws_region}
    # Explicit creds override the default AWS credential chain when provided.
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = SecretStr(settings.aws_access_key_id)
        kwargs["aws_secret_access_key"] = SecretStr(settings.aws_secret_access_key)
        if settings.aws_session_token:
            kwargs["aws_session_token"] = SecretStr(settings.aws_session_token)
    return ChatBedrockConverse(**kwargs)


def _api_key_from_headers(headers: dict) -> str:
    """Extract an API key from an Authorization header, stripping the Bearer prefix."""
    auth_value = headers.get("Authorization", "")
    if not auth_value:
        return ""
    return auth_value[7:] if auth_value.startswith("Bearer ") else auth_value


def _build_openai_compatible(
    model: str,
    url: str,
    headers: dict,
    *,
    api_key: str = "",
    streaming: bool = False,
    max_tokens: int | None = None,
) -> BaseChatModel:
    """Construct a ChatOpenAI instance pointed at an OpenAI-compatible endpoint."""
    from langchain_openai import ChatOpenAI

    effective_api_key = _api_key_from_headers(headers) or api_key
    kwargs: dict = {
        "model": model,
        "base_url": url.rstrip("/"),
        "api_key": SecretStr(effective_api_key or ""),
        "streaming": streaming,
        "temperature": 0,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if headers:
        kwargs["default_headers"] = {str(k): str(v) for k, v in headers.items()}
    return ChatOpenAI(**kwargs)


def _make_openai_compatible(model: str, streaming: bool) -> BaseChatModel:
    import json

    url = settings.openai_compatible_base_url
    if not url:
        raise ValueError("OPENAI_COMPATIBLE_BASE_URL is required for the openai-compatible provider")

    headers = {}
    if settings.openai_compatible_headers:
        try:
            headers = json.loads(settings.openai_compatible_headers)
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Invalid OPENAI_COMPATIBLE_HEADERS JSON: {e}")

    return _build_openai_compatible(
        model,
        url,
        headers,
        api_key=settings.openai_compatible_api_key,
        streaming=streaming,
    )


# Registry — adding a provider means adding one entry here.
_FACTORIES: dict[str, Callable[[str, bool], BaseChatModel]] = {
    "anthropic": _make_anthropic,
    "openai": _make_openai,
    "google": _make_google,
    "bedrock": _make_bedrock,
    "openai-compatible": _make_openai_compatible,
}


def _make_llm(model: str, streaming: bool = False) -> BaseChatModel:
    factory = _FACTORIES.get(settings.llm_provider)
    if factory is None:
        raise ValueError(
            f"Unknown LLM provider {settings.llm_provider!r}. Valid providers: {sorted(_FACTORIES)}"
        )
    return factory(model, streaming)


# ── Public accessors (one per model tier) ─────────────────────────────────────


def get_llm(streaming: bool = True) -> BaseChatModel:
    return _make_llm(settings.get_llm_model(), streaming=streaming)


def get_chart_llm() -> BaseChatModel:
    return _make_llm(settings.get_chart_llm_model())


def get_quality_llm() -> BaseChatModel:
    return _make_llm(settings.get_quality_llm_model())


def get_delight_llm() -> BaseChatModel:
    return _make_llm(settings.get_delight_llm_model())
