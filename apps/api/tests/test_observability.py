"""Trace context, metrics, and readiness — the operator-facing behaviour.

The recurring theme is that each of these is read by someone who cannot ask a
follow-up question: a probe by an orchestrator, a metric by a scraper, a trace id
by an engineer at 3am joining two log streams. So each is tested for what it
says *and* for what it must not say.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging

import pytest
from app.config import Settings
from app.main import create_app
from app.observability import context as trace_context
from app.observability.logging import configure_logging
from app.observability.metrics import MetricError, MetricRegistry, status_class
from app.observability.middleware import REQUEST_ID_HEADER, TRACEPARENT_HEADER
from app.observability.readiness import DependencyStatus, ReadinessReport, check
from httpx import ASGITransport, AsyncClient

VALID_TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
UPSTREAM_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"


def client(settings: Settings | None = None) -> AsyncClient:
    app = create_app(settings or Settings(_env_file=None))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


# --- trace context ----------------------------------------------------------


def test_an_inbound_trace_is_continued_with_a_fresh_span() -> None:
    """Joining the caller's trace is the point; reusing their span is not.

    Two operations sharing a span id are indistinguishable in any tool that
    assumes span ids are unique, which is all of them.
    """
    context = trace_context.continue_or_start(VALID_TRACEPARENT)

    assert context.trace_id == UPSTREAM_TRACE
    assert context.span_id != "00f067aa0ba902b7"
    assert len(context.span_id) == 16


def test_a_missing_or_malformed_traceparent_starts_a_new_trace() -> None:
    for header in (None, "garbage", "00-short-00f067aa0ba902b7-01", ""):
        context = trace_context.continue_or_start(header)
        assert len(context.trace_id) == 32
        assert context.trace_id != UPSTREAM_TRACE


def test_an_all_zero_trace_id_is_refused() -> None:
    """The specification reserves it as invalid, and honouring it would collapse
    every unrelated request into one trace that looks like a single enormous
    operation."""
    zeros = f"00-{'0' * 32}-00f067aa0ba902b7-01"

    assert trace_context.parse_traceparent(zeros) is None
    assert trace_context.continue_or_start(zeros).trace_id != "0" * 32


def test_the_rendered_traceparent_round_trips() -> None:
    context = trace_context.continue_or_start(None)

    parsed = trace_context.parse_traceparent(context.traceparent())

    assert parsed == (context.trace_id, context.span_id)


def test_context_fields_are_empty_outside_a_request() -> None:
    """A startup line belongs to no request; inventing an id would fabricate a trace."""
    assert trace_context.context_fields() == {}
    assert trace_context.current_traceparent() is None


def test_binding_is_scoped_and_restores_the_previous_context() -> None:
    outer = trace_context.continue_or_start(None)
    outer_token = trace_context.bind(outer)
    inner = trace_context.continue_or_start(None)
    inner_token = trace_context.bind(inner)

    assert trace_context.current() is inner
    trace_context.reset(inner_token)
    assert trace_context.current() is outer
    trace_context.reset(outer_token)
    assert trace_context.current() is None


async def test_concurrent_tasks_do_not_share_a_trace() -> None:
    """A module-level global would leak one request's id into another's logs.

    With many requests in flight this is not a tidiness problem: it attributes
    one tenant's activity to another in the record used to investigate it.
    """
    seen: list[str] = []

    async def run() -> None:
        token = trace_context.bind(trace_context.continue_or_start(None))
        await asyncio.sleep(0)
        current = trace_context.current()
        assert current is not None
        seen.append(current.trace_id)
        trace_context.reset(token)

    await asyncio.gather(*(run() for _ in range(8)))

    assert len(set(seen)) == 8


async def test_a_request_carries_its_trace_into_the_log_line() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    async with client() as http:
        response = await http.get("/health", headers={TRACEPARENT_HEADER: VALID_TRACEPARENT})

    assert response.status_code == 200
    lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    completed = [line for line in lines if line["event"] == "request.completed"]
    assert completed
    assert completed[0]["trace_id"] == UPSTREAM_TRACE
    assert completed[0]["route"] == "/health"
    # The response points a user at an identifier that is really in the logs.
    assert response.headers[REQUEST_ID_HEADER] == completed[0]["request_id"]
    assert UPSTREAM_TRACE in response.headers[TRACEPARENT_HEADER]


async def test_an_inbound_request_id_is_never_trusted() -> None:
    """It is echoed back and read as *our* identifier, so a caller must not set it.

    Accepting one lets two unrelated requests be reported under a single id,
    which corrupts the record rather than merely confusing it.
    """
    async with client() as http:
        response = await http.get("/health", headers={REQUEST_ID_HEADER: "forged-by-the-caller"})

    assert response.headers[REQUEST_ID_HEADER] != "forged-by-the-caller"


# --- metrics ----------------------------------------------------------------


def test_a_label_that_could_carry_tenant_content_is_refused() -> None:
    """A scrape endpoint has no per-tenant authorization to fall back on.

    A `query` label would publish the questions people asked to whoever can
    reach the endpoint.
    """
    counter = MetricRegistry().counter("probe", "help")

    for label in ("query", "email", "authorization", "password"):
        with pytest.raises(MetricError, match="tenant content or a credential"):
            counter.increment(1.0, **{label: "value"})


def test_an_identifier_is_refused_as_a_label_though_it_is_safe_to_log() -> None:
    """The one place a field can be fine in a log and wrong in a metric.

    `workspace_id` is exactly what an incident log needs. As a label it is a
    permanent time series per tenant — unbounded storage, and a tenant directory
    published to anyone who can scrape. Hashing does not help: the cardinality is
    the same and a hashed tenant list is still a tenant list.
    """
    counter = MetricRegistry().counter("probe", "help")

    for label in ("workspace_id", "document_id", "chunk_id", "user", "content_hash"):
        with pytest.raises(MetricError, match="unbounded cardinality"):
            counter.increment(1.0, **{label: "value"})


def test_counters_and_histograms_render_prometheus_text() -> None:
    registry = MetricRegistry()
    requests = registry.counter("attest_probe_requests", "Probe requests.")
    duration = registry.histogram("attest_probe_seconds", "Probe duration.", buckets=(0.1, 1.0))

    requests.increment(route="/health", status="2xx")
    requests.increment(route="/health", status="2xx")
    duration.observe(0.05, route="/health")
    duration.observe(2.0, route="/health")

    text = registry.render()

    assert "# TYPE attest_probe_requests counter" in text
    assert 'attest_probe_requests_total{route="/health",status="2xx"} 2' in text
    assert 'attest_probe_seconds_bucket{route="/health",le="0.1"} 1' in text
    assert 'attest_probe_seconds_bucket{route="/health",le="+Inf"} 2' in text
    assert 'attest_probe_seconds_count{route="/health"} 2' in text
    assert 'attest_probe_seconds_sum{route="/health"} 2.05' in text


def test_histogram_buckets_are_cumulative() -> None:
    """Prometheus defines `le` buckets as cumulative; per-bucket counts would
    make every rate and quantile query silently wrong."""
    registry = MetricRegistry()
    duration = registry.histogram("probe", "help", buckets=(1.0, 10.0))

    duration.observe(0.5)

    assert 'probe_bucket{le="1"} 1' in registry.render()
    assert 'probe_bucket{le="10"} 1' in registry.render()


def test_a_registry_refuses_to_redefine_a_name_as_another_type() -> None:
    registry = MetricRegistry()
    registry.counter("probe", "help")

    with pytest.raises(MetricError, match="already registered"):
        registry.histogram("probe", "help")


def test_a_counter_may_not_decrease_and_a_histogram_may_not_take_infinity() -> None:
    registry = MetricRegistry()

    with pytest.raises(MetricError, match="may not decrease"):
        registry.counter("probe", "help").increment(-1)
    with pytest.raises(MetricError, match="must be finite"):
        registry.histogram("timing", "help").observe(float("inf"))


def test_an_empty_registry_renders_nothing_rather_than_a_stray_newline() -> None:
    assert MetricRegistry().render() == ""


def test_status_is_recorded_as_a_class() -> None:
    """A label per status code multiplies series for no operational gain."""
    assert status_class(200) == "2xx"
    assert status_class(404) == "4xx"
    assert status_class(503) == "5xx"


async def test_metrics_are_not_exposed_unless_enabled() -> None:
    """A scrape endpoint published by default is how request volumes and error
    rates end up on the public internet."""
    async with client(Settings(_env_file=None)) as http:
        assert (await http.get("/metrics")).status_code == 404

    async with client(Settings(_env_file=None, metrics_enabled=True)) as http:
        response = await http.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


async def test_a_request_is_measured_by_route_template_not_by_path() -> None:
    """A path label carrying real ids grows without bound and lists the tenants."""
    settings = Settings(_env_file=None, metrics_enabled=True)
    async with client(settings) as http:
        await http.get("/health")
        text = (await http.get("/metrics")).text

    assert 'route="/health"' in text
    assert "attest_http_request_duration_seconds_count" in text


async def test_an_unmatched_path_cannot_create_unbounded_series() -> None:
    settings = Settings(_env_file=None, metrics_enabled=True)
    async with client(settings) as http:
        await http.get("/no/such/path/12345")
        text = (await http.get("/metrics")).text

    assert "no/such/path" not in text
    assert 'route="unmatched"' in text


# --- readiness --------------------------------------------------------------


async def test_readiness_reports_a_name_and_a_verdict_and_nothing_else() -> None:
    """The probe cannot authenticate its caller, so its body is public.

    A driver's failure message routinely carries the DSN it could not reach —
    host, port, user, sometimes a password — which is exactly what an operator
    wants and exactly what must not be published.
    """
    secret_dsn = "postgresql://attest:hunter2@db.internal:5432/attest"

    async def failing() -> None:
        raise ConnectionError(f"could not connect to {secret_dsn}")

    report = await check({"database": failing})
    body = json.dumps(report.as_dict())

    assert report.ready is False
    assert report.as_dict()["status"] == "degraded"
    assert "hunter2" not in body
    assert "db.internal" not in body
    assert "ConnectionError" not in body
    assert report.as_dict()["dependencies"] == {"database": "unavailable"}


async def test_a_hanging_dependency_is_bounded_by_the_probe_budget() -> None:
    """A probe slower than its own deadline reads as down for its own reasons."""

    async def hangs() -> None:
        await asyncio.sleep(10)

    report = await check({"queue": hangs}, budget_seconds=0.01)

    assert report.ready is False


async def test_dependencies_are_probed_concurrently() -> None:
    """Sequential probes would take the sum of the timeouts, and a probe that
    exceeds its schedule is indistinguishable from a failing one."""
    started = asyncio.Event()

    async def slow() -> None:
        started.set()
        await asyncio.sleep(0.05)

    async def quick() -> None:
        await started.wait()

    report = await asyncio.wait_for(check({"a": slow, "b": quick}), timeout=1.0)

    assert report.ready is True


def test_a_report_is_ready_only_when_every_dependency_is() -> None:
    mixed = ReadinessReport(
        dependencies=(
            DependencyStatus(name="database", ready=True),
            DependencyStatus(name="queue", ready=False),
        )
    )

    assert mixed.ready is False
    assert mixed.as_dict()["dependencies"] == {"database": "ok", "queue": "unavailable"}


async def test_readiness_failures_are_logged_with_the_error_type_only() -> None:
    stream = io.StringIO()
    configure_logging("WARNING", stream=stream)

    async def failing() -> None:
        raise ConnectionError("postgresql://attest:hunter2@db.internal/attest")

    await check({"database": failing})

    logged = stream.getvalue()
    assert "hunter2" not in logged
    assert json.loads(logged.strip())["error_type"] == "ConnectionError"


async def test_liveness_touches_no_dependency() -> None:
    """Wiring a restart to readiness turns a database blip into a rolling
    restart of every replica; liveness must therefore stay dependency-free."""
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)

    async with client() as http:
        response = await http.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "readiness" not in stream.getvalue()


def teardown_module() -> None:
    """Leave logging as the rest of the suite expects to find it."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)


