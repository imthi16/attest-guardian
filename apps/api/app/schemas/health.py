"""Health endpoint contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Stable liveness response."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    service: Literal["attest-api"]
    version: str


class ReadinessResponse(BaseModel):
    """Whether every dependency is reachable, and which is not.

    A dependency's verdict is a name and one of two words. Nothing here says
    *why* something is unavailable: this endpoint cannot authenticate its caller,
    and a driver's error message routinely carries the DSN it failed to reach —
    host, port, user, occasionally a password. The reason goes to the logs.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "degraded"]
    dependencies: dict[str, Literal["ok", "unavailable"]]
