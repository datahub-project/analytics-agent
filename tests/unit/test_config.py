import textwrap

from analytics_agent.config import (
    AnalyticsAgentYamlConfig,
    DataHubPlatformConfig,
    EngineConfig,
    Settings,
)


def test_engine_config_defaults():
    cfg = EngineConfig(type="snowflake")
    assert cfg.type == "snowflake"
    assert cfg.name == ""
    assert cfg.connection == {}
    assert cfg.effective_name == "snowflake"


def test_engine_config_effective_name_uses_name_when_set():
    cfg = EngineConfig(type="snowflake", name="prod")
    assert cfg.effective_name == "prod"


def test_context_platform_config_defaults():
    plat = DataHubPlatformConfig(type="datahub")
    assert plat.type == "datahub"
    assert plat.name == "default"
    assert plat.url == ""
    assert plat.token == ""


def test_context_platform_config_full():
    plat = DataHubPlatformConfig(
        type="datahub", name="staging", url="https://dh.example.com/gms", token="tok123"
    )
    assert plat.url == "https://dh.example.com/gms"
    assert plat.token == "tok123"


def test_yaml_config_parse():
    data = {
        "engines": [{"type": "snowflake", "name": "prod", "connection": {"account": "xy12345"}}],
        "context_platforms": [
            {"type": "datahub", "name": "default", "url": "http://localhost:8080", "token": "t"}
        ],
    }
    cfg = AnalyticsAgentYamlConfig.model_validate(data)
    assert len(cfg.engines) == 1
    assert cfg.engines[0].type == "snowflake"
    assert cfg.engines[0].connection["account"] == "xy12345"
    assert len(cfg.context_platforms) == 1
    assert cfg.context_platforms[0].url == "http://localhost:8080"


def test_yaml_config_empty():
    cfg = AnalyticsAgentYamlConfig.model_validate({})
    assert cfg.engines == []
    assert cfg.context_platforms == []


def test_load_yaml_missing_file(tmp_path):
    settings = Settings(
        engines_config=str(tmp_path / "nonexistent.yaml"),
        database_url="sqlite+aiosqlite:///./test.db",
    )
    assert settings.load_engines_config() == []
    assert settings.load_context_platforms_config() == []


def test_env_var_substitution(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAHUB_GMS_URL", "https://dh.example.com/gms")
    monkeypatch.setenv("DATAHUB_GMS_TOKEN", "mytoken")

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        textwrap.dedent("""\
        context_platforms:
          - type: datahub
            name: default
            url: "${DATAHUB_GMS_URL}"
            token: "${DATAHUB_GMS_TOKEN}"
        """)
    )
    settings = Settings(
        engines_config=str(config_file), database_url="sqlite+aiosqlite:///./test.db"
    )
    platforms = settings.load_context_platforms_config()
    assert len(platforms) == 1
    assert platforms[0].url == "https://dh.example.com/gms"
    assert platforms[0].token == "mytoken"


def test_get_datahub_config_from_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAHUB_GMS_URL", "http://env-url/gms")
    monkeypatch.setenv("DATAHUB_GMS_TOKEN", "env-token")

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        textwrap.dedent("""\
        context_platforms:
          - type: datahub
            name: default
            url: "https://yaml-url/gms"
            token: "yaml-token"
        """)
    )
    settings = Settings(
        engines_config=str(config_file), database_url="sqlite+aiosqlite:///./test.db"
    )
    url, token = settings.get_datahub_config()
    assert url == "https://yaml-url/gms"
    assert token == "yaml-token"


def test_get_datahub_config_fallback_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAHUB_GMS_URL", "http://env-url/gms")

    config_file = tmp_path / "config.yaml"
    config_file.write_text("engines: []\n")

    settings = Settings(
        engines_config=str(config_file), database_url="sqlite+aiosqlite:///./test.db"
    )
    url, _ = settings.get_datahub_config()
    assert url == "http://env-url/gms"


def test_load_engines_config_substitutes_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "xy12345")
    monkeypatch.setenv("SNOWFLAKE_USER", "test_user")

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        textwrap.dedent("""\
        engines:
          - type: snowflake
            name: snowflake
            connection:
              account: "${SNOWFLAKE_ACCOUNT}"
              user: "${SNOWFLAKE_USER}"
        """)
    )

    settings = Settings(
        engines_config=str(config_file), database_url="sqlite+aiosqlite:///./test.db"
    )
    engines = settings.load_engines_config()

    assert len(engines) == 1
    assert engines[0].connection["account"] == "xy12345"
    assert engines[0].connection["user"] == "test_user"


# ---------------------------------------------------------------------------
# Connection pool settings (PR #72)
# ---------------------------------------------------------------------------


def _clear_pool_env(monkeypatch):
    for var in (
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_RECYCLE",
        "DB_POOL_PRE_PING",
        "DB_POOL_TIMEOUT",
        "DB_COMMAND_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)


def test_db_pool_settings_defaults(monkeypatch):
    _clear_pool_env(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.db_pool_size == 10
    assert settings.db_max_overflow == 20
    assert settings.db_pool_recycle == 1800
    assert settings.db_pool_pre_ping is True
    assert settings.db_pool_timeout == 10
    assert settings.db_command_timeout == 30


def test_db_pool_settings_env_override(monkeypatch):
    """Ints and the bool flag coerce correctly from env-var strings."""
    _clear_pool_env(monkeypatch)
    monkeypatch.setenv("DB_POOL_SIZE", "25")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "50")
    monkeypatch.setenv("DB_POOL_RECYCLE", "900")
    monkeypatch.setenv("DB_POOL_PRE_PING", "false")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "5")
    monkeypatch.setenv("DB_COMMAND_TIMEOUT", "15")
    settings = Settings(_env_file=None)
    assert settings.db_pool_size == 25
    assert settings.db_max_overflow == 50
    assert settings.db_pool_recycle == 900
    assert settings.db_pool_pre_ping is False
    assert settings.db_pool_timeout == 5
    assert settings.db_command_timeout == 15
