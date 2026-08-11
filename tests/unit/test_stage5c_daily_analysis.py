"""Stage 5C daily analysis tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_csv, read_json, stage5c_artifact


def test_stage5c_daily_analysis(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    rows = read_csv(artifact / "daily_expressibility.csv")
    manifest = read_json(artifact / "analysis_universe_manifest.json")

    assert len(rows) == manifest["valid_date_count"]
    assert sum(int(row["opportunity_count"]) for row in rows) == 8679
    assert sum(int(row["expressible_count"]) for row in rows) == 6279
