#!/usr/bin/env python3
"""Build the Stage7D v1.1a documentation-only correction."""

from pathlib import Path

from tbm_twin.evaluation.stage7d_correction import build_stage7d_v1_1a_correction

if __name__ == "__main__":
    result = build_stage7d_v1_1a_correction(Path.cwd())
    for key, value in sorted(result.items()):
        print(f"{key}={value}")
