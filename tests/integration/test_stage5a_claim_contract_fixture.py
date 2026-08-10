"""Integration test for the Stage 5A candidate artifact builder."""

from __future__ import annotations

import csv
from pathlib import Path

from scripts.build_stage5a_claim_contract import build_stage5a_candidate


def test_stage5a_candidate_builder_uses_real_stage4_fixtures(tmp_path: Path) -> None:
    output = tmp_path / "stage5a"

    build_stage5a_candidate(Path.cwd(), output, "2026-08-09T20:55:00+08:00")

    hard_rows = list(csv.DictReader((output / "stage5a_hard_check.csv").open()))
    fixed_rows = list(csv.DictReader((output / "fixed_case_audit.csv").open()))
    adversarial_rows = list(csv.DictReader((output / "adversarial_contract_audit.csv").open()))
    field_rows = list(
        csv.DictReader((output / "claim_contract_field_enforcement_audit.csv").open())
    )
    real_rows = list(csv.DictReader((output / "real_fixture_contract_audit.csv").open()))

    assert {row["status"] for row in hard_rows} == {"PASS"}
    assert {row["status"] for row in fixed_rows} == {"PASS"}
    assert {row["status"] for row in adversarial_rows} == {"PASS"}
    assert {row["status"] for row in field_rows} == {"PASS"}
    assert len(real_rows) >= 4
    assert any(
        row["state_version_id"] == "state_version_90132939564734086ffba720" for row in real_rows
    )
    forward = next(row for row in real_rows if row["fixture_id"] == "REAL_FORWARD_GRS_AVAILABLE")
    assert forward["required_epistemic_statuses"] == "FORECAST"
    assert forward["resolved_epistemic_statuses"] == "FORECAST"
    assert forward["epistemic_evidence_ids"]
    hard_by_name = {row["check_name"]: row for row in hard_rows}
    assert hard_by_name["contract_fields_declared_but_not_enforced"]["details"] == "0"
    assert hard_by_name["hardcoded_pass_check_count"]["details"] == "0"
    assert (output / "file_hashes.sha256").exists()
