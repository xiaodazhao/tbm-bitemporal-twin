"""Tests that Stage 5A contract fields have runtime enforcement registry coverage."""

from __future__ import annotations

from scripts.build_stage5a_claim_contract import _field_enforcement_rows


def test_contract_field_enforcement_audit_is_not_documentation_only() -> None:
    rows = _field_enforcement_rows()

    assert rows
    assert {row["status"] for row in rows} == {"PASS"}
    assert all(row["declared_in_schema"] == "true" for row in rows)
    assert all(row["enforced_by_evaluator"] == "true" for row in rows)
    assert all(row["direct_field_access"] == "true" for row in rows)
    assert all(row["decision_changes_when_mutated"] == "true" for row in rows)
    assert all(row["runtime_handler"] for row in rows)
    assert all(row["metamorphic_case_id"] for row in rows)
    assert all(row["test_case_ids"] for row in rows)
    assert "metric_availability_required" not in {row["field_name"] for row in rows}
