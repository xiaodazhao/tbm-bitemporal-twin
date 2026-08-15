"""Stage 5C epistemic boundary tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_csv, stage5c_artifact


def test_stage5c_epistemic_analysis(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    boundary = read_csv(artifact / "epistemic_boundary_audit.csv")[0]

    assert boundary["forecast_promoted_to_observed_count"] == "0"
    assert boundary["observed_without_observed_proof_count"] == "0"
    assert boundary["forecast_resolved_as_forecast_count"] == boundary["forecast_claim_count"]
