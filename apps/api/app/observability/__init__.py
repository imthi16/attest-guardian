"""Telemetry: structured logs, trace context, metrics, and readiness.

Everything here is provider-agnostic by construction, in the same way the OCR,
embedding, and reranker layers are. Identifiers are minted in W3C Trace Context
format and metrics are rendered in Prometheus exposition format, so adopting a
real OpenTelemetry exporter or a scrape target is a wiring change rather than a
re-identification of every historical log line. **No collector is wired in this
release** — see `docs/OBSERVABILITY.md` for what that does and does not give an
operator today.

The privacy rule runs through all of it: a log field, a metric label, and a
readiness response are each capable of publishing tenant content to a place with
none of the platform's authorization, so each is filtered by the same
classifier in `redaction.py` rather than by the discipline of whoever wrote the
call site.
"""

from app.observability.context import (
    TraceContext,
    bind,
    context_fields,
    continue_or_start,
    current,
    parse_traceparent,
    reset,
)
from app.observability.logging import JsonFormatter, configure_logging
from app.observability.metrics import REGISTRY, MetricError, MetricRegistry, status_class
from app.observability.middleware import (
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    configure_observability,
)
from app.observability.readiness import ReadinessReport, check
from app.observability.redaction import fingerprint, redact_fields

__all__ = [
    "REGISTRY",
    "REQUEST_ID_HEADER",
    "TRACEPARENT_HEADER",
    "JsonFormatter",
    "MetricError",
    "MetricRegistry",
    "ReadinessReport",
    "TraceContext",
    "bind",
    "check",
    "configure_logging",
    "configure_observability",
    "context_fields",
    "continue_or_start",
    "current",
    "fingerprint",
    "parse_traceparent",
    "redact_fields",
    "reset",
    "status_class",
]
