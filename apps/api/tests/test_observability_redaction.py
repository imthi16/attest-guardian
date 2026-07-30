"""Nothing a log line carries may undo a boundary the rest of the system holds.

Retrieval is authorized, storage is workspace-scoped, answers are cited — and a
single debug line writing the user's question and a paragraph of their document
ships all of it to an aggregator that has none of those controls. Nothing fails,
nobody is told, and it cannot be taken back.

So these are the tests for the last enforcement point. They are written from the
attacker's and the careless developer's side: what does someone *actually* put in
`extra=` that must not survive, and what happens to a field nobody classified.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from app.observability.logging import JsonFormatter, configure_logging
from app.observability.redaction import REDACTED, classify, fingerprint, redact_fields

TAMIL_QUESTION = "ஒப்பந்தம் எப்போது முடிவடைகிறது?"
EVIDENCE = "The invoice payment is due within thirty days of receipt."


def emit(**fields: object) -> dict[str, object]:
    """Log one record through the real formatter and read back what shipped."""
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    logging.getLogger("app.test").info("event.name", extra=fields)
    record: dict[str, object] = json.loads(stream.getvalue().strip())
    return record


def test_a_credential_never_survives_in_any_form() -> None:
    """Not even a length: a short token is a different fact from a long one."""
    record = emit(
        password="correct-horse-battery",
        jwt_secret="a-real-signing-secret",
        refresh_token="rt_abc123",
        authorization="Bearer eyJhbGciOi",
        api_key="sk-live-1234",
        session_cookie="attest_session=abc",
    )

    for field in ("password", "jwt_secret", "refresh_token", "authorization", "api_key"):
        assert record[field] == REDACTED, field
    serialized = json.dumps(record)
    for secret in ("correct-horse", "signing-secret", "rt_abc123", "eyJhbGciOi", "sk-live"):
        assert secret not in serialized, secret


def test_tenant_content_is_fingerprinted_rather_than_written() -> None:
    """The question and the evidence are the point of the whole platform.

    A fingerprint still lets an operator confirm two lines concern the same
    string — which is what debugging a retrieval actually needs — without the
    text existing outside the tenant's workspace.
    """
    record = emit(query=TAMIL_QUESTION, content=EVIDENCE, quote="due within thirty days")

    serialized = json.dumps(record, ensure_ascii=False)
    assert TAMIL_QUESTION not in serialized
    assert EVIDENCE not in serialized
    assert "due within thirty days" not in serialized
    assert str(record["query"]).startswith("sha256:")
    assert record["query"] == fingerprint(TAMIL_QUESTION)


def test_the_same_text_fingerprints_identically_across_processes() -> None:
    """Unsalted on purpose: joining an API line to a worker line is the use.

    A per-process salt would make every fingerprint useless for the one thing
    they exist to do.
    """
    assert fingerprint(TAMIL_QUESTION) == fingerprint(TAMIL_QUESTION)
    assert fingerprint(TAMIL_QUESTION) != fingerprint(EVIDENCE)


def test_an_unclassified_prose_field_fails_closed() -> None:
    """A field nobody thought about is more likely new content than a new code.

    The two failure directions are not symmetric: over-redacting costs an
    operator a follow-up question, under-redacting cannot be undone.
    """
    record = emit(observation="The tenant asked about their termination clause today.")

    assert str(record["observation"]).startswith("sha256:")


def test_identifiers_counts_and_decisions_are_kept_verbatim() -> None:
    """Redaction that ate the diagnostics would just move the outage elsewhere."""
    record = emit(
        workspace_id="11111111-1111-4111-8111-111111111111",
        job_id="22222222-2222-4222-8222-222222222222",
        stage="chunking",
        status="running",
        decision="answer_with_warning",
        attempt=2,
        duration_ms=41.5,
        retryable=True,
    )

    assert record["workspace_id"] == "11111111-1111-4111-8111-111111111111"
    assert record["stage"] == "chunking"
    assert record["decision"] == "answer_with_warning"
    assert record["attempt"] == 2
    assert record["duration_ms"] == 41.5
    assert record["retryable"] is True


def test_a_stable_machine_code_survives_despite_its_name() -> None:
    """`abstention_reason` reads like prose and is a fixed vocabulary.

    It is the field an operator uses to tell "no evidence" from "the evidence
    contradicts itself", so fingerprinting it would remove the answer to the
    question the log was opened for.
    """
    record = emit(abstention_reason="insufficient_evidence", error_type="TimeoutError")

    assert record["abstention_reason"] == "insufficient_evidence"
    assert record["error_type"] == "TimeoutError"


def test_nested_structures_are_redacted_all_the_way_down() -> None:
    """A trace dictionary is the usual way content reaches a log by accident."""
    record = emit(trace={"query": TAMIL_QUESTION, "top_k": 8, "password": "hunter2"})

    trace = record["trace"]
    assert isinstance(trace, dict)
    assert trace["top_k"] == 8
    assert trace["password"] == REDACTED
    assert str(trace["query"]).startswith("sha256:")
    assert TAMIL_QUESTION not in json.dumps(record, ensure_ascii=False)


def test_a_list_of_evidence_is_redacted_element_by_element() -> None:
    record = emit(quotes=[EVIDENCE, "Refunds are processed within five business days."])

    serialized = json.dumps(record)
    assert EVIDENCE not in serialized
    assert "five business days" not in serialized


def test_an_exception_is_reduced_to_its_type() -> None:
    """A driver error carries its bound parameters — the raw query, evidence text.

    A traceback is therefore one of the richest sources of tenant content in the
    system, arriving on the one path nobody reads until something is wrong.
    """
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    try:
        raise ValueError(f"statement failed for parameters: {TAMIL_QUESTION!r}")
    except ValueError:
        logging.getLogger("app.test").exception("query.failed")

    record = json.loads(stream.getvalue().strip())
    assert record["error_type"] == "ValueError"
    assert TAMIL_QUESTION not in stream.getvalue()
    assert "Traceback" not in stream.getvalue()


def test_the_interpolated_message_is_never_written() -> None:
    """`logger.info("asked %s", query)` is the easiest way to leak by hand.

    The format string is logged, not the result, so the argument never reaches
    free text where no classifier can see it.
    """
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    logging.getLogger("app.test").info("question.received %s", TAMIL_QUESTION)

    assert TAMIL_QUESTION not in stream.getvalue()
    assert json.loads(stream.getvalue().strip())["event"] == "question.received %s"


def test_configure_logging_leaves_exactly_one_handler() -> None:
    """A surviving plain-text handler would re-emit every record unredacted.

    It would also be invisible: the JSON line still appears, correctly redacted,
    while a second copy goes somewhere else in full.
    """
    root = logging.getLogger()
    root.addHandler(logging.StreamHandler(io.StringIO()))

    configure_logging("INFO", stream=io.StringIO())

    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("password", "drop"),
        ("S3_SECRET_KEY", "drop"),
        ("access_token", "drop"),
        ("query", "fingerprint"),
        ("source_filename", "fingerprint"),
        ("email", "fingerprint"),
        ("full_name", "fingerprint"),
        ("workspace_id", "keep"),
        ("attempt", "keep"),
        ("error_type", "keep"),
    ],
)
def test_classification_is_by_field_name(name: str, expected: str) -> None:
    """Value matching cannot work: a token and a document id are both opaque.

    Only the field's name says what it is, which is why the rules are a name
    table and not a set of patterns over values.
    """
    assert classify(name) == expected


def test_redact_fields_is_pure() -> None:
    original = {"query": TAMIL_QUESTION, "workspace_id": "abc"}
    copy = dict(original)

    redact_fields(original)

    assert original == copy
