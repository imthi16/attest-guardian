# Deployment

A practical, non-Kubernetes deployment: Docker Compose on a host, behind a reverse proxy that
terminates TLS, with managed PostgreSQL, Redis, and object storage.

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.production.yml \
  --profile application up -d
```

## The four services, and the one that gets forgotten

| Service | Role | If it is missing |
| --- | --- | --- |
| `migrate` | Runs `alembic upgrade head` once, to completion | Replicas serve against an old schema and fail on the first query touching a new column |
| `api` | FastAPI | Nothing works, and you find out immediately |
| `worker` | Ingestion | **Uploads are accepted and never processed** |
| `web` | Next.js | The UI is down, and you find out immediately |

The worker is the one worth checking twice. Without it, documents sit at `pending` forever, the UI
shows them queued, and **nothing in the API's health or readiness says a word** — the API is
genuinely healthy. Running the API without the worker is the most plausible way to ship a broken
product that looks entirely fine. It is why `worker` is in the base Compose file rather than left as
an exercise.

Migrations are a **deployment step**, not something a service does on boot: replicas starting
together would race the same DDL, and a failed migration inside a startup path presents as a crash
loop rather than as a failed deploy.

## Before the first replica takes traffic

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.production.yml \
  --profile application run --rm api python -m app.preflight
```

**Both files, and the production environment.** Running it against the base file alone resolves the
development defaults and checks the bundled `postgres`, `redis`, and `minio` — so it can pass while
the managed database this deployment actually uses is unreachable. A preflight that verifies the
wrong thing is worse than none, because it is believed.

`Settings` already rejects a default `JWT_SECRET`, a wildcard CORS origin, and a retired embedding
version at construction. Preflight adds what cannot be checked from environment variables: whether
this process can actually open the database, the queue, and the bucket — and whether the schema is
at a revision at all. Exit `0` ready, `1` a check failed, `2` the configuration is invalid.

It deliberately **mutates nothing**. A preflight that created a missing bucket would hide a
misconfigured bucket name by silently making a second, empty one; the documents would be missing
rather than the deploy failing.

## Deploy

```bash
# 1. Build and push, or build on the host.
docker compose -f docker-compose.yml -f deploy/docker-compose.production.yml \
  --profile application build

# 2. Migrate. Forward-only; see rollback below before you need it.
docker compose -f docker-compose.yml -f deploy/docker-compose.production.yml \
  --profile application run --rm migrate

# 3. Start.
docker compose -f docker-compose.yml -f deploy/docker-compose.production.yml \
  --profile application up -d

# 4. Verify. Green containers mean the processes started, which is the question
#    nobody needs answered.
scripts/smoke.sh https://attest.example.com
```

`scripts/smoke.sh` is read-only and unauthenticated — it creates no account and uploads nothing, so
it leaves no residue in a production tenant and needs no credentials in CI. It checks liveness,
readiness (which proves the process reached all three dependencies), that the correlation header is
present (its absence means requests are reaching something that is not this application), that
interactive docs are closed, that the metrics endpoint is not publicly reachable, and that security
headers survive the proxy.

It does **not** check that the worker is running. Do that by hand on a first deploy: upload a
document and watch it reach `ready`.

## Rollback

**The application rolls back. The schema does not.**

Alembic migrations here are forward-only in practice: `downgrade` exists and is exercised in CI, but
a downgrade that drops a column discards the data in it, and no application rollback puts it back.
So the safe procedure is to roll the *images* back and leave the schema where it is — which works
because a migration must be backward-compatible with the release before it.

```bash
# Roll the application back one release, leaving the schema alone.
# `IMAGE_TAG` selects the images; the overlay requires it, so a rollback cannot
# silently redeploy the current build.
IMAGE_TAG=<previous> docker compose -f docker-compose.yml \
  -f deploy/docker-compose.production.yml --profile application up -d
scripts/smoke.sh https://attest.example.com
```

If a migration is genuinely unsafe to leave in place, that is a restore, not a rollback: see below.
Plan for it by writing migrations that add before they remove — a release that adds a column and a
later one that stops writing the old, rather than one that renames.

## Backup and restore

```bash
# Both read the deployment's own DATABASE_URL and S3_* settings, and need
# pg_dump, mc, and sha256sum on PATH. They do not go through Compose: the
# production topology parks the bundled datastores, so `compose exec postgres`
# would reach a container that is not running — or, if one were started, would
# faithfully back up an empty local database and report success.
scripts/backup.sh                   # -> ./backups/<timestamp>/
scripts/restore.sh ./backups/<timestamp>
```

