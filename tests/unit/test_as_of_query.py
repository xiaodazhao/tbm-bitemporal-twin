from __future__ import annotations

from pathlib import Path

from tbm_twin.bitemporal.query import AsOfStateQuery
from tbm_twin.state.io import write_jsonl


def test_as_of_query_returns_previous_version_before_revision(tmp_path: Path) -> None:
    write_jsonl(
        tmp_path / "bitemporal_state_versions.jsonl",
        [
            {
                "bitemporal_version_id": "v1",
                "valid_date": "2023-09-22",
                "cell_id": "cell_a",
                "knowledge_time_start_local_date": "2023-09-22",
                "knowledge_time_end_local_date": "2023-09-23",
                "version_number": 1,
            },
            {
                "bitemporal_version_id": "v2",
                "valid_date": "2023-09-22",
                "cell_id": "cell_a",
                "knowledge_time_start_local_date": "2023-09-23",
                "knowledge_time_end_local_date": None,
                "version_number": 2,
            },
        ],
    )
    query = AsOfStateQuery(tmp_path)
    assert query.get_state_as_known("2023-09-22", "cell_a", "2023-09-21") is None
    assert (
        query.get_state_as_known("2023-09-22", "cell_a", "2023-09-22")["bitemporal_version_id"]
        == "v1"
    )
    assert (
        query.get_state_as_known("2023-09-22", "cell_a", "2023-09-23")["bitemporal_version_id"]
        == "v2"
    )
