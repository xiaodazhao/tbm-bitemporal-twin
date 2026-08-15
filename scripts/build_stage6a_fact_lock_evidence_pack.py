"""Build Stage 6A deterministic FactLocks and controlled Evidence Packs."""

from __future__ import annotations

import argparse
from pathlib import Path

from tbm_twin.realization.build_stage6a import build_stage6a_candidate
from tbm_twin.realization.models import STAGE6A_GENERATED_AT, STAGE6A_OUTPUT


def main() -> None:
    """Run the Stage6A candidate builder."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path(STAGE6A_OUTPUT))
    parser.add_argument("--generated-at", default=STAGE6A_GENERATED_AT)
    args = parser.parse_args()
    build_stage6a_candidate(
        repo_root=args.repo_root,
        output_dir=args.output_dir,
        generated_at=args.generated_at,
    )


if __name__ == "__main__":
    main()
