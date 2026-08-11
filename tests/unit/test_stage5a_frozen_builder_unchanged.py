"""Stage 5B boundary test for the frozen Stage 5A builder script."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_stage5a_frozen_builder_script_matches_frozen_tag() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "stage5a-claim-contract-v1-frozen^{}",
            "--",
            "scripts/build_stage5a_claim_contract.py",
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert diff == ""
