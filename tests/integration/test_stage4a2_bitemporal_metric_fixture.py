from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.metrics.io import read_csv, read_json, read_jsonl
from tbm_twin.metrics.stage4a2_builder import Stage4A2Builder


def test_stage4a2_bitemporal_metric_fixture(tmp_path: Path) -> None:
    output_dir = tmp_path / "stage4a2"
    result = Stage4A2Builder(
        repo_root=Path.cwd(),
        generated_at=datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        output_dir=output_dir,
    ).build()
    assert result.hard_check_failures == 0
    manifest = read_json(output_dir / "freeze_manifest.json")
    assert manifest["state_metric_summary_count"] == 1375
    assert manifest["mapping_numeric_count"] == 36
    assert manifest["mapping_unmappable_count"] == 8
    assert manifest["rai_revision_change_count"] == 0
    assert len(read_jsonl(output_dir / "state_metric_summary.jsonl")) == 1375
    hard = read_csv(output_dir / "stage4a2_hard_check.csv")
    assert all(row["status"] == "PASS" for row in hard)
