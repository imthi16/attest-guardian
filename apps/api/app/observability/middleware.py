"""Per-request trace binding, access logging, and latency metrics.

One place where every request is observed, so coverage does not depend on each
route remembering to instrument itself.

Two decisions worth stating, because both are the opposite of the obvious one:

**The inbound `traceparent` is honoured, and the inbound `X-Request-ID` is not.**
A trace id is a correlation handle: accepting a caller's makes their logs join
ours, and the worst a hostile value achieves is a confused trace. A request id
is echoed back and read by operators as *this* system's identifier, so accepting
one lets a caller forge it — two unrelated requests reported under one id, which
is an audit problem rather than a tidiness one. Ours is always minted.

**Routes are recorded by template, never by path.** `/workspaces/{workspace_id}`
and not the resolved UUID: a metric labelled with real ids grows without bound
and publishes the tenant list to anyone who can scrape it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.observability import context as trace_context
from app.observability.metrics import REQUEST_DURATION, REQUESTS, status_class

logger = logging.getLogger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"
TRACEPARENT_HEADER = "traceparent"

# What an unmatched path is recorded as. A literal path here would let anyone
# create unbounded metric series by requesting random URLs.
UNMATCHED_ROUTE = "unmatched"


def route_template(request: Request) -> str:
    """The matched route's path template, or a fixed placeholder.

    Read from the scope, which routing populates with the route it chose. An
    earlier draft walked `app.routes` instead and silently reported every request
    as unmatched: FastAPI nests included routers behind wrapper objects, so a
    flat scan finds only the handful of routes mounted directly. Asking the
    router what it decided cannot drift like that.

    The consequence is that a request rejected *before* routing — by the rate
    limiter, or by the body-size cap — has no template and is recorded as
    `unmatched`. That is honest: no route was chosen. It is also why the
    placeholder is a constant rather than the request path, which would let
    anyone mint unbounded metric series by requesting random URLs.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else UNMATCHED_ROUTE


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Bind a trace to each request, then log and measure its outcome."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        context = trace_context.continue_or_start(request.headers.get(TRACEPARENT_HEADER))
        token = trace_context.bind(context)
        started = time.perf_counter()
        status = 500

        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            # Measured and logged before re-raising, so a request that fails
            # inside the app is not invisible in the metrics that page someone.
            # The handler above still produces the response body; nothing here
            # converts an error into a success.
            duration = time.perf_counter() - started
            template = route_template(request)
            _record(request.method, template, status, duration)
            logger.exception(
                "request.failed",
                extra={"method": request.method, "route": template, "status": status},
            )
            raise
        else:
            duration = time.perf_counter() - started
            template = route_template(request)
            _record(request.method, template, status, duration)
            # Echoed so a user reporting a failure can quote an identifier that
            # actually appears in the logs.
            response.headers[REQUEST_ID_HEADER] = context.request_id
            response.headers[TRACEPARENT_HEADER] = context.traceparent()
            logger.info(
                "request.completed",
                extra={
                    "method": request.method,
                    "route": template,
                    "status": status,
                    "duration_ms": round(duration * 1000, 3),
                },
            )
            return response
        finally:
            # Reset last. Unbinding before the completion log would strip the
            # trace from the one line most likely to be searched for it.
            trace_context.reset(token)


def _record(method: str, template: str, status: int, duration: float) -> None:
    REQUESTS.increment(method=method, route=template, status=status_class(status))
    REQUEST_DURATION.observe(duration, route=template)


def configure_observability(application: FastAPI) -> None:
    application.add_middleware(ObservabilityMiddleware)


__all__ = [
    "REQUEST_ID_HEADER",
    "TRACEPARENT_HEADER",
    "UNMATCHED_ROUTE",
    "ObservabilityMiddleware",
    "configure_observability",
    "route_template",
]
