from tbm_twin.state.models import StateGeologicalEvidenceLink


def test_forecast_can_enter_daily_review_without_becoming_observed() -> None:
    link = StateGeologicalEvidenceLink(
        link_id="state_geology_link_x",
        state_version_id="state_version_x",
        daily_state_id="daily_state_x",
        cell_id="cell_x",
        target_date="2023-10-01",
        assignment_id="assignment_x",
        evidence_id="evidence_x",
        document_id="document_x",
        asset_id="asset_x",
        source_type="TSP_REPORT",
        evidence_type="FORECAST_SEGMENT",
        epistemic_status="FORECAST",
        applicability_role="DAILY_REVIEW",
        overlap_kind="INTERVAL",
        overlap_start=1013200.0,
        overlap_end=1013210.0,
        overlap_length_m=10.0,
        source_span_ids=["span_x"],
        assignment_reason_codes=["EXCAVATED_REVIEW"],
        link_reason_codes=["APPLICABILITY_OVERLAP_SCOPE_SPLIT_TO_MATCHING_CELL_ROLE"],
        source_geology_manifest_hash="geology_hash",
        source_applicability_manifest_hash="app_hash",
        link_method_version="stage3a_initial_epistemic_state_v1_1_point_response_complete",
    )

    assert link.applicability_role == "DAILY_REVIEW"
    assert link.epistemic_status == "FORECAST"
