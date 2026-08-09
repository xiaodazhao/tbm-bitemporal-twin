from __future__ import annotations

from datetime import date

from tbm_twin.bitemporal.temporal_eligibility import evaluate_temporal_eligibility


def test_document_local_date_cannot_replace_later_observed_date() -> None:
    eligible, reasons = evaluate_temporal_eligibility(
        valid_date=date(2023, 11, 5),
        observed_local_date=date(2023, 11, 6),
        available_local_date=date(2023, 11, 6),
        knowledge_cutoff_date=date(2024, 11, 17),
    )
    assert eligible is False
    assert "OBSERVED_AFTER_STATE_VALID_DATE" in reasons
