"""Freeze the Stage7 supplemental 200-task automatic benchmark protocol."""

from pathlib import Path

from tbm_twin.evaluation.stage7_supplemental import build_supplemental_protocol


def main() -> None:
    output = build_supplemental_protocol(Path.cwd())
    print(output)


if __name__ == "__main__":
    main()
