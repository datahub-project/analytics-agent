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


def _make_openai_compat(model: str, streaming: bool) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    if not settings.openai_compat_base_url:
        raise ValueError("OPENAI_COMPAT_BASE_URL is required for the openai-compatible provider")
    kwargs: dict = {
        "model": model,
        "temperature": 0,
        "streaming": streaming,
        "base_url": settings.openai_compat_base_url,
    }
    # API key is optional — some proxies use network-level auth or no auth.
    api_key = settings.openai_compat_api_key or "no-key"
    kwargs["api_key"] = SecretStr(api_key)
    return ChatOpenAI(**kwargs)


# Registry — adding a provider means adding one entry here.
_FACTORIES: dict[str, Callable[[str, bool], BaseChatModel]] = {
    "anthropic": _make_anthropic,
    "openai": _make_openai,
    "google": _make_google,
    "bedrock": _make_bedrock,
    "openai-compatible": _make_openai_compat,
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
