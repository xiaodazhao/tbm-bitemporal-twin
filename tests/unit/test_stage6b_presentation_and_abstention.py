"""Stage6B presentation scope and task abstention tests."""

from __future__ import annotations

from tbm_twin.realization.models import SliceSpec
from tbm_twin.realization.stage6b import (
    PresentationScopeResolver,
    build_task_abstention_view,
    load_stage6b_inputs,
)
from tests.unit.stage6b_helpers import REPO_ROOT, read_csv, stage6b_artifact


def test_stage6b_cell_metric_resolves_stage3a_geometry(tmp_path_factory) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "presentation_scope_audit.csv")
    cell_rows = [row for row in rows if row["source_scope_kind"] == "CELL"]

    assert cell_rows
    assert all(row["scope_source"] == "FROZEN_STAGE3A_CONSTRUCTION_STATE_CELL" for row in cell_rows)
    assert all(row["display_start_chainage"] for row in cell_rows)
    assert all(row["display_end_chainage"] for row in cell_rows)


def test_stage6b_located_interval_and_point_are_not_overwritten(tmp_path_factory) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "presentation_scope_audit.csv")

    assert any(
        row["source_scope_kind"] == "LOCATED_INTERVAL"
        and row["scope_source"] == "FACT_LOCK_SPATIAL_SCOPE"
        for row in rows
    )
    assert any(
        row["source_scope_kind"] == "LOCATED_POINT"
        and row["display_point_chainage"]
        and row["scope_source"] == "FACT_LOCK_SPATIAL_SCOPE"
        for row in rows
    )


def test_stage6b_missing_cell_fails_closed() -> None:
    inputs = load_stage6b_inputs(REPO_ROOT)
    lock = next(
        item for item in inputs["stage6a_locks"] if item.spatial_scope["scope_kind"] == "CELL"
    )
    resolver = PresentationScopeResolver([])

    try:
        resolver.resolve(lock)
    except KeyError:
        return
    raise AssertionError("missing cell should fail closed")


def test_stage6b_task_abstention_view_is_task_scoped() -> None:
    inputs = load_stage6b_inputs(REPO_ROOT)
    target_date = inputs["stage5b_abstentions"][0]["valid_date"]
    view = build_task_abstention_view(
        inputs["stage5b_abstentions"],
        SliceSpec(product_type="daily_review", valid_date=target_date),
    )

    assert view.abstention_count < len(inputs["stage5b_abstentions"])
    assert all(row["valid_date"] == target_date for row in view.records)
    assert all(row["state_role"] == "DAILY_REVIEW_CELL" for row in view.records)
    assert all("claim_value" not in row and "candidate_value" not in row for row in view.records)


def test_stage6b_abstention_audit_does_not_expose_candidate_values(tmp_path_factory) -> None:
    artifact = stage6b_artifact(tmp_path_factory)
    rows = read_csv(artifact / "task_abstention_view_audit.csv")

    assert rows
    assert all(row["unsupported_candidate_value_exposed"] == "0" for row in rows)
    assert all(row["status"] == "PASS" for row in rows)
