from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.metrics.geological_mapping import build_formal_mapping
from tbm_twin.metrics.io import read_jsonl, read_yaml
from tbm_twin.metrics.stage4a2_builder import Stage4A2Builder


def test_runtime_raw_text_independence_audit_has_real_cases() -> None:
    repo = Path.cwd()
    builder = Stage4A2Builder(
        repo_root=repo,
        generated_at=datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    data = builder._load_data()
    mapping_config = read_yaml(repo / "configs/geological_attention_mapping_v1.yaml")
    _, mapping_by_key, _ = build_formal_mapping(
        data["review_entries"],
        mapping_config["entries"],
        datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    evidence = read_jsonl(
        repo / "artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl"
    )
    rows = builder._grs_structured_dependency_audit(evidence, mapping_by_key)
    source_types = {row["source_type"] for row in rows}
    assert {"SYNTHETIC", "TSP_REPORT", "SONIC_FORECAST", "FACE_SKETCH"} <= source_types
    assert all(row["status"] == "PASS" for row in rows)
    assert all(row["mapping_semantics_equal"] for row in rows)
    assert all(row["dimension_attention_equal"] for row in rows)
    assert all(row["grs_value_equal"] for row in rows)
    assert all(row["grs_status_equal"] for row in rows)
