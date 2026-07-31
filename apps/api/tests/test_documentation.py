"""Documentation checked as data rather than trusted as prose.

Documentation rots in three specific ways, all of them silent. A link goes
stale when a file is renamed and nobody follows it until a reader does. A
documented command stops existing when a Makefile target is renamed, and the
reader who runs it concludes the project is broken rather than the docs. And an
endpoint reference drifts from the application, which is the worst of the three:
a route table that lists a path the API does not serve is not merely unhelpful,
it is wrong in the same way a stale contract mirror is wrong — confidently, and
about the one thing the reader came for.

None of that needs a running service. These read the committed files, so they
cost nothing and fail in CI rather than in someone's terminal.

External URLs are deliberately not fetched: a test that reaches the network is
a test that fails when a third party has an outage, and a flaky documentation
check is one people learn to ignore.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "AGENTS.md").is_file():
            return parent
    message = "repository root not found"
    raise RuntimeError(message)


ROOT = repo_root()

# Directories whose markdown is not ours: dependencies, build output, and tool
# caches. `.venv` alone contributes thousands of vendored READMEs whose links
# are somebody else's contract.
_EXCLUDED = frozenset(
    {
        ".git",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "node_modules",
    }
)

# A markdown inline link or image. The negative lookbehind on the link pattern
# keeps images out of it so each is counted once, and both tolerate the
# optional title that follows a target.
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_INLINE_CODE = re.compile(r"`([^`]*)`")
_INLINE_LINK_TEXT = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# Bounded to one line: code spans are joined by newlines, and `\s+` would let a
# span ending in "make" borrow the first word of the next one as its target.
_MAKE_TARGET = re.compile(r"\bmake[ \t]+([a-z][a-z0-9-]*)")
_MAKEFILE_TARGET = re.compile(r"^([a-z][a-z0-9-]*):", re.MULTILINE)
_FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


def markdown_files() -> list[Path]:
    return sorted(
        path for path in ROOT.rglob("*.md") if not _EXCLUDED & set(path.relative_to(ROOT).parts)
    )


DOCUMENTS = markdown_files()


def anchors(text: str) -> set[str]:
    """GitHub's heading slugs for a document.

    Fenced blocks are skipped: a `#` starting a shell comment inside one is not
    a heading, and treating it as an anchor would let a broken link pass.
    """
    found: set[str] = set()
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = _HEADING.match(line)
        if heading is None:
            continue
        title = _INLINE_CODE.sub(r"\1", heading.group(2))
        title = _INLINE_LINK_TEXT.sub(r"\1", title).lower()
        title = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE)
        found.add(re.sub(r"\s+", "-", title.strip()))
    return found


def targets(text: str) -> list[tuple[str, str]]:
    """Every relative link and image target in a document, with its raw form."""
    return [
        (match.group(1), match.group(0))
        for pattern in (_LINK, _IMAGE)
        for match in pattern.finditer(text)
        if not match.group(1).startswith(("http://", "https://", "mailto:"))
    ]


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(document: Path) -> None:
    """Every relative link points at a file that exists.

    This is what breaks when a document is renamed, and it is invisible to
    every other check in the repository.
    """
    text = document.read_text(encoding="utf-8")
    broken = [
        raw
        for target, raw in targets(text)
        if target.partition("#")[0]
        and not (document.parent / target.partition("#")[0]).resolve().exists()
    ]
    assert not broken, f"{document.relative_to(ROOT)} links to missing files: {broken}"


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_heading_anchors_resolve(document: Path) -> None:
    """A `#section` link points at a heading that exists.

    A link to a renamed section silently lands at the top of the page, which
    reads as the author pointing at the wrong thing rather than as rot.
    """
    text = document.read_text(encoding="utf-8")
    broken: list[str] = []
    for target, raw in targets(text):
        path_part, _, anchor = target.partition("#")
        if not anchor:
            continue
        if not path_part:
            if anchor not in anchors(text):
                broken.append(raw)
            continue
        resolved = (document.parent / path_part).resolve()
        if resolved.suffix == ".md" and anchor not in anchors(resolved.read_text(encoding="utf-8")):
            broken.append(raw)
    assert not broken, f"{document.relative_to(ROOT)} links to missing sections: {broken}"


def code(text: str) -> str:
    """Only the parts of a document a reader would copy into a shell.

    Prose is excluded because English says "make a", "make an", and "make it",
    and a check that reads those as targets is one that gets deleted rather
    than fixed.
    """
    return "\n".join([*_FENCE.findall(text), *_INLINE_CODE.findall(text)])


def test_documented_make_targets_exist() -> None:
    """Every `make <target>` in the docs is a target the Makefile defines.

    A reader who runs a renamed command concludes the project is broken, not
    the documentation, so this is the check that protects a first impression.
    """
    defined = set(_MAKEFILE_TARGET.findall((ROOT / "Makefile").read_text(encoding="utf-8")))
    missing: dict[str, set[str]] = {}
    for document in DOCUMENTS:
        used = set(_MAKE_TARGET.findall(code(document.read_text(encoding="utf-8"))))
        absent = used - defined
        if absent:
            missing[str(document.relative_to(ROOT))] = absent
    assert not missing, f"documented make targets that do not exist: {missing}"


# The API reference and the application's own description of itself. The
# contract file is generated by `make contracts` and pinned by
# `test_contracts.py`, so checking the reference against it checks it against
# the application without importing one.
API_REFERENCE = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
CONTRACT_PATHS = frozenset(
    json.loads((ROOT / "packages" / "contracts" / "openapi.json").read_text(encoding="utf-8"))[
        "paths"
    ]
)
# Paths as they appear in the reference: inside backticks, in the route tables.
_REFERENCED = frozenset(
    match.group(1) for match in re.finditer(r"`(/api/v1/[^`]*)`", API_REFERENCE)
)


def test_every_documented_endpoint_exists() -> None:
    """The reference never lists a route the API does not serve.

    Only versioned paths are compared. `/metrics` is registered conditionally
    on `METRICS_ENABLED` and so is absent from a contract generated with it
    off — excluding it here is narrower than excluding it from the docs, which
    would leave a deployment-relevant endpoint undocumented.
    """
    invented = sorted(_REFERENCED - CONTRACT_PATHS)
    assert not invented, f"docs/API.md documents paths the API does not serve: {invented}"


def test_every_endpoint_is_documented() -> None:
    """And it lists all of them.

    The direction that catches a new route landing with no reference entry,
    which is how an API reference becomes a partial one nobody trusts.
    """
    undocumented = sorted(
        path for path in CONTRACT_PATHS if path.startswith("/api/v1/") and path not in _REFERENCED
    )
    assert not undocumented, f"endpoints missing from docs/API.md: {undocumented}"


def test_documented_error_codes_are_raised_by_the_application() -> None:
    """Every code on a `Codes:` line exists verbatim in the API source.

    Clients are told to branch on these rather than on messages, so a code
    documented and never raised is a branch that can never be reached — and one
    renamed in the source is a branch that silently stops matching.

    Only the `Codes:` lines are read. Field names and capabilities share the
    shape of a code, and a check that guessed from shape alone would either
    demand that every field be a quoted literal or be quietly narrowed until it
    asserted nothing.
    """
    documented = {
        code
        for line in API_REFERENCE.splitlines()
        if line.startswith("Codes:")
        for code in _INLINE_CODE.findall(line)
    }
    assert documented, "no `Codes:` lines found — the check has stopped reading the reference"
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "apps" / "api" / "app").rglob("*.py")
    )
    unknown = sorted(code for code in documented if f'"{code}"' not in sources)
    assert not unknown, f"docs/API.md names codes absent from the API source: {unknown}"


def test_no_screenshot_is_committed_without_being_shown() -> None:
    """An image in `docs/screenshots` is linked from at least one document.

    The directory is a placeholder that invites captures, so this does not
    forbid them — it forbids the orphan: a screenshot committed to satisfy a
    template, never rendered anywhere, and therefore never checked by a reader
    against what the product actually does.
    """
    directory = ROOT / "docs" / "screenshots"
    assert (directory / "README.md").is_file(), "the screenshot placeholder is missing"
    linked = {
        Path(target).name
        for document in DOCUMENTS
        for target, _ in targets(document.read_text(encoding="utf-8"))
    }
    orphans = sorted(
        path.name
        for path in directory.iterdir()
        if path.suffix.lower() != ".md" and path.name not in linked
    )
    assert not orphans, f"screenshots committed but linked from no document: {orphans}"
