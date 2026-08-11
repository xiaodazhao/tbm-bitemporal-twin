"""Run Stage 5C read-only claim expressibility and abstention analysis."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.claim_analysis.analysis import build_stage5c_analysis
from tbm_twin.claim_analysis.models import STAGE5B_ARTIFACT, STAGE5C_GENERATED_AT, STAGE5C_OUTPUT


def main() -> None:
    """Build the Stage 5C candidate analysis artifact."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--stage5b-artifact", type=Path, default=STAGE5B_ARTIFACT)
    parser.add_argument("--output-dir", type=Path, default=STAGE5C_OUTPUT)
    parser.add_argument("--generated-at", default=STAGE5C_GENERATED_AT)
    args = parser.parse_args()
    build_stage5c_analysis(
        repo_root=args.repo_root,
        stage5b_artifact=args.stage5b_artifact,
        output_dir=args.output_dir,
        generated_at=args.generated_at,
    )


if __name__ == "__main__":
    main()
