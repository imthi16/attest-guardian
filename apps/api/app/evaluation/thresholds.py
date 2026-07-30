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

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.evaluation.datasets import DatasetError, evaluation_root

THRESHOLDS_NAME = "thresholds.json"


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
            group: {metric: float(value) for metric, value in metrics.items()}
            for group, metrics in payload["thresholds"].items()
        },
    )


__all__ = ["THRESHOLDS_NAME", "Thresholds", "load_thresholds"]
