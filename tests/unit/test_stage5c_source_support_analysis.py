"""Stage 5C geological source support tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_csv, stage5c_artifact


def test_stage5c_source_support_analysis(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    rows = read_csv(artifact / "geological_source_support_analysis.csv")

    assert rows
    assert {row["analysis_semantics"] for row in rows} == {
        "support_participation_not_causal_contribution"
    }
    assert any(row["source_type"] == "FACE_SKETCH" for row in rows)
