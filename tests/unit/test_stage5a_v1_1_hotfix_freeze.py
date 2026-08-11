"""Stage 5A v1.1 hotfix freeze artifact tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.build_stage5a_v1_1_hotfix import build_stage5a_v1_1_hotfix


def test_stage5a_v1_1_freeze_records_expected_context_delta(tmp_path: Path) -> None:
    output = tmp_path / "stage5a_v1_1"
    build_stage5a_v1_1_hotfix(Path.cwd(), output, "2026-08-11T14:30:00+08:00")

    method = json.loads((output / "method_version.json").read_text())
    hard_rows = list(csv.DictReader((output / "stage5a_v1_1_hard_check.csv").open()))
    delta_rows = list(
        csv.DictReader((output / "stage5a_v1_1_authorization_delta_audit.csv").open())
    )
    semantic_rows = list(
        csv.DictReader((output / "stage5a_v1_v1_1_semantic_delta_audit.csv").open())
    )

    assert method["method"] == "stage5a_typed_claim_contract_v1_1_frozen"
    assert method["schema"] == "stage5a_typed_claim_contract.v1"
    assert method["authorization_semantics_changed"] is True
    assert method["authorization_delta_scope"] == "GEOLOGICAL_SUBJECT_CONTEXT_UNIQUENESS"
    assert {row["status"] for row in hard_rows} == {"PASS"}
    assert delta_rows[0]["v1_decision"] == "EXPRESSIBLE"
    assert delta_rows[0]["v1_1_decision"] == "ABSTAIN"
    assert delta_rows[0]["delta_class"] == "EXPECTED_CONTEXT_UNIQUENESS_HOTFIX"
    assert {
        row["check_name"]: row["actual"]
        for row in semantic_rows
        if row["delta_class"] == "UNCHANGED"
    } == {
        "claim_type_diff_from_v1": "0",
        "contract_config_diff_from_v1": "0",
        "metric_semantics_diff_from_v1": "0",
        "epistemic_semantics_diff_from_v1": "0",
        "spatial_semantics_diff_from_v1": "0",
        "unknown_semantics_diff_from_v1": "0",
    }
