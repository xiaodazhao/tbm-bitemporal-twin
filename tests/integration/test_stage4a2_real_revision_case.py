from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.metrics.io import read_csv
from tbm_twin.metrics.stage4a2_builder import Stage4A2Builder


def test_stage4a2_real_revision_case(tmp_path: Path) -> None:
    output_dir = tmp_path / "stage4a2"
    Stage4A2Builder(
        repo_root=Path.cwd(),
        generated_at=datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        output_dir=output_dir,
    ).build()
    cases = {
        row["case_name"]: row
        for row in read_csv(output_dir / "fixed_stage4a2_metric_case_audit.csv")
    }
    assert cases["fixed_revision_rai_invariant"]["status"] == "PASS"
    assert cases["fixed_revision_grs_v1"]["status"] == "PASS"
    assert cases["fixed_revision_grs_v2"]["status"] == "PASS"
    assert cases["fixed_revision_grci_changes"]["status"] == "PASS"
