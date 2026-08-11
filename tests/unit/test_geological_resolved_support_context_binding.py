"""Stage 5A context-bound geological support resolution tests."""

from __future__ import annotations

from tbm_twin.claims.models import (
    ClaimModality,
    ClaimProposal,
    ClaimScope,
    ClaimScopeKind,
    ClaimSemanticInterpretation,
    ClaimSupportRef,
    ClaimSupportRole,
    ClaimType,
    GeologicalConditionClaimValue,
    SupportKind,
    stable_id,
)
from tbm_twin.claims.resolution import (
    AuthoritativeSupportResolver,
    ClaimUpstreamLookup,
    GeologicalEvidenceRecord,
    SubjectRecord,
)


def test_same_evidence_multiple_subjects_selects_matching_claim_context() -> None:
    proposal = _proposal("bt_2", "sv_2", "daily_2", "cell_2", "2023-09-16")
    resolver = AuthoritativeSupportResolver(_lookup(_subjects()))

    resolved = resolver.resolve_many(proposal.support_refs, proposal)[0]

    assert resolved.resolution_status == "RESOLVED"
    assert resolved.resolved_bitemporal_version_id == "bt_2"
    assert resolved.resolved_base_stage3a_state_version_id == "sv_2"
    assert resolved.resolved_daily_state_id == "daily_2"
    assert resolved.resolved_cell_id == "cell_2"
    assert str(resolved.resolved_valid_date) == "2023-09-16"
    assert resolved.resolved_state_role == "DAILY_REVIEW_CELL"


def _lookup(subjects: list[SubjectRecord]) -> ClaimUpstreamLookup:
    return ClaimUpstreamLookup(
        geological_evidence={
            "geo_1": GeologicalEvidenceRecord(
                "geo_1",
                "OBSERVED",
                ClaimScope(
                    scope_kind=ClaimScopeKind.LOCATED_INTERVAL,
                    start_chainage=100.0,
                    end_chainage=110.0,
                    scope_basis="test",
                ),
                {"lithology": "slate"},
            )
        },
        geological_subjects={"geo_1": subjects},
    )


def _subjects() -> list[SubjectRecord]:
    return [
        SubjectRecord(
            "GEOLOGICAL_EVIDENCE_BACKED",
            "geo_1",
            "bt_1",
            "sv_1",
            "daily_1",
            "cell_1",
            "2023-09-15",
            "DAILY_REVIEW_CELL",
        ),
        SubjectRecord(
            "GEOLOGICAL_EVIDENCE_BACKED",
            "geo_1",
            "bt_2",
            "sv_2",
            "daily_2",
            "cell_2",
            "2023-09-16",
            "DAILY_REVIEW_CELL",
        ),
    ]


def _proposal(
    bitemporal_version_id: str,
    state_version_id: str,
    daily_state_id: str,
    cell_id: str,
    valid_date: str,
) -> ClaimProposal:
    value = GeologicalConditionClaimValue(
        source_evidence_id="geo_1",
        attribute_name="lithology",
        normalized_value="slate",
    )
    support_refs = [
        ClaimSupportRef(
            support_kind=SupportKind.GEOLOGICAL_EVIDENCE,
            support_id="geo_1",
            support_role=ClaimSupportRole.PRIMARY_SUPPORT,
        )
    ]
    return ClaimProposal(
        proposal_id=stable_id("proposal", {"case": bitemporal_version_id}),
        claim_type=ClaimType.OBSERVED_GEOLOGICAL_CONDITION,
        bitemporal_version_id=bitemporal_version_id,
        base_stage3a_state_version_id=state_version_id,
        state_version_id=state_version_id,
        daily_state_id=daily_state_id,
        cell_id=cell_id,
        state_role="DAILY_REVIEW_CELL",
        valid_date=valid_date,
        scope=ClaimScope(
            scope_kind=ClaimScopeKind.LOCATED_INTERVAL,
            start_chainage=100.0,
            end_chainage=110.0,
            scope_basis="test",
        ),
        modality=ClaimModality.GEOLOGICAL_OBSERVED,
        semantic_interpretation=ClaimSemanticInterpretation.OBSERVED_GEOLOGICAL_CONDITION,
        claim_value=value,
        support_refs=support_refs,
    )
