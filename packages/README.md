# Shared packages

Language-neutral contracts, shared configuration, and privacy-safe observability helpers, for
things more than one application or service consumes.

| Package | State |
| --- | --- |
| [`contracts/`](./contracts/README.md) | **In use.** Holds `openapi.json`, the pin between the API and the web app |
| [`config/`](./config/README.md) | Reserved. Configuration is per-application today |
| [`observability/`](./observability/README.md) | Reserved. The helpers live in `apps/api/app/observability/` |

A reserved directory is a stated intention, not a shipped package — nothing imports from one.
