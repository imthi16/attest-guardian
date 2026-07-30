"""The floors every measured number has to clear.

Held in one versioned JSON file rather than scattered as constants across test
modules, because a threshold is a promise about the product and a promise nobody
can find is not one. Grouping them also makes the diff legible: lowering a bar
is a one-line change in a file whose only purpose is to state the bars, so it
cannot be slipped in alongside the change that needed it lowered.

A missing key is an error, never a default. Defaulting would let a metric be
added to a report with no bar attached and read as passing, which is the same as
not measuring it.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.evaluation.datasets import DatasetError, evaluation_root

THRESHOLDS_NAME = "thresholds.json"


def _validated(group: str, metric: str, raw: object) -> float:
    """A floor has to be a real number in [0, 1], or it disables the check.

    ``NaN`` is the dangerous case and the reason this exists: JSON carries it as
    the string ``"NaN"``, ``float()`` accepts it, and every comparison against it
    is false — so ``observed < NaN`` never fires and the metric passes forever,
    silently, no matter how far it regresses. A threshold that cannot fail is
    worse than no threshold, because the report still shows the bar.
    """
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        message = f"threshold {group}.{metric} is not a number: {raw!r}"
        raise DatasetError(message) from error
    if not math.isfinite(value):
        message = f"threshold {group}.{metric} is not finite: {raw!r}"
        raise DatasetError(message)
    if not 0.0 <= value <= 1.0:
        message = f"threshold {group}.{metric} must be a rate in [0, 1], not {value}"
        raise DatasetError(message)
    return value


@dataclass(frozen=True)
class Thresholds:
    """Versioned metric floors, addressed as ``group.metric``."""

    version: str
    values: dict[str, dict[str, float]]

    def floor(self, group: str, metric: str) -> float:
        try:
            return float(self.values[group][metric])
        except KeyError as error:
            message = (
                f"no threshold for {group}.{metric} in {THRESHOLDS_NAME}; "
                "every reported metric needs a declared floor"
            )
            raise DatasetError(message) from error

    def group(self, group: str) -> dict[str, float]:
        try:
            return dict(self.values[group])
        except KeyError as error:
            message = f"no threshold group {group!r} in {THRESHOLDS_NAME}"
            raise DatasetError(message) from error

    @property
    def digest(self) -> str:
        """A hash of the floors themselves, for the report to record.

        The version label is a string nothing forces anyone to bump, so a report
        that cited only the label could claim to have been measured against bars
        that had since moved. This is derived from the values, so it moves
        whenever they do.
        """
        canonical = json.dumps(self.values, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_thresholds(root: Path | None = None) -> Thresholds:
    base = root or evaluation_root()
    path = base / THRESHOLDS_NAME
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        message = f"{THRESHOLDS_NAME} is missing"
        raise DatasetError(message) from error
    except json.JSONDecodeError as error:
        message = f"{THRESHOLDS_NAME} is not valid JSON: {error}"
        raise DatasetError(message) from error
    return Thresholds(
        version=str(payload["version"]),
        values={
            group: {metric: _validated(group, metric, value) for metric, value in metrics.items()}
            for group, metrics in payload["thresholds"].items()
        },
    )


__all__ = ["THRESHOLDS_NAME", "Thresholds", "load_thresholds"]
