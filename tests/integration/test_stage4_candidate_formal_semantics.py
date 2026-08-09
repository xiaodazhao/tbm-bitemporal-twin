from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.metrics.io import read_json
from tbm_twin.metrics.stage4a2_builder import Stage4A2Builder


def test_stage4_candidate_to_formal_metric_semantics_are_unchanged(tmp_path: Path) -> None:
    output_dir = tmp_path / "stage4"
    Stage4A2Builder(
        repo_root=Path.cwd(),
        generated_at=datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        output_dir=output_dir,
    ).build()
    summary = read_json(output_dir / "stage4_candidate_formal_semantic_summary.json")
    assert summary["numeric_semantic_difference"] == 0
    assert summary["status_semantic_difference"] == 0
    assert summary["dimension_semantic_difference"] == 0
