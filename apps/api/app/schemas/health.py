"""Health endpoint contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Stable liveness response."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    service: Literal["attest-api"]
    version: str
