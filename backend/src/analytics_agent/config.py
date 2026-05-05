from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path
from typing import Annotated, Any, Literal


def get_config_dir() -> Path:
    """Return the active analytics-agent config directory.

    Checks ANALYTICS_AGENT_CONFIG_DIR env var first; falls back to
    ~/.datahub/analytics-agent/. Callers may resolve sub-paths from this.
    """
    return Path(
        os.environ.get("ANALYTICS_AGENT_CONFIG_DIR", "~/.datahub/analytics-agent")
    ).expanduser()


# Computed once at import time. ANALYTICS_AGENT_CONFIG_DIR must be set in the
# shell environment before import — not in .env — to affect these defaults.
_CONFIG_DIR = get_config_dir()

import yaml
from pydantic import BaseModel, Field, TypeAdapter
from pydantic_settings import BaseSettings, SettingsConfigDict


class EngineConfig(BaseModel):
    type: str
    name: str = ""
    connection: dict[str, Any] = Field(default_factory=dict)

    @property
    def effective_name(self) -> str:
        return self.name or self.type


class DataHubPlatformConfig(BaseModel):
    type: Literal["datahub"] = "datahub"
    name: str = "default"
    label: str = ""
    url: str = ""
    token: str = ""


class DataHubMCPConfig(BaseModel):
    type: Literal["datahub-mcp"] = "datahub-mcp"
    name: str = "default"
    label: str = ""
    transport: Literal["http", "sse", "stdio"] = "http"
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


ContextPlatformConfig = Annotated[
    DataHubPlatformConfig | DataHubMCPConfig,
    Field(discriminator="type"),
]

_PLATFORM_ADAPTER: TypeAdapter[DataHubPlatformConfig | DataHubMCPConfig] = TypeAdapter(
    ContextPlatformConfig  # type: ignore[arg-type]
)


def parse_platform_config(cfg: dict) -> DataHubPlatformConfig | DataHubMCPConfig:
    """Parse a stored config dict into a typed platform config.

    Handles the legacy _mcp blob format transparently so old DB rows
    continue to work without a data migration.
    """
    # Strip internal metadata keys before parsing
    base = {k: v for k, v in cfg.items() if not k.startswith("_")}

    # Legacy rows (seeded before the type discriminator was introduced) have no
    # "type" key — default to "datahub" so the discriminated union can parse them.
    if "type" not in base:
        base["type"] = "datahub"

    # Legacy format: MCP config stored as JSON blob under _mcp key
    if "_mcp" in cfg:
        import json as _json

        mcp: dict = {}
        with contextlib.suppress(Exception):
            raw = cfg["_mcp"]
            mcp = _json.loads(raw) if isinstance(raw, str) else raw
        base = {
            "type": "datahub-mcp",
            "transport": mcp.get("transport", "http"),
            "url": mcp.get("url", ""),
            "headers": mcp.get("headers") or {},
            "command": mcp.get("command", ""),
            "args": mcp.get("args") or [],
            "env": mcp.get("env") or {},
        }

    with contextlib.suppress(Exception):
        return _PLATFORM_ADAPTER.validate_python(base)
    # Unknown type — fall back to a bare native config
    return DataHubPlatformConfig(type="datahub")


class AnalyticsAgentYamlConfig(BaseModel):
    engines: list[EngineConfig] = Field(default_factory=list)
    context_platforms: list[ContextPlatformConfig] = Field(default_factory=list)  # type: ignore[valid-type]


# Default models per provider per tier.
# Adding a new provider means adding one entry here — nowhere else in config.py.
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "anthropic": {
        "main": "claude-sonnet-4-6",
        "chart": "claude-haiku-4-5-20251001",
        "quality": "claude-haiku-4-5-20251001",
        "delight": "claude-haiku-4-5-20251001",
    },
    "openai": {
        "main": "gpt-4o",
        "chart": "gpt-4o-mini",
        "quality": "gpt-4o-mini",
        "delight": "gpt-4o-mini",
    },
    "google": {
        "main": "gemini-2.0-flash",
        "chart": "gemini-1.5-flash",
        "quality": "gemini-1.5-flash",
        "delight": "gemini-1.5-flash",
    },
    "bedrock": {
        "main": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "chart": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "quality": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "delight": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    },
    # OpenAI-compatible proxy (LiteLLM, vLLM, Ollama, etc.).
    # No curated model list — available models depend on the proxy configuration.
    "openai-compatible": {
        "main": "",
        "chart": "",
        "quality": "",
        "delight": "",
    },
}

# Env var name that holds the API key for each provider.
PROVIDER_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openai-compatible": "OPENAI_COMPAT_API_KEY",
}

