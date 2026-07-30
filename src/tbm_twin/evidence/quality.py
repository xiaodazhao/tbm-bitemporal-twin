"""Evidence quality helpers."""

from __future__ import annotations

from tbm_twin.evidence.models import EvidenceQualityGrade


def grade_from_reason_codes(reason_codes: list[str]) -> EvidenceQualityGrade:
    """Convert local evidence reason codes into an explainable quality grade."""

    serious = {
        "HIGH_MISSING_RATE",
        "LOW_SAMPLE_COUNT",
        "FOOTPRINT_INCONSISTENT",
        "RAW_TEXT_EMPTY",
        "SPATIAL_SCOPE_UNKNOWN",
        "INVALID_SPATIAL_SCOPE",
        "IMPLAUSIBLE_INTERVAL_LENGTH",
        "CHAINAGE_SCALE_MISMATCH",
        "CHAINAGE_PREFIX_MISMATCH",
        "CHAINAGE_PARSE_CONFLICT",
    }
    moderate = {
        "EPISODE_BOUNDARY_CENSORED",
        "ZERO_ADVANCE_TARGET",
        "AVAILABLE_TIME_UNKNOWN",
        "EPISTEMIC_STATUS_UNKNOWN",
        "TEMPORAL_VALUE_UNKNOWN",
        "EPISTEMIC_SOURCE_CONFLICT",
        "CHAINAGE_DIRECTION_CONFLICT",
    }
    if set(reason_codes) & serious:
        return EvidenceQualityGrade.C
    if set(reason_codes) & moderate:
        return EvidenceQualityGrade.B
    return EvidenceQualityGrade.A
