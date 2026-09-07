from __future__ import annotations

import csv
from pathlib import Path

from tbm_twin.evaluation.final_handoff import build_final_handoff

REPO = Path(__file__).resolve().parents[2]


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_final_handoff_builds_traceable_bundle(tmp_path: Path) -> None:
    output = build_final_handoff(REPO, tmp_path / "handoff")

    required = {
        "00_PROJECT_OVERVIEW.md",
        "01_TECHNICAL_PIPELINE.md",
        "02_METHOD_DEFINITION_REGISTRY.csv",
        "03_dataset_scale.csv",
        "04_EXPERIMENT_MASTER_REGISTRY.csv",
        "10_SUPERSEDED_RESULT_REGISTRY.csv",
        "14_RESULT_TRACEABILITY.csv",
        "15_REPOSITORY_RETENTION_PLAN.csv",
        "final_handoff_hard_check.csv",
        "freeze_manifest.json",
        "file_hashes.sha256",
    }
    assert required <= {path.name for path in output.iterdir()}
    assert len(list((output / "paper_tables").glob("table_*.csv"))) == 6
    assert len(list((output / "paper_figures").glob("figure_*.csv"))) == 5

    trace = _rows(output / "14_RESULT_TRACEABILITY.csv")
    assert len(trace) >= 40
    assert all(row["trace_status"] == "RESOLVED" for row in trace)
    assert not any("SOURCE_UNKNOWN" in str(row) for row in trace)

    checks = _rows(output / "final_handoff_hard_check.csv")
    assert checks
    assert all(row["status"] == "PASS" for row in checks)


def test_final_handoff_preserves_frozen_interpretation(tmp_path: Path) -> None:
    output = build_final_handoff(REPO, tmp_path / "handoff")
    text = "\n".join(path.read_text(encoding="utf-8") for path in output.glob("*.md"))

    assert "91 PLC-monitored construction dates" in text
    assert "91 consecutive" not in text
    assert "GRCI = RAI * GRS" in text
    assert "mean_non_null_dimension_attention" in text
    assert "NOT_EXECUTABLE_ON_FROZEN_48_TASK_BENCHMARK" in text
    assert "COARSE_RESOLUTION_STRESS_TEST" in text
    assert "DEFERRED_TO_HUMAN" in text
