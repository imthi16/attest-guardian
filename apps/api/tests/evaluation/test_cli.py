"""The two command-line entry points, which are how a human uses any of this.

`make evaluate` and `make evaluate-refresh` are the documented workflow, so they
are tested rather than assumed: an exit code that did not track the verdict would
make a red evaluation look green in CI, which is worse than not running it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from app.evaluation import datasets as datasets_module
from app.evaluation import report as report_module
from app.evaluation import thresholds as thresholds_module
from app.evaluation.datasets import evaluation_root

pytestmark = pytest.mark.usefixtures("sandboxed_root")


@pytest.fixture
def sandboxed_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every module at a writable copy, so a CLI run never edits the source.

    Each module imported `evaluation_root` by name, so each holds its own
    reference and each has to be redirected — patching one and assuming the rest
    followed would leave a test quietly reading the real files.
    """
    destination = tmp_path / "evaluation"
    shutil.copytree(evaluation_root(), destination)
    for module in (datasets_module, report_module, thresholds_module):
        monkeypatch.setattr(module, "evaluation_root", lambda *_: destination)
    return destination


def test_the_report_command_prints_the_metrics_and_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = report_module._main([])  # noqa: SLF001 - exercising the CLI entry point

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["metrics"]["isolation"]["containment"] == 1.0
    assert printed["threshold_version"]


def test_the_report_command_writes_the_baseline_without_timings(
    sandboxed_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Timings differ per machine; a baseline that churned every run gets reviewed by nobody."""
    written = sandboxed_root / "reports" / "baseline.json"
    written.unlink(missing_ok=True)

    assert report_module._main(["--write"]) == 0  # noqa: SLF001 - CLI entry point
    assert "wrote" in capsys.readouterr().out

    payload = json.loads(written.read_text(encoding="utf-8"))
    assert "performance" not in payload
    assert payload["metrics"]


def test_a_failed_threshold_exits_non_zero_and_names_the_metric(
    sandboxed_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An exit code that ignored the verdict would make a red evaluation look green."""
    thresholds = sandboxed_root / "thresholds.json"
    payload = json.loads(thresholds.read_text(encoding="utf-8"))
    payload["thresholds"]["abstention"]["recall"] = 1.0
    thresholds.write_text(json.dumps(payload), encoding="utf-8")

    assert report_module._main([]) == 1  # noqa: SLF001 - CLI entry point

    assert "abstention.recall" in capsys.readouterr().err


def test_the_refresh_command_records_the_new_digests(
    sandboxed_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = sandboxed_root / "datasets" / "corpus.json"
    corpus.write_text(
        json.dumps({"version": "test", "chunks": []}),
        encoding="utf-8",
    )

    assert datasets_module._main(["--refresh"]) == 0  # noqa: SLF001 - CLI entry point

    assert "corpus.json" in capsys.readouterr().out
    recorded = json.loads((sandboxed_root / "manifest.json").read_text(encoding="utf-8"))
    assert recorded["datasets"]["corpus.json"] != ""
    # And the tampered file now loads, which is the whole point of refreshing.
    assert datasets_module.load_datasets(sandboxed_root).corpus == ()


def test_the_refresh_command_refuses_to_run_by_accident(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Recomputing digests is destructive to the check, so it needs the flag."""
    assert datasets_module._main([]) == 2  # noqa: SLF001 - CLI entry point

    assert "--refresh" in capsys.readouterr().err
