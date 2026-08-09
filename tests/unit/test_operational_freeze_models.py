from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tbm_twin.operational_freeze.models import OperationalFreezeConfig


def test_reconstruction_time_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="reconstruction_time"):
        OperationalFreezeConfig(
            repo_root=Path("."),
            output_dir=Path("artifacts/test"),
            reconstruction_time=datetime(2023, 1, 1),
        )


def test_reconstruction_time_accepts_explicit_aware_value() -> None:
    config = OperationalFreezeConfig(
        repo_root=Path("."),
        output_dir=Path("artifacts/test"),
        reconstruction_time=datetime(2026, 7, 30, tzinfo=UTC),
    )
    assert config.reconstruction_time.isoformat() == "2026-07-30T00:00:00+00:00"


def test_freeze_cli_requires_reconstruction_time(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_stage2e_plc_operational_freeze.py",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=Path.cwd(),
        env={
            **os.environ,
            "PYTHONPATH": str(Path.cwd() / "src"),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--reconstruction-time" in result.stderr


def test_applicability_v2_1_cli_requires_generated_at(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_stage2d_applicability_v2_1.py",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=Path.cwd(),
        env={
            **os.environ,
            "PYTHONPATH": f"{Path.cwd() / 'src'}:{Path.cwd()}",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--generated-at" in result.stderr
