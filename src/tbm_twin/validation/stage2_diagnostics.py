"""Diagnostics for Stage 2 evidence validation."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tbm_twin.evidence.models import (
    ApplicabilityResult,
    EvidenceApplicabilityAssignment,
    GeologicalEvidence,
    ResponseEvidence,
)


def stage2_diagnostics(
    *,
    responses: list[ResponseEvidence],
    geology: list[GeologicalEvidence],
    assignments: list[EvidenceApplicabilityAssignment],
) -> dict[str, Any]:
    """Build Stage 2 validation diagnostics."""

    geological_evidence_level = evidence_level_applicability_summary(
        assignments=assignments,
        evidence_ids=[record.evidence_id for record in geology],
        evidence_family="GEOLOGICAL",
    )
    response_evidence_level = evidence_level_applicability_summary(
        assignments=assignments,
        evidence_ids=[record.evidence_id for record in responses],
        evidence_family="RESPONSE",
    )
    historically_evaluable = sum(record.available_time is not None for record in geology)
    return {
        "response_evidence_count": len(responses),
        "response_quality_distribution": _counts(
            record.quality_grade.value for record in responses
        ),
        "geological_evidence_count": len(geology),
        "geological_quality_distribution": _counts(
            record.quality_grade.value for record in geology
        ),
        "available_time_unknown_count": sum(record.available_time is None for record in geology),
        "spatial_scope_unknown_count": sum(record.chainage_interval is None for record in geology),
        "epistemic_status_unknown_count": sum(
            record.epistemic_status.value == "UNKNOWN" for record in geology
        ),
        "epistemic_status_distribution": _counts(
            record.epistemic_status.value for record in geology
        ),
        "applicability_result_distribution": _counts(record.result.value for record in assignments),
        "temporal_status_distribution": _counts(
            record.temporal_status.value for record in assignments
        ),
        "spatial_status_distribution": _counts(
            record.spatial_status.value for record in assignments
        ),
        "detected_future_leakage_count": sum(
            record.result != ApplicabilityResult.NOT_APPLICABLE
            and "EVIDENCE_NOT_YET_AVAILABLE" in record.reason_codes
            for record in assignments
        ),
        "future_evidence_leakage_count": sum(
            record.result != ApplicabilityResult.NOT_APPLICABLE
            and "EVIDENCE_NOT_YET_AVAILABLE" in record.reason_codes
            for record in assignments
        ),
        "hard_exclusion_distribution": _counts(
            record.dominant_reason_code
            for record in assignments
            if record.result == ApplicabilityResult.NOT_APPLICABLE
        ),
        "excluded_by_future_time": _dominant_count(assignments, "EVIDENCE_NOT_YET_AVAILABLE"),
        "excluded_by_spatial_disjoint": _dominant_count(assignments, "SPATIAL_DISJOINT"),
        "excluded_by_epistemic_conflict": _dominant_count(
            assignments, "EPISTEMICALLY_INCOMPATIBLE"
        ),
        "excluded_by_invalid_spatial_scope": _dominant_count(assignments, "INVALID_SPATIAL_SCOPE"),
        "geological_evidence_level_summary": _evidence_level_counts(geological_evidence_level),
        "response_evidence_level_summary": _evidence_level_counts(response_evidence_level),
        "historically_evaluable_geological_evidence_count": historically_evaluable,
        "real_data_temporal_applicability_validation": "NOT_EVALUABLE"
        if historically_evaluable == 0
        else "EVALUABLE",
    }


def evidence_level_applicability_summary(
    *,
    assignments: list[EvidenceApplicabilityAssignment],
    evidence_ids: list[str],
    evidence_family: str,
) -> list[dict[str, Any]]:
    """Summarize applicability across all targets for each evidence record."""

    by_evidence: dict[str, list[EvidenceApplicabilityAssignment]] = {}
    for record in assignments:
        by_evidence.setdefault(record.evidence_id, []).append(record)
    rows: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        items = by_evidence.get(evidence_id, [])
        result_values = {item.result for item in items}
        rows.append(
            {
                "evidence_id": evidence_id,
                "evidence_family": evidence_family,
                "assignment_count": len(items),
                "applicable_to_at_least_one_episode": any(
                    item.result == ApplicabilityResult.APPLICABLE for item in items
                ),
                "qualified_for_at_least_one_episode": any(
                    item.result == ApplicabilityResult.APPLICABLE_WITH_QUALIFICATION
                    for item in items
                ),
                "undetermined_for_all_episodes": bool(items)
                and result_values == {ApplicabilityResult.UNDETERMINED},
                "not_applicable_to_all_episodes": bool(items)
                and result_values == {ApplicabilityResult.NOT_APPLICABLE},
                "mixed_applicability_results": len(result_values) > 1,
            }
        )
    return rows


def _evidence_level_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    fields = [
        "applicable_to_at_least_one_episode",
        "qualified_for_at_least_one_episode",
        "undetermined_for_all_episodes",
        "not_applicable_to_all_episodes",
        "mixed_applicability_results",
    ]
    return {field: sum(bool(row[field]) for row in rows) for field in fields}


def _dominant_count(records: list[EvidenceApplicabilityAssignment], reason: str) -> int:
    return sum(record.dominant_reason_code == reason for record in records)


def _counts(values: Iterable[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts
