"""FastAPI application factory for Attest Guardian."""

from fastapi import FastAPI

from app.api.v1.router import api_v1_router
from app.auth.rate_limit import SlidingWindowRateLimiter
from app.config import Settings, get_settings
from app.ingestion.queue import RedisJobQueue
from app.observability.logging import configure_logging
from app.observability.middleware import configure_observability
from app.routes.health import router as health_router
from app.routes.observability import router as observability_router
from app.security import configure_security
from app.storage.s3 import S3ObjectStorage


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application with validated configuration."""
    resolved_settings = settings or get_settings()
    application = FastAPI(
        title="Attest Guardian API",
        description=("Secure multilingual document intelligence for Tamil, Tanglish, and English."),
        version=resolved_settings.app_version,
        docs_url="/docs" if resolved_settings.api_docs_enabled else None,
        redoc_url="/redoc" if resolved_settings.api_docs_enabled else None,
        openapi_url="/openapi.json" if resolved_settings.api_docs_enabled else None,
    )
    application.state.settings = resolved_settings
    application.state.auth_rate_limiter = SlidingWindowRateLimiter(
        attempts=resolved_settings.auth_rate_limit_attempts,
        window_seconds=resolved_settings.auth_rate_limit_window_seconds,
    )
    application.state.object_storage = S3ObjectStorage(resolved_settings)
    application.state.job_queue = RedisJobQueue(
        resolved_settings.redis_url,
        queue_key=resolved_settings.ingestion_queue_key,
        dead_letter_key=resolved_settings.ingestion_dead_letter_key,
    )
    application.include_router(health_router)
    application.include_router(observability_router)
    application.include_router(api_v1_router, prefix="/api/v1")
    configure_security(application, resolved_settings)
    # Added last so it wraps the security middleware too: a request rejected
    # by a security check is still a request, and an unmeasured rejection is
    # how an attack looks like silence on a dashboard.
    configure_observability(application)
    return application


# The process entry point, not the factory, owns logging. `configure_logging`
# replaces the root handlers — which is right for a running service, where a
# leftover plain-text handler would re-emit every record unredacted, and wrong
# for a factory: building an app is something tests do dozens of times, and a
# constructor that reconfigures global logging as a side effect would silently
# detach any handler its caller had installed.
configure_logging(get_settings().log_level)
app = create_app()
