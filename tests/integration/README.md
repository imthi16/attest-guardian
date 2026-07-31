# Integration tests

Reserved for cross-service behaviour spanning more than one application.

**The integration suite that exists today is `apps/api/tests/integration/`**, where it can import
the application it exercises. It runs against the real PostgreSQL, Redis, and MinIO from
`make infra-up`, provisions disposable databases, and covers row-level security, the tenant fence,
the ingestion worker, and the document lifecycle end to end.

Fixtures are synthetic throughout: no tenant document, no personal data, no real credential.
