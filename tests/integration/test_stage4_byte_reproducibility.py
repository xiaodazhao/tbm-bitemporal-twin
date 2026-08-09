from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tbm_twin.metrics.io import read_json
from tbm_twin.metrics.stage4a2_builder import Stage4A2Builder


def _hashes(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(item for item in directory.rglob("*") if item.is_file())
    }


def test_stage4_same_generated_at_outputs_are_byte_identical(tmp_path: Path) -> None:
    generated_at = datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    build_a = tmp_path / "build_a"
    build_b = tmp_path / "build_b"
    Stage4A2Builder(repo_root=Path.cwd(), generated_at=generated_at, output_dir=build_a).build()
    Stage4A2Builder(repo_root=Path.cwd(), generated_at=generated_at, output_dir=build_b).build()

    files_a = _hashes(build_a)
    files_b = _hashes(build_b)
    assert files_a.keys() == files_b.keys()
    assert files_a == files_b

    audited = tmp_path / "audited"
    Stage4A2Builder(
        repo_root=Path.cwd(),
        generated_at=generated_at,
        output_dir=audited,
        reproducibility_build_a_dir=build_a,
        reproducibility_build_b_dir=build_b,
    ).build()
    summary = read_json(audited / "stage4_byte_reproducibility_summary.json")
    assert summary["byte_difference_count"] == 0
    assert summary["source_snapshot_sha_equal"] is True
    assert summary["all_formal_outputs_byte_identical"] is True
