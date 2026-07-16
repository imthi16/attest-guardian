"""Configuration safety tests."""

from typing import cast

import pytest
from app.config import Environment, Settings
from pydantic import ValidationError


def test_development_defaults_are_usable() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.api_docs_enabled is True
    assert settings.jwt_secret.get_secret_value() == "development-only-change-me"


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environments_reject_local_secrets(environment: str) -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET must be replaced"):
        Settings(app_env=cast(Environment, environment), _env_file=None)


def test_production_accepts_replaced_secrets() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret="a-production-secret-provided-by-a-secret-manager",
        s3_secret_key="a-production-object-storage-secret",
        _env_file=None,
    )

    assert settings.app_env == "production"


def test_production_rejects_local_object_storage_secret() -> None:
    with pytest.raises(ValidationError, match="S3_SECRET_KEY must be replaced"):
        Settings(
            app_env="production",
            jwt_secret="a-production-secret-provided-by-a-secret-manager",
            _env_file=None,
        )
