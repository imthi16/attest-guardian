# Monitoring

- `dashboard.json` — a Grafana dashboard (import by UID `attest-guardian`).
- `alerts.yml` — Prometheus alerting rules.

Both are built only from the metrics in `apps/api/app/observability/metrics.py`, which carry no
identifier and no tenant content. That is what lets a dashboard be shared with anyone who operates
the service, and an alert be routed to a chat channel, without granting either of them access to
who was affected or what was asked. Finding the affected workspace is deliberately a second step,
through the logs, where authorization applies.

Point Prometheus at `GET /metrics`, which is served only when `METRICS_ENABLED=true` and should sit
behind your own network boundary — the endpoint has no authentication of its own.

## The panel and the alert worth understanding

Most of this is the usual rate, error, and duration. The one that is particular to this product is
**abstention share**.

A rising abstention rate is not an error. The API returns `200`, the pipeline behaves exactly as
designed, and no error metric moves — while users stop getting answers. It is the earliest signal
that retrieval regressed, that an embedding version changed without a re-index, or that a
workspace's documents were archived. Without it, that failure reaches users before it reaches an
operator.

`AttestClaimsMostlyDropped` is the quieter version of the same idea: claims proposed and then
dropped by verification never appear in an answer, so answers get thinner while still looking
correct, and nobody reports it.

## Thresholds

Starting points, not measurements. Nothing has run in production, so any claim that these are tuned
would be invented. Review them against the first fortnight of real traffic and record what you
changed and why.
