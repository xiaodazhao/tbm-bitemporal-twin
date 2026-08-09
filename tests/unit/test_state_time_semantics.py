from datetime import datetime
from zoneinfo import ZoneInfo

from tbm_twin.state.models import InitialConstructionStateVersion


def test_initial_state_version_does_not_fabricate_transaction_time() -> None:
    version = InitialConstructionStateVersion(
        state_version_id="state_version_x",
        daily_state_id="daily_state_x",
        cell_id="cell_x",
        target_date="2023-09-15",
        valid_date="2023-09-15",
        valid_time_precision="DAY",
        knowledge_as_of_local_date="2023-09-15",
        knowledge_precision="DAY",
        historical_transaction_time=None,
        historical_transaction_time_known=False,
        transaction_time_basis="HISTORICAL_DATABASE_TRANSACTION_TIME_UNAVAILABLE",
        reconstructed_at=datetime(2026, 7, 30, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        version_number=1,
        supersedes_version_id=None,
        is_current_version=True,
        cell_scope_role="DAILY_REVIEW_CELL",
        episode_ids=[],
        response_evidence_ids=[],
        daily_review_evidence_ids=[],
        forward_attention_evidence_ids=[],
        local_background_evidence_ids=[],
        observed_geological_evidence_ids=[],
        forecast_geological_evidence_ids=[],
        background_geological_evidence_ids=[],
        source_assignment_ids=[],
        geological_link_ids=[],
        response_link_ids=[],
        state_quality_flags=[],
        state_reason_codes=[],
        source_geology_manifest_hash="geology_hash",
        source_applicability_manifest_hash="app_hash",
        source_operational_manifest_hash="op_hash",
        state_method_version="stage3a_initial_epistemic_state_v1_1_point_response_complete",
    )

    assert version.historical_transaction_time is None
    assert version.historical_transaction_time_known is False
