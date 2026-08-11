"""Stage 5C state-role analysis tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_csv, stage5c_artifact


def test_stage5c_role_analysis(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    rows = {row["state_role"]: row for row in read_csv(artifact / "state_role_expressibility.csv")}

    assert rows["LOCAL_BACKGROUND_CELL"]["expressible_count"] == "0"
    assert rows["LOCAL_BACKGROUND_CELL"]["abstain_count"] == "880"
    assert sum(int(row["opportunity_count"]) for row in rows.values()) == 8679
