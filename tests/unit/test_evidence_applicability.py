from __future__ import annotations

from datetime import UTC, datetime

from tbm_twin.evidence.applicability import assign_evidence_to_episode
from tbm_twin.evidence.models import (
    ApplicabilityResult,
    EvidenceType,
    GeologicalEpistemicStatus,
    GeologicalEvidence,
    GeologicalSourceType,
    SpatialApplicabilityStatus,
    TemporalValue,
    TemporalValueConfidence,
)
from tbm_twin.geology.chainage import parse_chainage_interval
from tbm_twin.process.episode_builder import build_excavation_episodes
from tbm_twin.process.weak_labels import label_operation_phases
from tbm_twin.trajectory.footprint_builder import build_spatial_footprints
from tests.conftest import base_rows, normalize_rows


def _target(catalog, tmp_path):
    labeled = label_operation_phases(normalize_rows(tmp_path, base_rows(), catalog))
    episodes = build_excavation_episodes(labeled)
    footprints = build_spatial_footprints(labeled, episodes)
    return episodes[0], footprints[0]


def _geology(
    *,
    available_time: datetime | None,
    text: str = "TSP forecast DK0+090-DK0+120",
    evidence_type: EvidenceType = EvidenceType.GEOLOGICAL_FORECAST,
    source_type: GeologicalSourceType = GeologicalSourceType.TSP_REPORT,
    epistemic_status: GeologicalEpistemicStatus = GeologicalEpistemicStatus.FORECAST,
) -> GeologicalEvidence:
    interval = parse_chainage_interval({}, text)
    return GeologicalEvidence(
        evidence_id="geology-1",
        evidence_type=evidence_type,
        source_asset_ids=["asset-g"],
        valid_time=None,
        available_time=available_time,
        ingested_time=datetime(2026, 1, 1, tzinfo=UTC),
        spatial_scope=None,
        quality_grade="A",
        quality_flags=[],
        method_version="test",
        provenance_refs=["record:1"],
        geological_source_type=source_type,
        epistemic_status=epistemic_status,
        title="TSP",
        raw_text=text,
        normalized_text=text,
        observed_time=None,
        issued_time=None,
        available_time_value=TemporalValue(
            value=available_time,
            confidence=TemporalValueConfidence.DERIVED
            if available_time
            else TemporalValueConfidence.UNKNOWN,
            basis="fixture",
        ),
        chainage_interval=interval,
        structured_attributes={},
        source_record_id="1",
        parse_warnings=[],
    )


def test_future_geological_evidence_is_not_applicable(catalog, tmp_path) -> None:
    episode, footprint = _target(catalog, tmp_path)
    evidence = _geology(available_time=datetime(2026, 1, 2, tzinfo=UTC))

    assignment = assign_evidence_to_episode(
        evidence,
        episode,
        footprint,
        evaluation_time=episode.excavation_end,
    )

    assert assignment.result == ApplicabilityResult.NOT_APPLICABLE
    assert "EVIDENCE_NOT_YET_AVAILABLE" in assignment.reason_codes
    assert assignment.dominant_reason_code == "EVIDENCE_NOT_YET_AVAILABLE"


def test_unknown_available_time_is_undetermined_not_backfilled(catalog, tmp_path) -> None:
    episode, footprint = _target(catalog, tmp_path)
    evidence = _geology(available_time=None)

    assignment = assign_evidence_to_episode(
        evidence,
        episode,
        footprint,
        evaluation_time=episode.excavation_end,
    )

    assert assignment.result == ApplicabilityResult.UNDETERMINED
    assert "AVAILABLE_TIME_UNKNOWN" in assignment.reason_codes
    assert assignment.dominant_reason_code == "AVAILABLE_TIME_UNKNOWN"


