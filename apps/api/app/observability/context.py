"""The identifiers that make one request followable across processes.

An incident is diagnosed by joining lines: a slow answer in the API, the
retrieval it ran, the ingestion that produced the chunk it cited — three
programs, three log streams, one user action. Without a shared identifier that
join is manual and usually impossible.

Two identifiers, because they answer different questions. The **request id** is
this hop: one HTTP request, or one ingestion job. The **trace id** is the whole
causal chain, carried across process boundaries so the job a request enqueued is
recognisably part of that request. A worker that invented a fresh trace per job
would produce tidy logs that could never be joined back to the person waiting.

Both live in `contextvars`, so they follow `async` control flow without being
threaded through every signature — and, importantly, without leaking between
concurrent requests the way a module-level global would.

The format is W3C Trace Context: a 32-hex trace id and a 16-hex span id, the
same wire format OpenTelemetry uses. That is deliberate. Nothing here exports to
a collector, but generating ids in the standard shape means adopting a real
exporter later is a wiring change rather than a re-identification of every
historical log line.
"""

from __future__ import annotations

import re
import secrets
from contextvars import ContextVar, Token
from dataclasses import dataclass

# `version-traceid-spanid-flags`, e.g.
# 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
_TRACEPARENT = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace>[0-9a-f]{32})-(?P<span>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)
_ZERO_TRACE = "0" * 32
_ZERO_SPAN = "0" * 16


@dataclass(frozen=True)
class TraceContext:
    """One hop's position in a causal chain."""

    trace_id: str
    span_id: str
    request_id: str

    def traceparent(self) -> str:
        """This context as a W3C `traceparent` header value.

        Sampled flag is always `01`: nothing here samples, and claiming a
        sampling decision the system does not make would mislead a collector
        that later trusts it.
        """
        return f"00-{self.trace_id}-{self.span_id}-01"


_current: ContextVar[TraceContext | None] = ContextVar("trace_context", default=None)


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def parse_traceparent(header: str | None) -> tuple[str, str] | None:
    """Extract `(trace_id, span_id)` from an inbound header, if it is usable.

    An all-zero trace or span id is rejected: the specification reserves them as
    invalid, and accepting one would collapse unrelated requests into a single
    trace that appears to be one enormous operation.
    """
    if header is None:
        return None
    match = _TRACEPARENT.match(header.strip())
    if match is None:
        return None
    trace, span = match.group("trace"), match.group("span")
    if trace == _ZERO_TRACE or span == _ZERO_SPAN:
        return None
    return trace, span


def continue_or_start(traceparent: str | None, *, request_id: str | None = None) -> TraceContext:
    """Join an inbound trace when one is offered, otherwise begin one.

    The inbound span becomes this hop's *parent*, so a fresh span id is always
    minted: reusing the caller's span would make two operations indistinguishable
    in any tool that assumes span ids are unique.
    """
    parsed = parse_traceparent(traceparent)
    trace_id = parsed[0] if parsed else new_trace_id()
    return TraceContext(
        trace_id=trace_id,
        span_id=new_span_id(),
        request_id=request_id or new_span_id(),
    )


def current() -> TraceContext | None:
    return _current.get()


def bind(context: TraceContext) -> Token[TraceContext | None]:
    """Make `context` current; the token restores the previous one."""
    return _current.set(context)


def reset(token: Token[TraceContext | None]) -> None:
    _current.reset(token)


def context_fields() -> dict[str, str]:
    """The current identifiers as log fields, or empty outside a request.

    Empty rather than placeholder values: a line emitted at startup genuinely
    belongs to no request, and inventing an id for it would create a trace that
    never happened.
    """
    context = _current.get()
    if context is None:
        return {}
    return {
        "trace_id": context.trace_id,
        "span_id": context.span_id,
        "request_id": context.request_id,
    }


def current_traceparent() -> str | None:
    """The current trace as a header value, or ``None`` outside a request.

    Used when handing work to another process. ``None`` rather than a fresh
    trace: a job enqueued by a background sweep genuinely has no originating
    request, and minting one would assert a causal link that does not exist.
    """
    context = _current.get()
    return None if context is None else context.traceparent()


__all__ = [
    "TraceContext",
    "current_traceparent",
    "bind",
    "context_fields",
    "continue_or_start",
    "current",
    "new_span_id",
    "new_trace_id",
    "parse_traceparent",
    "reset",
]