async def test_a_failing_request_is_measured_and_logged_before_it_propagates() -> None:
    """An unhandled error must not be invisible in the metrics that page someone.

    The middleware records and logs, then re-raises: the error handler above
    still produces the response, and nothing here converts a failure into a
    success.
    """
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    settings = Settings(_env_file=None, metrics_enabled=True)
    app = create_app(settings)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("statement failed for parameters: 'a tenant question'")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        response = await http.get("/boom")

    assert response.status_code == 500
    logged = stream.getvalue()
    # The exception is recorded by type; its message carried tenant text.
    assert "a tenant question" not in logged
    failures = [
        json.loads(line)
        for line in logged.splitlines()
        if line.strip() and json.loads(line)["event"] == "request.failed"
    ]
    assert failures
    assert failures[0]["error_type"] == "RuntimeError"
    assert failures[0]["status"] == 500


def test_uvicorn_loggers_are_adopted_rather_than_left_in_plain_text() -> None:
    """The leak that would have defeated this whole module.

    Under the container entry point uvicorn configures `uvicorn.error` with its
    own non-propagating handler *before* importing the application. Clearing
    only the root's handlers leaves it emitting plain text — and what it emits
    is the traceback of an unhandled request exception, which is the richest
    tenant content in the system: a driver error carries its bound parameters,
    meaning the raw query and sometimes evidence text.
    """
    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.propagate = False
    leaked = io.StringIO()
    uvicorn_error.addHandler(logging.StreamHandler(leaked))

    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    try:
        raise ValueError("statement failed for parameters: 'a tenant question'")
    except ValueError:
        uvicorn_error.exception("Exception in ASGI application")

    assert uvicorn_error.handlers == []
    assert uvicorn_error.propagate is True
    assert leaked.getvalue() == ""
    record = json.loads(stream.getvalue().strip())
    assert record["error_type"] == "ValueError"
    assert "a tenant question" not in stream.getvalue()


async def test_probes_are_exempt_from_the_global_rate_limit() -> None:
    """Rate limiting a probe breaks the thing it exists for.

    Where probes and traffic share a source address — one reverse proxy, a
    service mesh — ordinary load exhausts the limiter and `/readyz` returns 429
    while every dependency is healthy. The orchestrator reads that as down and
    removes a working replica, turning a traffic spike into an outage.
    """
    settings = Settings(_env_file=None, global_rate_limit_attempts=1, metrics_enabled=True)
    async with client(settings) as http:
        await http.get("/api/v1/does-not-exist")  # consume the only slot
        assert (await http.get("/api/v1/does-not-exist")).status_code == 429

        assert (await http.get("/health")).status_code == 200
        assert (await http.get("/metrics")).status_code == 200


def test_the_readiness_contract_declares_its_degraded_response() -> None:
    """A client generated from a contract claiming only 200 treats the state
    this endpoint exists to report as an unexpected error."""
    schema = create_app(Settings(_env_file=None)).openapi()

    assert set(schema["paths"]["/readyz"]["get"]["responses"]) >= {"200", "503"}
