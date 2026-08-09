from __future__ import annotations

from tbm_twin.bitemporal.spatial_revision import (
    evaluate_revision_role,
    evaluate_spatial_overlap,
)

CELL = {"spatial_start": 1013270.0, "spatial_end": 1013280.0}


def test_point_maps_to_only_right_closed_previous_cell() -> None:
    eligible, overlap, reasons = evaluate_spatial_overlap(
        cell=CELL,
        evidence_scope={
            "kind": "POINT",
            "start_chainage": 1013280.0,
            "end_chainage": 1013280.0,
        },
    )
    assert eligible is True
    assert overlap["cell_overlap_kind"] == "POINT"
    assert overlap["cell_overlap_length_m"] == 0.0
    assert "POINT_MAPPED_TO_RIGHT_CLOSED_PREVIOUS_CELL" in reasons


def test_interval_requires_positive_overlap() -> None:
    eligible, overlap, _ = evaluate_spatial_overlap(
        cell=CELL,
        evidence_scope={
            "kind": "INTERVAL",
            "start_chainage": 1013275.0,
            "end_chainage": 1013290.0,
        },
    )
    assert eligible is True
    assert overlap["cell_overlap_start"] == 1013275.0
    assert overlap["cell_overlap_end"] == 1013280.0
    assert overlap["cell_overlap_length_m"] == 5.0


def test_observed_evidence_cannot_enter_forward_attention() -> None:
    eligible, role, reasons = evaluate_revision_role(
        cell_scope_role="FORWARD_ATTENTION_CELL",
        epistemic_status="OBSERVED",
    )
    assert eligible is False
    assert role == "UNKNOWN"
    assert reasons == ["OBSERVED_NOT_ALLOWED_FOR_FORWARD_ATTENTION"]


def test_forecast_preserves_forecast_role_in_forward_attention() -> None:
    eligible, role, _ = evaluate_revision_role(
        cell_scope_role="FORWARD_ATTENTION_CELL",
        epistemic_status="FORECAST",
    )
    assert eligible is True
    assert role == "FORWARD_ATTENTION"


def test_background_is_not_allowed_for_daily_review() -> None:
    eligible, role, reasons = evaluate_revision_role(
        cell_scope_role="DAILY_REVIEW_CELL",
        epistemic_status="BACKGROUND",
    )
    assert eligible is False
    assert role == "UNKNOWN"
    assert reasons == ["BACKGROUND_NOT_ALLOWED_FOR_DAILY_REVIEW"]


def test_unknown_epistemic_status_is_not_revision_eligible() -> None:
    eligible, role, reasons = evaluate_revision_role(
        cell_scope_role="LOCAL_BACKGROUND_CELL",
        epistemic_status="UNKNOWN",
    )
    assert eligible is False
    assert role == "UNKNOWN"
    assert reasons == ["UNKNOWN_EPISTEMIC_STATUS_NOT_REVISION_ELIGIBLE"]
