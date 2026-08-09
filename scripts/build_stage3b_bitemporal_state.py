"""Build Stage 3B bitemporal epistemic state candidate artifacts."""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

from tbm_twin.bitemporal import Stage3BConfig, Stage3BRevisionBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-at", required=True, help="Timezone-aware ISO datetime")
    parser.add_argument("--knowledge-cutoff-date", required=True, help="YYYY-MM-DD local date")
    parser.add_argument(
        "--output-dir",
        default="artifacts/stage3b_bitemporal_epistemic_state_v1_1",
    )
    parser.add_argument(
        "--stage3a-dir",
        default="artifacts/stage3a_initial_epistemic_state_v1_1",
    )
    parser.add_argument(
        "--geology-freeze-dir",
        default="artifacts/stage2_geology_v2_freeze_candidate",
    )
    parser.add_argument(
        "--applicability-dir",
        default="artifacts/stage2d_applicability_v2_1",
    )
    parser.add_argument(
        "--operational-freeze-dir",
        default="artifacts/stage2_plc_operational_freeze_v2",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    config = Stage3BConfig(
        repo_root=Path.cwd(),
        output_dir=Path(args.output_dir),
        stage3a_dir=Path(args.stage3a_dir),
        geology_freeze_dir=Path(args.geology_freeze_dir),
        applicability_dir=Path(args.applicability_dir),
        operational_freeze_dir=Path(args.operational_freeze_dir),
        generated_at=datetime.fromisoformat(args.generated_at),
        knowledge_cutoff_date=date.fromisoformat(args.knowledge_cutoff_date),
        overwrite=args.overwrite,
    )
    result = Stage3BRevisionBuilder(config).build()
    print(
        "Stage 3B bitemporal state complete: "
        f"version1={result.version1_count}, "
        f"revision_versions={result.revision_version_count}, "
        f"revision_events={result.revision_event_count}, "
        f"revision_links={result.revision_link_count}, "
        f"hard_checks={result.hard_check_issue_count}"
    )
    print(f"Artifacts: {result.output_dir.relative_to(config.repo_root)}")
    return 0 if result.hard_check_issue_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
