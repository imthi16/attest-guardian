"""What must never reach a log line, and how it is removed.

Logs are the one place where every other guarantee this platform makes can be
quietly undone. Retrieval is authorized, storage is scoped, answers are cited —
and then a debug line writes the user's question and a paragraph of their
document into a file that ships to an aggregator with none of those boundaries.
Nothing fails, nobody is told, and the data is out.

So redaction is not a formatter's convenience here; it is the last enforcement
point, and it works by *classification of the field*, not by pattern-matching
the value. Value matching cannot work: a bearer token and a document id are both
opaque strings, and a Tamil sentence looks like any other text. Only the name of
the field says what it is, so the rules below are keyed on names and applied to
every record.

Three treatments, because "remove it" is not always right:

* **Dropped** — credentials and tokens. There is no version of these worth
  keeping; even a length is a hint.
* **Fingerprinted** — content whose *identity* matters for debugging but whose
  text must not persist: a query, an answer, a chunk. A short digest lets an
  operator confirm two log lines concern the same string without recovering it.
* **Kept** — ids, counts, durations, decisions, and stable codes. These are what
  an incident is actually diagnosed from, and they carry no tenant content.

Anything unrecognised is fingerprinted rather than kept, so a field added
without thought fails closed.
"""

from __future__ import annotations

import hashlib
from typing import Any

REDACTED = "[redacted]"

# Substrings that mark a field as a credential. Matched against a case-folded
# field name, so `JWT_SECRET`, `refresh_token`, and `authorization` all hit.
_CREDENTIAL_MARKERS = (
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "credential",
    "cookie",
    "session_key",
    "private_key",
)

# Fields carrying tenant text: a question, an answer, evidence, a filename, a
# person's name or address. Kept as a fingerprint, never verbatim.
_CONTENT_MARKERS = (
    "query",
    "question",
    "answer",
    "content",
    "text",
    "quote",
    "claim",
    "prompt",
    "excerpt",
    "snippet",
    "filename",
    "title",
    "email",
    "full_name",
    "note",
    "message",
    "body",
    "reason",
)

# Names that look like content by the rules above but are safe and useful: a
# stable machine code, a stage name, an exception *type*. Listed explicitly so
# the exception is auditable rather than implied by a cleverer regex.
_SAFE_NAMES = frozenset(
    {
        "error_type",
        "event",
        "message_id",
        "content_hash",
        "abstention_reason",
        "decision_reason_code",
        "stage",
        "status",
        "outcome",
        "decision",
        "verdict",
        "code",
        "reason_code",
    }
)

# Scalars that cannot carry tenant content and are worth reading directly.
_TRANSPARENT_TYPES = (bool, int, float, type(None))


def fingerprint(value: object) -> str:
    """A short, stable digest of a value's text.

    Twelve hex characters: enough to tell two strings apart across log lines
    while far too short to attack, and unsalted so the same query fingerprints
    identically in the API and in the worker — which is the entire point of
    keeping it at all.
    """
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}"


def classify(name: str) -> str:
    """How one field name must be treated: ``drop``, ``fingerprint``, or ``keep``."""
    folded = name.casefold()
    if folded in _SAFE_NAMES:
        return "keep"
    if any(marker in folded for marker in _CREDENTIAL_MARKERS):
        return "drop"
    if any(marker in folded for marker in _CONTENT_MARKERS):
        return "fingerprint"
    return "keep"


def redact_value(name: str, value: object) -> object:
    """Apply the field's treatment to one value.

    A string that is not recognised as an id-like scalar is fingerprinted rather
    than kept: an unfamiliar field is more likely to be new tenant content than
    a new safe code, and the failure directions are not symmetric — an
    over-redacted log costs an operator a follow-up, an under-redacted one
    cannot be undone.
    """
    treatment = classify(name)
    if treatment == "drop":
        return REDACTED
    if treatment == "fingerprint":
        return REDACTED if value is None else fingerprint(value)
    if isinstance(value, _TRANSPARENT_TYPES):
        return value
    if isinstance(value, dict):
        return redact_fields(value)
    if isinstance(value, (list, tuple)):
        return [redact_value(name, item) for item in value]
    return _redact_scalar(value)


def _redact_scalar(value: object) -> object:
    """Keep short identifier-shaped strings; fingerprint anything longer.

    A UUID, a status, or a stage is a scalar an operator reads directly. Prose
    is not, and length is the only signal available once the field name has
    already been judged neutral.
    """
    text = str(value)
    if len(text) <= 64 and "\n" not in text and " " not in text:
        return text
    return fingerprint(text)


def redact_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Redact every field of a log record's structured payload."""
    return {name: redact_value(name, value) for name, value in fields.items()}


__all__ = ["REDACTED", "classify", "fingerprint", "redact_fields", "redact_value"]
