from __future__ import annotations

from datetime import date

from tbm_twin.bitemporal.temporal_eligibility import evaluate_temporal_eligibility


def test_later_available_evidence_is_temporally_eligible() -> None:
    eligible, reasons = evaluate_temporal_eligibility(
        valid_date=date(2023, 9, 22),
        observed_local_date=date(2023, 9, 22),
        available_local_date=date(2023, 9, 23),
        knowledge_cutoff_date=date(2024, 11, 17),
    )
    assert eligible is True
    assert reasons == ["LATE_AVAILABLE_PRIMARY_EVIDENCE"]


def test_later_observed_evidence_is_rejected() -> None:
    eligible, reasons = evaluate_temporal_eligibility(
        valid_date=date(2023, 11, 5),
        observed_local_date=date(2023, 11, 6),
        available_local_date=date(2023, 11, 6),
        knowledge_cutoff_date=date(2024, 11, 17),
    )
    assert eligible is False
    assert reasons == ["OBSERVED_AFTER_STATE_VALID_DATE"]


def test_same_day_available_evidence_is_initial_state_knowledge() -> None:
    eligible, reasons = evaluate_temporal_eligibility(
        valid_date=date(2023, 9, 22),
        observed_local_date=date(2023, 9, 22),
        available_local_date=date(2023, 9, 22),
        knowledge_cutoff_date=date(2024, 11, 17),
    )
    assert eligible is False
    assert reasons == ["ALREADY_AVAILABLE_IN_INITIAL_STATE"]
