"""Stage 5C upstream immutability tests."""

from __future__ import annotations

from tests.unit.stage5c_helpers import read_csv, stage5c_artifact


def test_stage5c_upstream_immutability(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    hard = {row["check_name"]: row for row in read_csv(artifact / "stage5c_hard_check.csv")}

    assert hard["stage5b_modified_count"]["actual"] == "0"
    assert hard["stage5a_modified_count"]["actual"] == "0"
    assert hard["stage4_modified_count"]["actual"] == "0"
    assert hard["issue_count"]["actual"] == "0"