The database and the object store are **not independent**. A `documents` row points at a storage
key, and a citation is only resolvable while both exist. Backing up one without the other produces a
restore where answers cite evidence that is gone — worse than no backup, because every check passes
and it looks like it worked.

So both are captured under one timestamp and the manifest digests **both** the dump and the object
tree; `restore.sh` verifies both, and validates everything *before* it destroys anything. Restoring a database from Tuesday alongside objects from Thursday would make
citations resolve to the *wrong text*: no error, no failed check, answers that look grounded and are
not. Nothing downstream can detect that, so it is caught at restore time or not at all.

This is not a consistent snapshot across two systems, and there are two windows, not one. A document
uploaded between the steps lands in storage and not in the dump — harmless, and why the database is
dumped **first**: an orphaned object wastes space, an orphaned row breaks an answer. The dangerous
direction is a *permanent delete* between the steps: the row is already in the dump and the worker's
purge sweep removes the object before the mirror reaches it, leaving a restored citation pointing at
bytes that are gone. Stop the worker, or pause purging, for the duration of a backup you intend to
rely on.

After a restore, run migrations before starting the application: the dump may predate the running
release.

**A backup nobody has restored is a hypothesis.** Test the restore on staging, on a schedule.

## What this deployment assumes

- **TLS terminates in front of the application.** Nothing here serves HTTPS. Session cookies are
  `Secure` in production, so over plain HTTP the browser accepts the sign-in response and silently
  drops the cookie — which presents to the user as a wrong password.
- **The proxy sets `X-Forwarded-Host`.** The upload and streaming relays compare `Origin` against it;
  a proxy that does not set it will have same-origin requests rejected as cross-origin.
- **Three database roles, not one.** The overlay requires `API_DATABASE_URL`, `WORKER_DATABASE_URL`,
  and `MIGRATE_DATABASE_URL` separately. The worker's stale-job recovery and purge sweeps run across
  workspaces and need `BYPASSRLS`; granting that to a shared role would silently remove the API's
  tenant fence, and withholding it leaves crashed jobs stuck and deleted bytes retained. Migrations
  need DDL rights that neither runtime role should hold.
- **OCR is off by default in production.** The API image ships no `tesseract` binary or trained data,
  so selecting the engine makes every scanned page fail ingestion rather than producing searchable
  evidence. Build a worker image with `tesseract-ocr`, `tesseract-ocr-tam`, and `tesseract-ocr-eng`
  before setting `OCR_ENGINE`.
- **PostgreSQL, Redis, and object storage are managed.** The bundled containers are moved to an
  inactive profile by the production overlay: single containers with no backup, no failover, and no
  upgrade path are right for a laptop and wrong for anything holding a tenant's documents.
- **The database role is not a superuser.** Row-level security is `FORCE`d but PostgreSQL superusers
  bypass RLS entirely, so a superuser connection silently removes the tenant fence beneath the
  repository scoping.

## Known gaps

Stated rather than implied, because each is the kind of thing found during an incident:

- **The worker exports no metrics.** It is not an HTTP server, so the ingestion alerts in
  `infra/monitoring/alerts.yml` are correct and will not fire until a push gateway or sidecar
  exporter exists. This is the first thing to add after a first deploy, not a detail.
- **No zero-downtime deploy.** `up -d` replaces containers; expect a brief gap. Achieving better
  needs a proxy that drains connections, which is beyond a Compose file.
- **No first-class reindex.** Changing `EMBEDDING_MODEL_VERSION` invalidates stored vectors and there
  is no way to re-embed a `READY` document through the API. See `docs/CONFIGURATION.md`; plan a
  version change as a re-ingestion of the workspace.
- **The backup and restore scripts have not been executed against a real deployment by their
  author.** They are written against the documented topology and their logic is reviewed, but a
  script that talks to Docker, PostgreSQL, and an object store cannot be verified by reading it —
  the first version of these two looked correct and could not have worked. Run both against staging
  and confirm the restored system answers a question with a citation before trusting either.
- **Secrets are environment variables.** The overlay reads them from the deploy environment and fails
  the deploy if any is unset (`${VAR:?}`), which is better than a default but is not a secret
  manager: they are visible to anyone who can run `docker inspect` on the host.
