# Observability helpers

Reserved for trace, metric, and structured logging helpers shared across `apps/*` and `services/*`.

**Nothing imports from here yet.** The implementation lives in `apps/api/app/observability/`, where
it has one consumer; it moves here when it has two. Its design — redaction in the *formatter* keyed
on field name, metric labels held stricter than log fields, and W3C trace context carried across
the queue — is documented in [`docs/OBSERVABILITY.md`](../../docs/OBSERVABILITY.md).

Whatever lands here must keep those properties: redact secrets, document content, and full
sensitive prompts, and never accept a tenant identifier as a metric label.
