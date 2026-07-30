"""The API's own description of what it returns, written to disk.

The web app is a separate program that has to agree with this one about every
response body, and it agrees by hand: `apps/web/lib/contracts.ts` restates each
shape as a Zod schema. A hand-written mirror is the right trade — it keeps the
browser bundle free of a generator and lets the client be stricter than the
server where that is useful — but a mirror that drifts is worse than none. It
either rejects a valid response (the page reports a transport failure for data
that arrived correctly) or accepts a field that never comes.

That is not hypothetical: a required `document_id` in the citation mirror, which
the API deliberately does not return, made every stored conversation fail
validation. Nothing caught it but a human reading the diff.

So the schema is generated here, committed under `packages/contracts/`, and
checked from both sides: an API test fails if the committed file no longer
matches the application, and a web test fails if a Zod schema disagrees with the
committed file. Neither side can move alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import Settings
from app.main import create_app

SCHEMA_NAME = "openapi.json"


def contracts_dir(start: Path | None = None) -> Path:
    """Locate ``packages/contracts`` by walking up to the repository marker."""
    for parent in (start or Path(__file__)).resolve().parents:
        if (parent / "AGENTS.md").is_file():
            return parent / "packages" / "contracts"
    message = "repository root not found; the contracts directory is unreachable"
    raise RuntimeError(message)


def schema_path(start: Path | None = None) -> Path:
    return contracts_dir(start) / SCHEMA_NAME


def build_schema() -> dict[str, Any]:
    """The OpenAPI document for the application as configured by default.

    Built from a default :class:`Settings` rather than the ambient environment,
    so the committed file describes the *shape* of the API and not one
    deployment's toggles. ``version`` is dropped for the same reason: a release
    bump is not a contract change, and leaving it in would make every release
    look like one to the drift check.
    """
    schema = create_app(Settings(_env_file=None)).openapi()
    schema.get("info", {}).pop("version", None)
    return schema


def render() -> str:
    return json.dumps(build_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write(start: Path | None = None) -> Path:
    path = schema_path(start)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")
    return path


def _main() -> int:  # pragma: no cover - CLI entry point
    import sys

    path = write()
    sys.stdout.write(f"wrote {path}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(_main())


__all__ = ["SCHEMA_NAME", "build_schema", "contracts_dir", "render", "schema_path", "write"]
