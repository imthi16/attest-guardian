"""Counters and histograms, rendered in the Prometheus text format.

Written rather than pulled in, because the exposition format is a dozen lines of
text and the client library is a process-global singleton that fights every test
wanting an isolated registry. A registry that can be constructed per test is
worth more here than the features that library adds.

The metric set is chosen so an operator can answer the questions this product
actually gets asked: is it up, is it slow, is it failing, is it *abstaining*,
and is ingestion keeping up. That fourth one is peculiar to this platform — a
rising abstention rate is not an error and would not appear in any error metric,
but it is the clearest signal that retrieval has regressed or a corpus has gone
stale, and it is exactly the shape of failure that otherwise reaches users
before it reaches an operator.

**No label may carry tenant content.** Labels are cardinality *and* exposure: a
`workspace_id` label makes every scrape enumerate the tenants, and a `query`
label would publish questions to anyone who can read the metrics endpoint. Label
values are validated against that rule on the way in.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import Protocol

from app.observability.redaction import classify

# Buckets in seconds, spanning a fast cached read to a slow grounded answer.
# Chosen so the p95 of a normal answer lands mid-range rather than in the final
# bucket, where a histogram stops being able to distinguish "slow" from "worse".
DEFAULT_BUCKETS = (0.005, 0.025, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

Labels = tuple[tuple[str, str], ...]


class MetricFamily(Protocol):
    """What the registry needs of a metric to export it."""

    name: str

    def render(self) -> list[str]: ...


class MetricError(Exception):
    """A metric was declared or observed in a way that cannot be exported."""


# A label may not be an identifier. This is *stricter* than the log rule, and
# deliberately so: a `workspace_id` is exactly what an incident log needs and
# exactly what a metric must not carry. Every distinct value becomes a permanent
# time series, so an id label grows the storage without bound — and because a
# scrape has no per-tenant authorization, the label set is a tenant directory
# published to whoever can reach the endpoint.
_IDENTIFIER_SUFFIXES = ("_id", "_ids", "_uuid", "_key", "_hash")
_IDENTIFIER_NAMES = frozenset({"id", "user", "tenant", "workspace", "document", "chunk"})


def _label_error(name: str, why: str) -> MetricError:
    return MetricError(
        f"metric label {name!r} {why}; labels must be low-cardinality, "
        "non-sensitive dimensions such as a route template, a stage, or a status"
    )


def _normalize(labels: dict[str, str] | None) -> Labels:
    """Sort labels into a stable key, refusing any that must not be a dimension.

    Content and credentials are judged by the same classifier the log redactor
    uses, so "what may be logged" and "what may be labelled" cannot drift apart.
    Identifiers are then refused on top of that, because a metric label is the
    one place where a field that is perfectly safe to log is still wrong.
    """
    if not labels:
        return ()
    for name in labels:
        if classify(name) != "keep":
            raise _label_error(name, "may carry tenant content or a credential")
        folded = name.casefold()
        if folded in _IDENTIFIER_NAMES or folded.endswith(_IDENTIFIER_SUFFIXES):
            raise _label_error(name, "is an identifier, so it is unbounded cardinality")
    return tuple(sorted((name, str(value)) for name, value in labels.items()))


def _render_labels(labels: Labels, extra: tuple[tuple[str, str], ...] = ()) -> str:
    combined = tuple(labels) + extra
    if not combined:
        return ""
    inner = ",".join(f'{name}="{_escape(value)}"' for name, value in combined)
    return "{" + inner + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@dataclass
class Counter:
    """A monotonically increasing total."""

    name: str
    help_text: str
    values: dict[Labels, float] = field(default_factory=dict)

    def increment(self, amount: float = 1.0, **labels: str) -> None:
        if amount < 0:
            message = "a counter may not decrease"
            raise MetricError(message)
        key = _normalize(labels)
        self.values[key] = self.values.get(key, 0.0) + amount

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} counter"]
        for key, value in sorted(self.values.items()):
            lines.append(f"{self.name}_total{_render_labels(key)} {_number(value)}")
        return lines


@dataclass
class Histogram:
    """Cumulative buckets, a sum, and a count — the Prometheus histogram shape."""

    name: str
    help_text: str
    buckets: tuple[float, ...] = DEFAULT_BUCKETS
    counts: dict[Labels, list[int]] = field(default_factory=dict)
    sums: dict[Labels, float] = field(default_factory=dict)
    totals: dict[Labels, int] = field(default_factory=dict)

    def observe(self, value: float, **labels: str) -> None:
        if not math.isfinite(value):
            message = "a histogram observation must be finite"
            raise MetricError(message)
        key = _normalize(labels)
        counts = self.counts.setdefault(key, [0] * len(self.buckets))
        for index, edge in enumerate(self.buckets):
            if value <= edge:
                counts[index] += 1
        self.sums[key] = self.sums.get(key, 0.0) + value
        self.totals[key] = self.totals.get(key, 0) + 1

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} histogram"]
        for key in sorted(self.totals):
            counts = self.counts[key]
            for edge, count in zip(self.buckets, counts, strict=True):
                labels = _render_labels(key, (("le", _number(edge)),))
                lines.append(f"{self.name}_bucket{labels} {count}")
            total = self.totals[key]
            lines.append(f"{self.name}_bucket{_render_labels(key, (('le', '+Inf'),))} {total}")
            lines.append(f"{self.name}_sum{_render_labels(key)} {_number(self.sums[key])}")
            lines.append(f"{self.name}_count{_render_labels(key)} {total}")
        return lines


def _number(value: float) -> str:
    """Render without a trailing `.0`, which Prometheus accepts but humans re-read."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


