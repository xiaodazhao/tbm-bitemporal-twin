"""Stage 5B determinism tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, stage5b_artifact


def test_claim_builder_repeat_build_business_identity_is_stable(tmp_path_factory) -> None:
    artifact = stage5b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "claim_determinism_audit.csv")

    assert rows
    assert all(int(row["business_diff_count"]) == 0 for row in rows)
    assert all(row["status"] == "PASS" for row in rows)
