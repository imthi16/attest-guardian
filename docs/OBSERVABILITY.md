# Observability

Three surfaces, each read by someone who cannot ask a follow-up question: structured logs for an
engineer joining two streams at 3am, metrics for a scraper, and a readiness probe for an
orchestrator. Each is designed around what it must *not* say as much as what it reports.

| Surface | Where | Exposed |
| --- | --- | --- |
| JSON logs | stdout, both the API and the worker | wherever logs are shipped |
| `GET /health` | API | liveness; touches no dependency |
| `GET /readyz` | API | readiness; `503` when a dependency is unreachable |
| `GET /metrics` | API | Prometheus text, **only when `METRICS_ENABLED=true`** |

## What is not here

**No collector is wired.** Identifiers are minted in W3C Trace Context format and metrics are
rendered in Prometheus exposition format, so adopting an OpenTelemetry exporter or a scrape target
is a wiring change rather than a re-identification of every historical log line — but nothing in
this release sends a span anywhere. An operator gets correlated logs and a scrapeable endpoint, not
a distributed trace view. That is the honest description; treat any claim of "OpenTelemetry
support" as meaning the wire format, not the pipeline.

The `Tracer` seam sits at `app/observability/context.py`. A real exporter would read the same
`traceparent` this already produces.

## Privacy

A log line is the one place where every other boundary can be quietly undone. Retrieval is
authorized, storage is workspace-scoped, answers are cited — and a single debug line writing the
user's question and a paragraph of their document ships all of it to an aggregator with none of
those controls. Nothing fails and it cannot be taken back.

So redaction lives in the **formatter**, not at the call sites. Call-site discipline holds until the
one line somebody adds at 2am, and that is the line that leaks.

Fields are classified by **name**, because value matching cannot work: a bearer token and a document
id are both opaque strings, and a Tamil sentence looks like any other text.

| Treatment | Fields | Why |
| --- | --- | --- |
| Dropped | `password`, `*_secret`, `*_token`, `authorization`, `api_key`, `cookie` | No version is worth keeping; even a length is a hint |
| Fingerprinted | `query`, `content`, `quote`, `claim`, `email`, `filename`, `title`, `note`, … | Identity matters for debugging, the text must not persist |
| Kept | ids, counts, durations, `stage`, `status`, `decision`, `error_type` | What an incident is actually diagnosed from |

Anything unrecognised is **fingerprinted**, so a field added without thought fails closed. The
failure directions are not symmetric: over-redacting costs an operator a follow-up question,
under-redacting cannot be undone.

A fingerprint is `sha256:` plus twelve hex characters, unsalted — deliberately, so the same query
fingerprints identically in the API and the worker. That cross-process join is the only reason to
keep it at all.

Two further rules that are easy to miss:

- **Exceptions are reduced to their type.** A database or provider error carries its bound
  parameters — the raw query, sometimes evidence text — so a traceback is one of the richest sources
  of tenant content in the system, arriving on the path nobody reads until something is wrong.
- **The format string is logged, not the interpolated message.** `logger.info("asked %s", query)`
  is the easiest way to leak by hand; the argument goes through redaction as a field instead of
  being spliced into free text where nothing can classify it.

## Trace context

Two identifiers, answering different questions. The **request id** is this hop — one HTTP request,
or one ingestion job. The **trace id** is the whole causal chain.

An inbound `traceparent` is honoured, so a caller's logs join ours. An inbound `X-Request-ID` is
**not**: it is echoed back and read by operators as this system's identifier, so accepting one would
let a caller report two unrelated requests under a single id. That is an audit problem rather than a
tidiness one.

The trace travels to the worker on the queue message, so a document's ingestion lines join the
upload the user is still waiting on. A job with no inbound trace — an operator requeue, the idle
sweep — starts its own rather than being dropped from telemetry.

## Metrics

The label rule is **stricter than the log rule**, and it is the one place a field can be fine in a
log and wrong in a metric. `workspace_id` is exactly what an incident log needs; as a label it is a
permanent time series per tenant — unbounded storage, and a tenant directory published to whoever
can scrape. Identifiers are refused, and hashing does not help: the cardinality is the same and a
hashed tenant list is still a tenant list. Routes are recorded as **templates**
(`/workspaces/{workspace_id}`), never resolved paths, and an unmatched path is recorded as the
constant `unmatched` so nobody can mint series by requesting random URLs.

`/metrics` is **off by default**. A scrape endpoint published automatically is how a service's
request volumes and error rates end up on the public internet; it has no authentication of its own
and belongs behind your network boundary.

Dashboards and alerts are in [`infra/monitoring/`](../infra/monitoring/), including the metric
peculiar to this product — abstention share, which no error metric would ever show.

## Readiness

`/health` is liveness and touches nothing. `/readyz` reaches PostgreSQL, Redis, and object storage,
and returns `503` when any is unreachable.

**Do not wire a restart to `/readyz`.** A database blip would roll every replica, turning a
dependency's outage into an outage of your own. Wire the load balancer to readiness and the restart
to liveness.

The response is a dependency name and one of two words, and nothing else — the probe cannot
authenticate its caller, and a driver's failure message routinely carries the DSN it could not
reach, including host, port, user, and sometimes a password. The reason goes to the logs, where
authorization exists. Probes run concurrently under a short budget, because a probe slower than its
own schedule is indistinguishable from a failing one.

## Configuration

| Variable | Default | Effect |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | Root level for the JSON handler |
| `METRICS_ENABLED` | `false` | Serves `GET /metrics` when true |

Logging is configured by the **process entry point**, not by `create_app`. The factory is called
dozens of times in tests, and a constructor that reconfigured global logging as a side effect would
silently detach whatever handler its caller had installed.

## Limitations

- No collector, no span export, no sampling. See above.
- Metrics are per process and in memory: a restart resets counters (normal for Prometheus) and a
  multi-replica deployment must aggregate across scrape targets rather than expecting one total.
- Alert thresholds are starting points; nothing has run in production and any claim they are tuned
  would be invented.
- The worker exposes no scrape endpoint — it is not an HTTP server. Its metrics are visible only in
  its logs until a push gateway or a sidecar is added.
