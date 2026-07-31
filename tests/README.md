# Cross-service tests

Repository-level suites spanning more than one application. Unit tests stay next to the code they
cover, which is where all of them are today:

| Suite | Lives in | Needs |
| --- | --- | --- |
| API unit | `apps/api/tests/` | nothing |
| API integration | `apps/api/tests/integration/` | `make infra-up` |
| Evaluation | `apps/api/tests/evaluation/`, data in `evaluation/` | nothing |
| Web | `apps/web/**/*.test.ts(x)` | nothing |

See [`docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md#tests) for how to run each and what the coverage
floors are.
