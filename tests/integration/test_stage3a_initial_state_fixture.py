import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.state import Stage3AStateBuilder, Stage3AStateConfig
from tbm_twin.state.io import read_jsonl


def test_stage3a_builds_initial_state_from_formal_freezes(tmp_path: Path) -> None:
    output_dir = tmp_path / "stage3a"
    config = Stage3AStateConfig(
        repo_root=Path.cwd(),
        output_dir=output_dir,
        generated_at=datetime(2026, 7, 30, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        overwrite=True,
    )

    result = Stage3AStateBuilder(config).build()

    assert result["daily_state_count"] == 91
    assert result["hard_check_count"] == 0
    assert len(read_jsonl(output_dir / "daily_construction_states.jsonl")) == 91

    versions = read_jsonl(output_dir / "initial_construction_state_versions.jsonl")
    geological_links = read_jsonl(output_dir / "state_geological_evidence_links.jsonl")
    response_links = read_jsonl(output_dir / "state_response_evidence_links.jsonl")
    located_points = read_jsonl(output_dir / "daily_located_point_operational_events.jsonl")
    daily_states = read_jsonl(output_dir / "daily_construction_states.jsonl")

    assert not [row for row in versions if row["target_date"] == "2023-11-06"]
    assert not [row for row in geological_links if row["target_date"] == "2023-11-06"]
    assert not [row for row in response_links if row["target_date"] == "2023-11-06"]
    nov_06_state = next(row for row in daily_states if row["target_date"] == "2023-11-06")
    assert nov_06_state["episode_ids"]
    assert all(row["historical_transaction_time"] is None for row in versions)
    assert len({row["response_evidence_id"] for row in response_links}) == 5425
    assert len(response_links) == 5510
    assert len(located_points) == 95
    assert {row["spatial_relation"] for row in response_links} == {
        "INTERVAL_OVERLAP",
        "POINT_IN_CELL",
    }
    assert all(
        row["trusted_overlap_length_m"] == 0.0
        for row in response_links
        if row["trusted_overlap_kind"] == "POINT"
    )
    with (output_dir / "state_epistemic_integrity_audit.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        epistemic_rows = list(csv.DictReader(handle))
    assert epistemic_rows
    assert {row["status"] for row in epistemic_rows} == {"PASS"}
    with (output_dir / "response_state_coverage_audit.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        coverage_rows = list(csv.DictReader(handle))
    assert len(coverage_rows) == 5595
    assert {row["status"] for row in coverage_rows} == {"PASS"}
