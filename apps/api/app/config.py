"""Validated environment configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]
_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
_UNSAFE_JWT_SECRETS = {
    "development-only-change-me",
    "replace-with-a-long-random-value",
}


class Settings(BaseSettings):
    """Application settings loaded from process environment or the root `.env`."""

    model_config = SettingsConfigDict(
        env_file=_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Environment = "development"
    app_version: str = "0.1.0"
    api_host: str = "0.0.0.0"  # noqa: S104 - required inside containers
    api_port: int = 8000
    api_docs_enabled: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    database_url: str = "postgresql+asyncpg://nambikkai:nambikkai@localhost:5432/nambikkai"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minio"
    s3_secret_key: SecretStr = SecretStr("minio123")
    s3_bucket: str = "nambikkai-documents"
    jwt_secret: SecretStr = SecretStr("development-only-change-me")

    @model_validator(mode="after")
    def enforce_deployment_secrets(self) -> Self:
        """Reject known local-only secrets outside development and test."""
        if self.app_env in {"staging", "production"}:
            if self.jwt_secret.get_secret_value() in _UNSAFE_JWT_SECRETS:
                msg = "JWT_SECRET must be replaced in staging and production"
                raise ValueError(msg)
            if self.s3_secret_key.get_secret_value() == "minio123":
                msg = "S3_SECRET_KEY must be replaced in staging and production"
                raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""
    return Settings()
