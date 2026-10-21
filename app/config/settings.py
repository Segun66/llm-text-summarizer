from pathlib import Path
from typing import Literal, Self

from pydantic import AliasChoices, Field, FilePath, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GIGACHAT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    app_env: Literal["dev", "prod"] = Field(default="dev", validation_alias="APP_ENV")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )
    auth_key: SecretStr = Field(
        validation_alias=AliasChoices("GIGACHAT_CREDENTIALS", "GIGACHAT_AUTH_KEY")
    )
    auth_url: HttpUrl
    completions_url: HttpUrl
    scope: str = Field(default="GIGACHAT_API_PERS", min_length=1)
    model: str = Field(default="GigaChat", min_length=1)
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    max_attempts: int = Field(default=3, ge=1, le=3)
    retry_min_seconds: float = Field(default=0.5, ge=0, le=30)
    retry_max_seconds: float = Field(default=4, ge=0, le=60)
    max_tokens: int = Field(default=512, ge=1, le=4096)
    cache_ttl_seconds: float = Field(default=300, gt=0, allow_inf_nan=False)
    cache_max_entries: int = Field(default=128, ge=1)
    ca_bundle: FilePath | None = None

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        if not self.auth_key.get_secret_value().strip():
            raise ValueError("GIGACHAT_CREDENTIALS must not be empty")
        if self.retry_min_seconds > self.retry_max_seconds:
            raise ValueError("retry_min_seconds must not exceed retry_max_seconds")
        for url in (self.auth_url, self.completions_url):
            if url.scheme != "https" or url.username or url.password or url.fragment or url.query:
                raise ValueError(
                    "GigaChat endpoints must use HTTPS without credentials, "
                    "query parameters or fragments"
                )
        return self

    @property
    def credentials(self) -> SecretStr:
        return self.auth_key

    def certificate_path(self) -> str | None:
        return str(Path(self.ca_bundle)) if self.ca_bundle else None
