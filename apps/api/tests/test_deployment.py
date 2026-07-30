"""The deployment shape, checked as data rather than trusted as documentation.

A Compose file is configuration nobody type-checks and CI only validates for
syntax. The failures that matter here are all *semantic* and all silent: an
application that starts without its worker, a production overlay that quietly
keeps a development default for the signing secret, a service publishing a port
onto the host interface. Each of those deploys successfully.

So the topology is asserted. These read the committed files rather than running
anything, so they need no Docker.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.config import Settings
from app.preflight import CheckResult, check_database, check_queue, check_storage, run


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "AGENTS.md").is_file():
            return parent
    message = "repository root not found"
    raise RuntimeError(message)


# Compose's own tags. `!override` tells it to replace a merged value rather than
# extend it — which is how the production overlay removes published ports. They
# are stripped before parsing rather than given constructors, because a
# constructor for a tagged empty sequence trips PyYAML's two-pass construction;
# the tag carries no information these tests need, only the value under it does.
# The tag alone is removed and surrounding whitespace preserved: consuming the
# newline after `depends_on: !override` would fold the following mapping onto
# that line and produce a parse error rather than the value.
_COMPOSE_TAGS = re.compile(r"!(?:override|reset)\b")


def load(relative: str) -> dict[str, Any]:
    text = (repo_root() / relative).read_text(encoding="utf-8")
    document: dict[str, Any] = yaml.safe_load(_COMPOSE_TAGS.sub("", text))
    return document


BASE = load("docker-compose.yml")
PRODUCTION = load("deploy/docker-compose.production.yml")


def test_the_worker_is_part_of_the_application() -> None:
    """The service whose absence is invisible.

    Without it uploads are accepted and never processed: documents sit at
    `pending`, the UI shows them queued, and the API is genuinely healthy the
    whole time. Nothing in liveness or readiness would say a word, so the only
    protection is that the service exists in the file everyone copies.
    """
    worker = BASE["services"]["worker"]

    assert worker["profiles"] == ["application"]
    assert worker["command"] == ["python", "-m", "app.ingestion.worker"]


def test_migrations_run_as_a_step_and_not_inside_a_service() -> None:
    """Replicas booting together would race the same DDL.

    And a migration failing inside a startup path presents as a crash loop
    rather than as a failed deploy, which sends whoever is on call looking in
    entirely the wrong place.
    """
    migrate = BASE["services"]["migrate"]

    assert migrate["restart"] == "no"
    assert migrate["command"][:1] == ["alembic"]
    assert migrate["command"][-2:] == ["upgrade", "head"]

    for service in ("api", "worker"):
        gates = BASE["services"][service]["depends_on"]
        assert gates["migrate"]["condition"] == "service_completed_successfully", service


def test_every_application_service_drops_privileges_and_is_read_only() -> None:
    for name in ("api", "web", "worker", "migrate"):
        service = BASE["services"][name]
        assert service["read_only"] is True, name
        assert "no-new-privileges:true" in service["security_opt"], name
        # Read-only root needs somewhere to write; without it the process fails
        # on its first temporary file, which is rarely on the startup path.
        assert "/tmp" in service["tmpfs"], name  # noqa: S108 - a container mount, not a host path


def test_the_application_environment_is_defined_once() -> None:
    """Three hand-maintained copies drift, and the one that drifts is the worker.

    It is the service nobody exercises locally, so a variable added to the API
    and forgotten there produces a worker that authenticates to storage with
    stale credentials — at the point a user is waiting on a document.
    """
    raw = (repo_root() / "docker-compose.yml").read_text(encoding="utf-8")

    assert "x-app-environment: &app-environment" in raw
    assert raw.count("*app-environment") >= 3


def test_the_three_database_roles_are_distinct() -> None:
    """One DSN for all three services cannot be correct for any of them.

    The worker's stale-job recovery and purge sweeps run *across* workspaces and
    need `BYPASSRLS`. Granting that to a shared role silently removes the API's
    tenant fence — row-level security stops applying to every tenant query.
    Withholding it leaves crashed jobs stuck and deleted bytes retained. And
    migrations need DDL rights that neither runtime role should hold, so a
    compromised API replica cannot drop a table.
    """
    services = PRODUCTION["services"]
    dsns = {
        name: services[name]["environment"]["DATABASE_URL"] for name in ("api", "worker", "migrate")
    }

    assert len(set(dsns.values())) == 3, dsns
    assert "API_DATABASE_URL" in dsns["api"]
    assert "WORKER_DATABASE_URL" in dsns["worker"]
    assert "MIGRATE_DATABASE_URL" in dsns["migrate"]


def test_production_does_not_select_an_ocr_engine_the_image_lacks() -> None:
    """Choosing `tesseract` here fails every scanned page rather than reading it.

    The API image installs no tesseract binary and no trained data, so the
    engine raises on the first page that needs it and the ingestion job fails —
    turning a document that would have been searchable into one that is broken.
    """
    dockerfile = (repo_root() / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    worker_env = PRODUCTION["services"]["worker"]["environment"]

    if "tesseract" not in dockerfile:
        assert "none" in worker_env["OCR_ENGINE"], (
            "the image ships no tesseract, so it must not be the production default"
        )


def test_every_application_image_is_tagged_by_release() -> None:
    """The documented rollback sets `IMAGE_TAG`; something has to consume it.

    Without an `image:` reference the rollback command rebuilds the *current*
    source and starts it again — during an incident, while the operator believes
    they have gone back a release.
    """
    for name in ("api", "worker", "migrate", "web"):
        image = PRODUCTION["services"][name]["image"]
        assert "${IMAGE_TAG" in image, name


def test_production_refuses_to_start_without_real_secrets() -> None:
    """The base file's development defaults are the hazard being removed.

    `${JWT_SECRET:-development-only-change-me}` is right for `make infra-up` and
    catastrophic in production: a typo in the deploy environment would start the
    service with a signing key published in this repository.
    """
    api = PRODUCTION["services"]["api"]["environment"]

    for required in ("JWT_SECRET", "DATABASE_URL", "S3_SECRET_KEY", "CORS_ALLOWED_ORIGINS"):
        assert ":?" in api[required], f"{required} must fail the deploy when unset"
        assert ":-" not in api[required], f"{required} must not carry a default"


def test_production_closes_the_doc_and_debug_surfaces() -> None:
    api = PRODUCTION["services"]["api"]["environment"]

    assert api["APP_ENV"] == "production"
    # Interactive docs hand a reader a complete, accurate map of the API.
    assert api["API_DOCS_ENABLED"] == "false"


def test_production_publishes_no_application_port() -> None:
    """TLS terminates in a proxy, so a published port is plaintext on the host."""
    for name in ("api", "web"):
        assert PRODUCTION["services"][name]["ports"] == [], name


def test_production_parks_the_bundled_datastores() -> None:
    """Single containers with no backup or failover must not hold tenant data.

    They would also be invisible: `DATABASE_URL` points at the managed instance,
    so the bundled Postgres would run alongside holding nothing, publishing 5432
    on the host, and nobody would notice it was there.
    """
    for name in ("postgres", "redis", "minio", "minio-create-bucket"):
        assert PRODUCTION["services"][name]["profiles"] == ["bundled-datastores"], name


def test_the_worker_has_no_healthcheck() -> None:
    """A liveness check that only proved the process was alive would lie.

    The failure that actually happens is a wedged worker — running, claiming
    nothing — and a process-liveness probe reports that as healthy while the
    queue grows.
    """
    assert "healthcheck" not in BASE["services"]["worker"]


# --- preflight --------------------------------------------------------------


async def test_preflight_reports_a_failure_per_dependency() -> None:
    """Each check answers for itself, so a failed deploy names what to fix."""
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://nobody:nobody@127.0.0.1:1/none",
        redis_url="redis://127.0.0.1:1/0",
        s3_endpoint="http://127.0.0.1:1",
    )

    results = await run(settings)

    assert {result.name for result in results} == {"database", "object_storage", "queue"}
    assert all(not result.ok for result in results)
    # The reason *is* included here, unlike the readiness probe: this output goes
    # to a deploy log read by the operator holding the credentials, and hiding it
    # would mean debugging a failed rollout with nothing to go on.
    assert all(result.detail for result in results)


@pytest.mark.parametrize("check", [check_database, check_queue, check_storage])
async def test_an_unreachable_dependency_is_a_result_not_an_exception(
    check: Any,
) -> None:
    """Preflight must report every check, not abort on the first failure.

    Otherwise a deploy with three misconfigurations takes three attempts to
    diagnose, one per run.
    """
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://nobody:nobody@127.0.0.1:1/none",
        redis_url="redis://127.0.0.1:1/0",
        s3_endpoint="http://127.0.0.1:1",
    )

    result = await check(settings)

    assert isinstance(result, CheckResult)
    assert result.ok is False


def test_the_backup_scripts_use_the_configured_stores() -> None:
    """Not `compose exec postgres`, which the production topology parks.

    The first version of these scripts did exactly that: in production it
    reaches a container that is not running, and if somebody started it, it
    would faithfully back up an empty local database and report success. A
    backup that cannot fail loudly is worse than no backup.
    """
    backup = (repo_root() / "scripts" / "backup.sh").read_text(encoding="utf-8")
    restore = (repo_root() / "scripts" / "restore.sh").read_text(encoding="utf-8")

    for script, name in ((backup, "backup.sh"), (restore, "restore.sh")):
        # Comments explain why it is not done; the code must not do it.
        executable = [
            line
            for line in script.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert not any("compose exec" in line for line in executable), name
        assert "DATABASE_URL" in script, name
        assert "S3_ENDPOINT" in script, name


def test_the_manifest_covers_the_objects_as_well_as_the_dump() -> None:
    """Otherwise the runbook's promise to refuse a mismatched pair is false.

    Swapping the objects directory for another date's would pass every check,
    and restored citations would resolve to unrelated evidence with nothing able
    to detect it.
    """
    backup = (repo_root() / "scripts" / "backup.sh").read_text(encoding="utf-8")
    restore = (repo_root() / "scripts" / "restore.sh").read_text(encoding="utf-8")

    assert "objects_sha256" in backup
    assert "objects_sha256" in restore


def test_restore_validates_before_it_destroys() -> None:
    """The ordering is the whole point of the script.

    An earlier version ran `pg_restore --clean` and only then warned that the
    objects directory was missing — by which time the database had been replaced
    and every restored row pointed at bytes that were not there.
    """
    restore = (repo_root() / "scripts" / "restore.sh").read_text(encoding="utf-8")

    first_destructive = restore.index("pg_restore --dbname")
    for guard in ("refusing to restore a database whose documents", "does not match its manifest"):
        assert restore.index(guard) < first_destructive, guard


def test_the_operational_scripts_are_executable_and_documented() -> None:
    """A runbook referring to a script nobody can run is not a runbook."""
    scripts = repo_root() / "scripts"
    runbook = (repo_root() / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")

    for name in ("backup.sh", "restore.sh", "smoke.sh"):
        path = scripts / name
        assert path.is_file(), name
        assert path.stat().st_mode & 0o111, f"{name} is not executable"
        assert name in runbook, f"{name} is not mentioned in the deployment runbook"
