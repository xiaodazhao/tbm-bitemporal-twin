from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.metrics.io import read_json, read_jsonl
from tbm_twin.metrics.stage4a2_builder import Stage4A2Builder


def test_generated_at_does_not_change_business_ids_or_metric_values(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    Stage4A2Builder(
        repo_root=Path.cwd(),
        generated_at=datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        output_dir=first,
    ).build()
    Stage4A2Builder(
        repo_root=Path.cwd(),
        generated_at=datetime(2026, 8, 10, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        output_dir=second,
    ).build()
    keys = [
        "state_metric_summary_id",
        "state_rai_id",
        "state_grs_id",
        "state_grci_id",
        "rai",
        "rai_status",
        "grs",
        "grs_status",
        "grci",
        "grci_status",
    ]
    first_rows = read_jsonl(first / "state_metric_summary.jsonl")
    second_rows = read_jsonl(second / "state_metric_summary.jsonl")
    assert [{key: row[key] for key in keys} for row in first_rows] == [
        {key: row[key] for key in keys} for row in second_rows
    ]
    first_method = read_json(first / "method_version.json")
    second_method = read_json(second / "method_version.json")
    assert first_method["source_snapshot_sha256"] == second_method["source_snapshot_sha256"]
    assert first_method["source_tree_hash"] == second_method["source_tree_hash"]
