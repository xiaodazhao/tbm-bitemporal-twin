"""Build combined automatic evaluation for 48 frozen plus 152 supplemental tasks."""

from pathlib import Path

from tbm_twin.evaluation.stage7_supplemental import (
    EVALUATION_DIR,
    build_supplemental_auto_eval,
    upstream_gold_readiness,
)


def main() -> None:
    repo_root = Path.cwd()
    summary = build_supplemental_auto_eval(repo_root)
    gold = upstream_gold_readiness(repo_root, repo_root / EVALUATION_DIR)
    print(f"task_count={summary['task_count']}")
    print(f"hard_check_fail_count={summary['hard_check_fail_count']}")
    print(f"upstream_gold_status={gold['status']}")


if __name__ == "__main__":
    main()
