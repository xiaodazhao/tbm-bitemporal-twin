from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.metrics.io import read_csv, sha256_file
from tbm_twin.metrics.stage4a2_builder import Stage4A2Builder


def test_stage4_source_snapshot_is_deterministic_and_excludes_caches(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for output in [first, second]:
        builder = Stage4A2Builder(
            repo_root=Path.cwd(),
            generated_at=datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            output_dir=output,
        )
        output.mkdir(parents=True)
        builder._write_source_snapshot()

    assert sha256_file(first / "stage4_source_snapshot.tar.gz") == sha256_file(
        second / "stage4_source_snapshot.tar.gz"
    )
    assert (first / "stage4_source_hashes.sha256").read_text() == (
        second / "stage4_source_hashes.sha256"
    ).read_text()
    integrity = read_csv(first / "stage4_source_snapshot_integrity_audit.csv")
    assert all(row["status"] == "PASS" for row in integrity)
    manifest = read_csv(first / "stage4_source_snapshot_manifest.csv")
    assert manifest
    assert not any("__pycache__" in row["relative_path"] for row in manifest)
    assert not any(row["relative_path"].endswith(".pyc") for row in manifest)
