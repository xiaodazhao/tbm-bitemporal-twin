"""Tests for executable Stage 5A hard-check evidence sources."""

from __future__ import annotations

import csv
from pathlib import Path

from scripts.build_stage5a_claim_contract import build_stage5a_candidate


def test_stage5a_hard_check_rows_have_evidence_sources(tmp_path: Path) -> None:
    output = tmp_path / "stage5a"
    build_stage5a_candidate(Path.cwd(), output, "2026-08-09T20:55:00+08:00")

    rows = list(csv.DictReader((output / "stage5a_hard_check.csv").open()))
    by_name = {row["check_name"]: row for row in rows}

    assert {row["status"] for row in rows} == {"PASS"}
    assert all(row["evidence_source"] for row in rows)
    assert all(row["evidence_case_id"] for row in rows)
    assert by_name["hardcoded_pass_check_count"]["details"] == "0"
    assert by_name["issue_count"]["details"] == "0"
