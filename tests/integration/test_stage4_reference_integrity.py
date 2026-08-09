from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.metrics.io import read_csv
from tbm_twin.metrics.stage4a2_builder import Stage4A2Builder


def test_stage4_full_reference_integrity_audit_passes(tmp_path: Path) -> None:
    output_dir = tmp_path / "stage4"
    Stage4A2Builder(
        repo_root=Path.cwd(),
        generated_at=datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        output_dir=output_dir,
    ).build()
    rows = read_csv(output_dir / "stage4_metric_reference_integrity_audit.csv")
    assert rows
    assert all(row["status"] == "PASS" for row in rows)