class MetricRegistry:
    """Every metric one process exposes.

    Instantiable rather than global so a test can hold its own, and guarded by a
    lock because the ingestion worker observes from its own loop while the API
    scrapes from a request.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}

    def counter(self, name: str, help_text: str) -> Counter:
        with self._lock:
            if name in self._histograms:
                message = f"{name} is already registered as a histogram"
                raise MetricError(message)
            return self._counters.setdefault(name, Counter(name, help_text))

    def histogram(
        self,
        name: str,
        help_text: str,
        buckets: tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> Histogram:
        with self._lock:
            if name in self._counters:
                message = f"{name} is already registered as a counter"
                raise MetricError(message)
            return self._histograms.setdefault(name, Histogram(name, help_text, buckets))

    def render(self) -> str:
        """The whole registry in Prometheus text exposition format."""
        with self._lock:
            families: list[MetricFamily] = [
                *self._counters.values(),
                *self._histograms.values(),
            ]
        lines: list[str] = []
        for family in sorted(families, key=lambda item: item.name):
            lines.extend(family.render())
        return "\n".join(lines) + "\n" if lines else ""


# --- the process-wide registry and the metrics this platform reports ---------

REGISTRY = MetricRegistry()

REQUESTS = REGISTRY.counter(
    "attest_http_requests",
    "HTTP requests by method, route template, and status class.",
)
REQUEST_DURATION = REGISTRY.histogram(
    "attest_http_request_duration_seconds",
    "Wall-clock duration of an HTTP request, by route template.",
)
ANSWERS = REGISTRY.counter(
    "attest_answers",
    "Grounded-answer outcomes by decision. A rising abstention share is the "
    "earliest signal that retrieval or a corpus has regressed.",
)
ANSWER_DURATION = REGISTRY.histogram(
    "attest_answer_duration_seconds",
    "End-to-end duration of the grounded-answer pipeline.",
)
RETRIEVAL_DURATION = REGISTRY.histogram(
    "attest_retrieval_duration_seconds",
    "Duration of hybrid retrieval, excluding generation and verification.",
)
CLAIMS = REGISTRY.counter(
    "attest_claims",
    "Claim verdicts assigned by the verifier. Dropped claims that never reach "
    "an answer are counted here and nowhere else.",
)
INGESTION_STAGES = REGISTRY.counter(
    "attest_ingestion_stages",
    "Ingestion stage completions by stage and result.",
)
INGESTION_JOBS = REGISTRY.counter(
    "attest_ingestion_jobs",
    "Ingestion jobs by result. Distinct from stage counts: a job claimed with "
    "no stage completing is a stalled worker, which no stage metric can show.",
)
INGESTION_DURATION = REGISTRY.histogram(
    "attest_ingestion_stage_duration_seconds",
    "Duration of one ingestion stage.",
)
MODEL_CALLS = REGISTRY.counter(
    "attest_model_calls",
    "Calls to an embedding, rerank, or OCR provider, by kind and result.",
)
MODEL_DURATION = REGISTRY.histogram(
    "attest_model_call_duration_seconds",
    "Duration of one provider call, by kind.",
)


def status_class(status_code: int) -> str:
    """`2xx`, `4xx`, … — a class rather than a code, to bound cardinality."""
    return f"{status_code // 100}xx"


__all__ = [
    "ANSWERS",
    "ANSWER_DURATION",
    "CLAIMS",
    "DEFAULT_BUCKETS",
    "INGESTION_DURATION",
    "INGESTION_JOBS",
    "INGESTION_STAGES",
    "MODEL_CALLS",
    "MODEL_DURATION",
    "REGISTRY",
    "REQUESTS",
    "REQUEST_DURATION",
    "RETRIEVAL_DURATION",
    "Counter",
    "Histogram",
    "MetricError",
    "MetricRegistry",
    "status_class",
]