# Settings attribute name for each provider's API key.
PROVIDER_KEY_ATTR: dict[str, str] = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "google": "google_api_key",
    "openai-compatible": "openai_compat_api_key",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # DataHub — fallback when config.yaml has no context_platforms entry
    datahub_gms_url: str = "http://localhost:8080"
    datahub_gms_token: str = ""

    # LLM provider — must be a key in PROVIDER_DEFAULTS above
    llm_provider: str = "openai"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    # OpenAI-compatible proxy (LiteLLM, vLLM, Ollama, etc.)
    openai_compat_base_url: str = ""  # OPENAI_COMPAT_BASE_URL
    openai_compat_api_key: str = ""  # OPENAI_COMPAT_API_KEY

    # Bedrock — uses the standard AWS credential chain by default (env vars,
    # ~/.aws/credentials, IAM role). Set the explicit *_key_id/*_access_key
    # settings to override.
    aws_region: str = "us-west-2"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""
    # Anthropic + Bedrock prompt caching (system prompt + tool definitions).
    # Disable if you hit a Bedrock region/model where caching isn't supported.
    enable_prompt_cache: bool = True
    # Model IDs — override any tier independently via env vars.
    # Unset tiers fall back to PROVIDER_DEFAULTS[llm_provider][tier].
    llm_model: str = ""  # LLM_MODEL         — main analysis agent
    chart_llm_model: str = ""  # CHART_LLM_MODEL   — Vega-Lite chart generation
    quality_llm_model: str = ""  # QUALITY_LLM_MODEL — context quality assessment
    delight_llm_model: str = ""  # DELIGHT_LLM_MODEL — titles, greetings

    def _default_model(self, tier: str) -> str:
        provider_defaults = PROVIDER_DEFAULTS.get(self.llm_provider, PROVIDER_DEFAULTS["openai"])
        return provider_defaults[tier]

    def get_llm_model(self) -> str:
        return self.llm_model or self._default_model("main")

    def get_chart_llm_model(self) -> str:
        return self.chart_llm_model or self._default_model("chart")

    def get_quality_llm_model(self) -> str:
        return self.quality_llm_model or self._default_model("quality")

    def get_delight_llm_model(self) -> str:
        return self.delight_llm_model or self._default_model("delight")

    def get_api_key(self) -> str:
        """Return the configured API key for the active provider."""
        attr = PROVIDER_KEY_ATTR.get(self.llm_provider, "")
        return getattr(self, attr, "") if attr else ""

    # Database — defaults to the user config dir; override via DATABASE_URL env var
    database_url: str = f"sqlite+aiosqlite:///{_CONFIG_DIR}/data/agent.db"

    # Engine config — defaults to the user config dir; override via ENGINES_CONFIG env var
    engines_config: str = str(_CONFIG_DIR / "config.yaml")
    sql_row_limit: int = 500

    # App
    log_level: str = "INFO"
    sse_keepalive_interval: int = 15
    agent_recursion_limit: int = 50
    # Token budget for reconstructed chat history sent to the LLM.
    # Leaves ~80K headroom for system prompt, tool definitions, and response
    # within the 200K Claude context window. Override via MAX_HISTORY_TOKENS env var.
    max_history_tokens: int = 800_000

    # Testing — when set, MCPContextPlatform.get_tools() returns a static stub list
    # instead of connecting to the real server.  Set to "1" in e2e test environments.
    mock_mcp_tools: bool = False

    # Telemetry — anonymous usage metrics. Set DATAHUB_TELEMETRY_ENABLED=false to opt out.
    datahub_telemetry_enabled: bool = True

    # OAuth SSO (all integrations share one master encryption key)
    oauth_master_key: str = (
        ""  # Fernet key for encrypting OAuth secrets/tokens; auto-generated if blank
    )

    def _load_yaml(self) -> AnalyticsAgentYamlConfig:
        path = Path(self.engines_config)
        if not path.exists():
            return AnalyticsAgentYamlConfig()
        raw = path.read_text()
        raw = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), raw)
        data = yaml.safe_load(raw) or {}
        return AnalyticsAgentYamlConfig.model_validate(data)

    def load_engines_config(self) -> list[EngineConfig]:
        return self._load_yaml().engines

    def load_context_platforms_config(self) -> list[ContextPlatformConfig]:
        return self._load_yaml().context_platforms

    def get_datahub_config(self) -> tuple[str, str]:
        """Return (url, token) for DataHub — config.yaml wins, falls back to env vars."""
        for plat in self.load_context_platforms_config():
            if isinstance(plat, DataHubPlatformConfig):
                return plat.url, plat.token
        return self.datahub_gms_url, self.datahub_gms_token


settings = Settings()
