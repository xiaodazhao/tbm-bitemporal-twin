from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from tbm_twin.metrics.io import read_csv, read_json, read_jsonl
from tbm_twin.metrics.stage4a1_1_builder import Stage4A11Builder


def test_stage4a1_1_method_freeze_fixture(tmp_path: Path) -> None:
    output_dir = tmp_path / "stage4a1_1"
    result = Stage4A11Builder(
        repo_root=Path.cwd(),
        generated_at=datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        output_dir=output_dir,
    ).build()
    assert result.hard_check_failures == 0
    manifest = read_json(output_dir / "freeze_manifest.json")
    assert manifest["rpm_regime_count"] == 2
    assert manifest["rpm_shift_start_date"] == "2023-12-01"
    assert manifest["mapping_review_count"] == 44
    assert manifest["attention_value_non_null_count"] == 0
    regimes = read_jsonl(output_dir / "operational_measurement_regimes.jsonl")
    rpm_regimes = [row for row in regimes if row["channel_name"] == "cutterhead_rpm"]
    assert all(not row["usable_for_scalar_attention"] for row in rpm_regimes)
    daily = read_csv(output_dir / "operational_channel_regime_daily_audit.csv")
    rpm_1201 = next(
        row
        for row in daily
        if row["target_date"] == "2023-12-01" and row["channel_name"] == "cutterhead_rpm"
    )
    assert float(rpm_1201["rpm_consistency_ratio_median"]) > 8
    review = yaml.safe_load((output_dir / "geological_attention_mapping_review.yaml").read_text())
    assert all(row["attention_value"] is None for row in review["mappings"])
    assert len(read_csv(output_dir / "stage4a1_1_hard_check.csv")) >= 1