def test_forecast_overlap_is_qualified_not_observed_fact(catalog, tmp_path) -> None:
    episode, footprint = _target(catalog, tmp_path)
    evidence = _geology(available_time=datetime(2025, 12, 31, tzinfo=UTC))

    assignment = assign_evidence_to_episode(
        evidence,
        episode,
        footprint,
        evaluation_time=episode.excavation_end,
    )

    assert assignment.spatial_status in {
        SpatialApplicabilityStatus.OVERLAP,
        SpatialApplicabilityStatus.ADJACENT,
    }
    assert assignment.result == ApplicabilityResult.APPLICABLE_WITH_QUALIFICATION
    assert "FORECAST_NOT_OBSERVATION" in assignment.reason_codes


def test_disjoint_with_unknown_available_time_is_hard_excluded(catalog, tmp_path) -> None:
    episode, footprint = _target(catalog, tmp_path)
    evidence = _geology(available_time=None, text="TSP forecast DK0+300 DK0+320")

    assignment = assign_evidence_to_episode(
        evidence,
        episode,
        footprint,
        evaluation_time=episode.excavation_end,
    )

    assert assignment.result == ApplicabilityResult.NOT_APPLICABLE
    assert assignment.dominant_reason_code == "SPATIAL_DISJOINT"


def test_forecast_behind_target_cannot_support_front_context(catalog, tmp_path) -> None:
    episode, footprint = _target(catalog, tmp_path)
    evidence = _geology(
        available_time=datetime(2025, 12, 31, tzinfo=UTC),
        text="TSP forecast DK0+050 DK0+060",
    )

    assignment = assign_evidence_to_episode(
        evidence,
        episode,
        footprint,
        evaluation_time=episode.excavation_end,
    )

    assert assignment.result == ApplicabilityResult.NOT_APPLICABLE
    assert assignment.dominant_reason_code == "FORECAST_BEHIND_TARGET"


def test_observed_ahead_target_cannot_be_target_observation(catalog, tmp_path) -> None:
    episode, footprint = _target(catalog, tmp_path)
    evidence = _geology(
        available_time=datetime(2025, 12, 31, tzinfo=UTC),
        text="field observation DK0+120 DK0+125",
        evidence_type=EvidenceType.GEOLOGICAL_OBSERVATION,
        source_type=GeologicalSourceType.FIELD_OBSERVATION,
        epistemic_status=GeologicalEpistemicStatus.OBSERVED,
    )

    assignment = assign_evidence_to_episode(
        evidence,
        episode,
        footprint,
        evaluation_time=episode.excavation_end,
    )

    assert assignment.result == ApplicabilityResult.NOT_APPLICABLE
    assert assignment.dominant_reason_code == "OBSERVED_AHEAD_OF_TARGET"


def test_background_is_only_qualified_context(catalog, tmp_path) -> None:
    episode, footprint = _target(catalog, tmp_path)
    evidence = _geology(
        available_time=datetime(2025, 12, 31, tzinfo=UTC),
        text="design background DK0+090 DK0+120",
        evidence_type=EvidenceType.GEOLOGICAL_BACKGROUND,
        source_type=GeologicalSourceType.DESIGN_BACKGROUND,
        epistemic_status=GeologicalEpistemicStatus.BACKGROUND,
    )

    assignment = assign_evidence_to_episode(
        evidence,
        episode,
        footprint,
        evaluation_time=episode.excavation_end,
    )

    assert assignment.result == ApplicabilityResult.APPLICABLE_WITH_QUALIFICATION
    assert assignment.dominant_reason_code == "BACKGROUND_CONTEXT_ONLY"


def test_unknown_epistemic_status_is_not_strongly_applicable(catalog, tmp_path) -> None:
    episode, footprint = _target(catalog, tmp_path)
    evidence = _geology(
        available_time=datetime(2025, 12, 31, tzinfo=UTC),
        text="unclear geology DK0+090 DK0+120",
        evidence_type=EvidenceType.GEOLOGICAL_UNKNOWN,
        source_type=GeologicalSourceType.OTHER,
        epistemic_status=GeologicalEpistemicStatus.UNKNOWN,
    )

    assignment = assign_evidence_to_episode(
        evidence,
        episode,
        footprint,
        evaluation_time=episode.excavation_end,
    )

    assert assignment.result == ApplicabilityResult.UNDETERMINED
    assert assignment.dominant_reason_code == "EPISTEMIC_STATUS_UNKNOWN"
