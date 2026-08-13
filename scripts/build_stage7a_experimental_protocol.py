"""Build Stage7A experimental protocol and held-out benchmark artifact."""

from __future__ import annotations

from pathlib import Path

from tbm_twin.evaluation.stage7a import build_stage7a_protocol


def main() -> None:
    """CLI entrypoint."""

    repo_root = Path(__file__).resolve().parents[1]
    build_stage7a_protocol(repo_root)


if __name__ == "__main__":
    main()
