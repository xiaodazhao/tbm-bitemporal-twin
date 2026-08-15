"""Stage 5B formal freeze hard-check tests."""

from __future__ import annotations

from tests.unit.stage5b_helpers import read_csv, stage5b_formal_artifact


def test_stage5b_freeze_hard_check(tmp_path_factory) -> None:
    artifact = stage5b_formal_artifact(tmp_path_factory)
    rows = read_csv(artifact / "stage5b_freeze_hard_check.csv")
    by_name = {row["check_name"]: row for row in rows}

    assert by_name["issue_count"]["actual"] == "0"
    assert all(row["status"] == "PASS" for row in rows)
