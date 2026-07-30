from __future__ import annotations

import json
import subprocess
import sys

from tests.conftest import base_rows, write_plc_csv


def test_stage1_cli_pipeline(tmp_path) -> None:
    raw = write_plc_csv(tmp_path / "raw.csv", base_rows())
    parquet = tmp_path / "normalized.parquet"
    episodes_json = tmp_path / "episodes.json"

    normalize = subprocess.run(
        [sys.executable, "scripts/normalize_plc.py", "--input", str(raw), "--output", str(parquet)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert normalize.returncode == 0, normalize.stderr

    build = subprocess.run(
        [
            sys.executable,
            "scripts/build_episodes.py",
            "--input",
            str(parquet),
            "--output",
            str(episodes_json),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    payload = json.loads(episodes_json.read_text(encoding="utf-8"))
    assert len(payload["episodes"]) == 1
    assert payload["spatial_footprints"][0]["consistency_status"] == "PRIMARY_CHANNEL_ONLY"
