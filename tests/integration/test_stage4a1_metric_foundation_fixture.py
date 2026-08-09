from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.metrics import MetricFoundationBuilder
from tbm_twin.metrics.io import read_csv, read_json, read_jsonl
from tbm_twin.metrics.models import Stage4A1Config


def test_stage4a1_metric_foundation_fixture(tmp_path: Path) -> None:
    output_dir = tmp_path / "stage4a1"
    result = MetricFoundationBuilder(
        Stage4A1Config(
            repo_root=Path.cwd(),
            output_dir=output_dir,
            generated_at=datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
    ).build()
    assert result.hard_check_failures == 0
    assert len(read_jsonl(output_dir / "causal_operational_baselines.jsonl")) == 455
    assert len(read_jsonl(output_dir / "response_deviation_components.jsonl")) == 5595
    assert len(read_jsonl(output_dir / "cell_operational_response_profiles.jsonl")) == 1322
    assert len(read_jsonl(output_dir / "bitemporal_response_profile_bindings.jsonl")) == 1375
    assert len(read_csv(output_dir / "causal_baseline_future_leakage_audit.csv")) == 0
    manifest = read_json(output_dir / "freeze_manifest.json")
    assert manifest["geological_attention_non_null_count"] == 0
    assert manifest["future_baseline_leakage_count"] == 0
    assert manifest["grs_status"] == "GEOLOGICAL_ATTENTION_MAPPING_NOT_FROZEN"
    assert manifest["grci_status"] == "DEPENDENT_METRICS_NOT_BUILT_IN_STAGE4A1"
