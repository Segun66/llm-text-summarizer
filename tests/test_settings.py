import pytest
from pydantic import ValidationError

from app.config.settings import Settings


@pytest.mark.parametrize(
    "changes",
    [
        {"auth_key": " "},
        {"auth_url": "http://auth.test"},
        {"completions_url": "https://user:password@llm.test"},
        {"max_attempts": 0},
        {"max_attempts": 4},
        {"timeout_seconds": 0},
        {"cache_ttl_seconds": 0},
        {"cache_ttl_seconds": float("inf")},
        {"cache_max_entries": 0},
        {"retry_min_seconds": 5, "retry_max_seconds": 1},
    ],
)
def test_invalid_configuration(settings, changes):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(settings.model_dump() | changes))


def test_environment_configuration_and_secret_masking(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "private-key")
    monkeypatch.setenv("GIGACHAT_AUTH_URL", "https://auth.test/oauth")
    monkeypatch.setenv("GIGACHAT_COMPLETIONS_URL", "https://llm.test/completions")
    settings = Settings()
    assert settings.auth_key.get_secret_value() == "private-key"
    assert "private-key" not in repr(settings)


def test_missing_required_settings(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key in (
        "GIGACHAT_CREDENTIALS",
        "GIGACHAT_AUTH_KEY",
        "GIGACHAT_AUTH_URL",
        "GIGACHAT_COMPLETIONS_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_cache_configuration_from_environment(settings, monkeypatch):
    monkeypatch.setenv("GIGACHAT_CACHE_TTL_SECONDS", "12.5")
    monkeypatch.setenv("GIGACHAT_CACHE_MAX_ENTRIES", "16")
    config = Settings(
        _env_file=None,
        auth_key="test",
        auth_url=settings.auth_url,
        completions_url=settings.completions_url,
    )
    assert config.cache_ttl_seconds == 12.5
    assert config.cache_max_entries == 16


def test_canonical_credentials_and_legacy_alias_priority(monkeypatch, settings):
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "fixture-canonical")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "fixture-legacy")
    config = Settings(
        _env_file=None, auth_url=settings.auth_url, completions_url=settings.completions_url
    )
    assert config.credentials.get_secret_value() == "fixture-canonical"
    assert config.auth_key.get_secret_value() == "fixture-canonical"
    assert "fixture-canonical" not in repr(config)
    assert "fixture-canonical" not in config.model_dump_json()


@pytest.mark.parametrize("environment", ["dev", "prod"])
def test_dotenv_loading_and_environment_precedence(environment, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in (
        "GIGACHAT_CREDENTIALS",
        "GIGACHAT_AUTH_KEY",
        "APP_ENV",
        "LOG_LEVEL",
        "GIGACHAT_MODEL",
        "GIGACHAT_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "GIGACHAT_CREDENTIALS=fixture-dotenv\n"
        "GIGACHAT_AUTH_URL=https://auth.test/oauth\n"
        "GIGACHAT_COMPLETIONS_URL=https://llm.test/completions\n"
        f"APP_ENV={environment}\nLOG_LEVEL=WARNING\n"
        "GIGACHAT_MODEL=ConfiguredModel\nGIGACHAT_TIMEOUT_SECONDS=7\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    config = Settings()
    assert config.app_env == environment
    assert config.log_level == "ERROR"
    assert config.model == "ConfiguredModel"
    assert config.timeout_seconds == 7
    assert config.credentials.get_secret_value() == "fixture-dotenv"


@pytest.mark.parametrize(
    "changes",
    [
        {"app_env": "staging"},
        {"log_level": "TRACE"},
        {"auth_url": "https://auth.test/oauth?token=fixture-only"},
    ],
)
def test_invalid_environment_and_secret_in_url_are_rejected(settings, changes):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **(settings.model_dump() | changes))


def test_validation_error_text_hides_input_values(settings):
    data = settings.model_dump() | {"auth_key": "fixture-private-value", "retry_min_seconds": 10}
    with pytest.raises(ValidationError) as captured:
        Settings(_env_file=None, **data)
    assert "fixture-private-value" not in str(captured.value)
    assert "input_value" not in str(captured.value)


def test_environment_legacy_key_overrides_dotenv_canonical_key(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GIGACHAT_CREDENTIALS", raising=False)
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "fixture-environment")
    (tmp_path / ".env").write_text(
        "GIGACHAT_CREDENTIALS=fixture-dotenv\n"
        "GIGACHAT_AUTH_URL=https://auth.test/oauth\n"
        "GIGACHAT_COMPLETIONS_URL=https://llm.test/completions\n",
        encoding="utf-8",
    )
    assert Settings().credentials.get_secret_value() == "fixture-environment"
