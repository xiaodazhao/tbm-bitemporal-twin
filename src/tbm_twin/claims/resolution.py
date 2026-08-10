"""Structured support resolution for Stage 5A claim contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import isclose

from tbm_twin.claims.models import (
    ClaimProposal,
    ClaimScope,
    ClaimScopeKind,
    ClaimSupportRef,
    ClaimSupportRole,
    GeologicalConditionClaimValue,
    MetricClaimValue,
    ResolvedClaimSupportRef,
    SupportKind,
)

AVAILABLE = "AVAILABLE"
FLOAT_TOLERANCE = 1e-12


@dataclass(frozen=True)
class MetricRecord:
    """Formal Stage 4 metric record used for payload binding."""

    metric_id: str
    metric_name: str
    metric_value: float | None
    metric_status: str
    metric_semantics: str
    is_probability: bool
    is_hazard_probability: bool
    is_causal_estimate: bool
    cell_id: str | None
    bitemporal_version_id: str | None = None
    base_stage3a_state_version_id: str | None = None
    daily_state_id: str | None = None
    valid_date: str | None = None
    state_role: str | None = None


@dataclass(frozen=True)
class GeologicalEvidenceRecord:
    """Structured geological evidence facts needed by Stage 5A."""

    evidence_id: str
    epistemic_status: str | None
    spatial_scope: ClaimScope | None = None
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SubjectRecord:
    """Authoritative state/cell/date context for an upstream support object."""

    subject_source_type: str
    support_id: str
    bitemporal_version_id: str | None = None
    base_stage3a_state_version_id: str | None = None
    daily_state_id: str | None = None
    cell_id: str | None = None
    valid_date: str | None = None
    state_role: str | None = None


@dataclass(frozen=True)
class ClaimUpstreamLookup:
    """Read-only structured lookup for frozen upstream objects."""

    metrics: dict[str, MetricRecord] = field(default_factory=dict)
    geological_evidence: dict[str, GeologicalEvidenceRecord] = field(default_factory=dict)
    grs_contributing_evidence_ids: dict[str, list[str]] = field(default_factory=dict)
    geological_subjects: dict[str, list[SubjectRecord]] = field(default_factory=dict)
    cell_scopes: dict[str, ClaimScope] = field(default_factory=dict)


def scopes_equal(left: ClaimScope | None, right: ClaimScope | None) -> bool:
    """Return whether two scopes carry the same authority-relevant geometry."""

    if left is None or right is None:
        return left is right
    if left.scope_kind != right.scope_kind:
        return False
    if left.scope_kind == ClaimScopeKind.CELL:
        return left.cell_id == right.cell_id
    if left.scope_kind == ClaimScopeKind.LOCATED_POINT:
        return (
            left.point_chainage is not None
            and right.point_chainage is not None
            and isclose(
                left.point_chainage,
                right.point_chainage,
                rel_tol=0.0,
                abs_tol=FLOAT_TOLERANCE,
            )
        )
    if left.scope_kind == ClaimScopeKind.LOCATED_INTERVAL:
        return (
            left.start_chainage is not None
            and left.end_chainage is not None
            and right.start_chainage is not None
            and right.end_chainage is not None
            and isclose(
                left.start_chainage,
                right.start_chainage,
                rel_tol=0.0,
                abs_tol=FLOAT_TOLERANCE,
            )
            and isclose(
                left.end_chainage,
                right.end_chainage,
                rel_tol=0.0,
                abs_tol=FLOAT_TOLERANCE,
            )
        )
    return True


@dataclass(frozen=True)
class ResolvedEpistemicProof:
    """Resolved proof for required OBSERVED/FORECAST status."""

    resolved_statuses: set[str]
    proof_refs: list[str]
    proof_source_kinds: list[str]
    proof_evidence_ids: list[str]
    unresolved_support_ids: list[str]
    status: str


class EpistemicProofResolver:
    """Resolve epistemic status only from traceable structured support."""

    def __init__(self, lookup: ClaimUpstreamLookup) -> None:
        self._lookup = lookup

    def resolve(self, support_refs: list[ClaimSupportRef]) -> ResolvedEpistemicProof:
        statuses: set[str] = set()
        proof_refs: list[str] = []
        proof_source_kinds: list[str] = []
        proof_evidence_ids: list[str] = []
        unresolved: list[str] = []
        for support in support_refs:
            if support.support_kind == SupportKind.GEOLOGICAL_EVIDENCE:
                self._resolve_geological_evidence(
                    support.support_id,
                    statuses,
                    proof_refs,
                    proof_source_kinds,
                    proof_evidence_ids,
                    unresolved,
                )
            elif support.support_kind in {
                SupportKind.STATE_GRS,
                SupportKind.GRS_DIMENSION_COMPONENT,
            }:
                evidence_ids = self._lookup.grs_contributing_evidence_ids.get(
                    support.support_id, []
                )
                if not evidence_ids:
                    unresolved.append(support.support_id)
                for evidence_id in evidence_ids:
                    self._resolve_geological_evidence(
                        evidence_id,
                        statuses,
                        proof_refs,
                        proof_source_kinds,
                        proof_evidence_ids,
                        unresolved,
                    )
        return ResolvedEpistemicProof(
            resolved_statuses=statuses,
            proof_refs=proof_refs,
            proof_source_kinds=proof_source_kinds,
            proof_evidence_ids=proof_evidence_ids,
            unresolved_support_ids=unresolved,
            status="RESOLVED" if statuses else "UNRESOLVED",
        )

    def _resolve_geological_evidence(
        self,
        evidence_id: str,
        statuses: set[str],
        proof_refs: list[str],
        proof_source_kinds: list[str],
        proof_evidence_ids: list[str],
        unresolved: list[str],
    ) -> None:
        evidence = self._lookup.geological_evidence.get(evidence_id)
        if evidence is None:
            unresolved.append(evidence_id)
            return
        if evidence.epistemic_status:
            statuses.add(evidence.epistemic_status.upper())
            proof_refs.append(evidence_id)
            proof_source_kinds.append(SupportKind.GEOLOGICAL_EVIDENCE.value)
            proof_evidence_ids.append(evidence_id)


@dataclass(frozen=True)
class MetricValidationResult:
    """Result of binding typed metric payload to formal Stage 4 support."""

    status: str
    reason: str | None
    resolved_metric_id: str | None = None


class MetricSupportResolver:
    """Validate typed metric payloads against formal Stage 4 metric support."""

    def __init__(self, lookup: ClaimUpstreamLookup) -> None:
        self._lookup = lookup

    def validate(
        self,
        payload: MetricClaimValue | None,
        required_metric: str | None,
        required_semantics: str | None,
        support_refs: list[ClaimSupportRef],
    ) -> MetricValidationResult:
        if required_metric is None:
            return MetricValidationResult("PASS", None)
        if payload is None:
            return MetricValidationResult("FAIL", "MALFORMED_CLAIM_VALUE")
        if payload.metric_name != required_metric:
            return MetricValidationResult("FAIL", "METRIC_IDENTITY_MISMATCH")
        if payload.metric_status != AVAILABLE:
            return MetricValidationResult("FAIL", "REQUIRED_METRIC_UNAVAILABLE")
        if required_semantics is not None and payload.metric_semantics != required_semantics:
            return MetricValidationResult("FAIL", "METRIC_SEMANTICS_MISMATCH")
        if payload.is_probability or payload.is_hazard_probability or payload.is_causal_estimate:
            return MetricValidationResult("FAIL", "METRIC_SEMANTICS_MISMATCH")
        formal = self._lookup.metrics.get(payload.source_metric_id)
        if formal is None:
            return MetricValidationResult("FAIL", "REQUIRED_SUPPORT_MISSING")
        if formal.metric_name != payload.metric_name:
            return MetricValidationResult("FAIL", "METRIC_IDENTITY_MISMATCH")
        if formal.metric_status != payload.metric_status:
            return MetricValidationResult("FAIL", "REQUIRED_METRIC_UNAVAILABLE")
        if formal.metric_semantics != payload.metric_semantics:
            return MetricValidationResult("FAIL", "METRIC_SEMANTICS_MISMATCH")
        if (
            formal.is_probability != payload.is_probability
            or formal.is_hazard_probability != payload.is_hazard_probability
            or formal.is_causal_estimate != payload.is_causal_estimate
        ):
            return MetricValidationResult("FAIL", "METRIC_SEMANTICS_MISMATCH")
        if formal.metric_value is None or not isclose(
            formal.metric_value,
            payload.metric_value,
            rel_tol=0.0,
            abs_tol=FLOAT_TOLERANCE,
        ):
            return MetricValidationResult("FAIL", "METRIC_VALUE_MISMATCH")
        primary_support_ids = {
            ref.support_id
            for ref in support_refs
            if ref.support_role == ClaimSupportRole.PRIMARY_SUPPORT
        }
        if payload.source_metric_id not in primary_support_ids:
            return MetricValidationResult("FAIL", "REQUIRED_SUPPORT_MISSING")
        return MetricValidationResult("PASS", None, formal.metric_id)


@dataclass(frozen=True)
class ResolvedSpatialSupport:
    """Authoritative spatial scope resolved from frozen upstream support."""

    support_id: str
    support_kind: str
    declared_scope: ClaimScope | None
    authoritative_scope: ClaimScope | None
    scope_source: str
    scope_match: bool
    resolution_status: str


class AuthoritativeSpatialResolver:
    """Resolve spatial scope from upstream objects, never from proposal metadata."""

    def __init__(self, lookup: ClaimUpstreamLookup) -> None:
        self._lookup = lookup

    def resolve(self, support: ClaimSupportRef) -> ResolvedSpatialSupport:
        authoritative_scope: ClaimScope | None = None
        source = "UNRESOLVED"
        if support.support_kind == SupportKind.GEOLOGICAL_EVIDENCE:
            evidence = self._lookup.geological_evidence.get(support.support_id)
            authoritative_scope = evidence.spatial_scope if evidence is not None else None
            source = "FROZEN_GEOLOGICAL_EVIDENCE"
        elif support.support_kind in {
            SupportKind.STATE_RAI,
            SupportKind.STATE_GRS,
            SupportKind.STATE_GRCI,
        }:
            metric = self._lookup.metrics.get(support.support_id)
            if metric is not None and metric.cell_id is not None:
                authoritative_scope = ClaimScope(
                    scope_kind=ClaimScopeKind.CELL,
                    valid_date=_parse_date(metric.valid_date),
                    cell_id=metric.cell_id,
                    state_role=metric.state_role,
                    scope_basis="stage4_metric_subject",
                )
            source = "FROZEN_STAGE4_METRIC"
        return ResolvedSpatialSupport(
            support_id=support.support_id,
            support_kind=support.support_kind.value,
            declared_scope=support.spatial_scope,
            authoritative_scope=authoritative_scope,
            scope_source=source,
            scope_match=support.spatial_scope is None
            or scopes_equal(support.spatial_scope, authoritative_scope),
            resolution_status="RESOLVED" if authoritative_scope is not None else "UNRESOLVED",
        )


class AuthoritativeSupportResolver:
    """Materialize Decision support refs from frozen upstream records."""

    def __init__(self, lookup: ClaimUpstreamLookup) -> None:
        self._lookup = lookup
        self._spatial_resolver = AuthoritativeSpatialResolver(lookup)

    def resolve_many(self, support_refs: list[ClaimSupportRef]) -> list[ResolvedClaimSupportRef]:
        """Resolve all support refs without copying proposal fact metadata."""

        return [self.resolve(ref) for ref in support_refs]

    def resolve(self, support: ClaimSupportRef) -> ResolvedClaimSupportRef:
        """Resolve one support ref from authoritative lookup records."""

        if support.support_kind == SupportKind.GEOLOGICAL_EVIDENCE:
            return self._resolve_geological_evidence(support)
        if support.support_kind in {
            SupportKind.STATE_RAI,
            SupportKind.STATE_GRS,
            SupportKind.STATE_GRCI,
        }:
            return self._resolve_metric(support)
        spatial = self._spatial_resolver.resolve(support)
        return ResolvedClaimSupportRef(
            support_kind=support.support_kind,
            support_id=support.support_id,
            support_role=support.support_role,
            resolved_epistemic_status=None,
            resolved_spatial_scope=spatial.authoritative_scope,
            resolved_state_role=None,
            trace_ref_ids=[],
            resolution_source=spatial.scope_source,
            resolution_status=spatial.resolution_status,
        )

    def _resolve_geological_evidence(
        self,
        support: ClaimSupportRef,
    ) -> ResolvedClaimSupportRef:
        evidence = self._lookup.geological_evidence.get(support.support_id)
        subjects = self._lookup.geological_subjects.get(support.support_id, [])
        subject = subjects[0] if subjects else None
        if evidence is None:
            return ResolvedClaimSupportRef(
                support_kind=support.support_kind,
                support_id=support.support_id,
                support_role=support.support_role,
                resolved_epistemic_status=None,
                resolved_spatial_scope=None,
                resolved_state_role=None,
                trace_ref_ids=[],
                resolution_source="FROZEN_GEOLOGICAL_EVIDENCE",
                resolution_status="UNRESOLVED",
            )
        return ResolvedClaimSupportRef(
            support_kind=support.support_kind,
            support_id=support.support_id,
            support_role=support.support_role,
            resolved_epistemic_status=(
                evidence.epistemic_status.upper() if evidence.epistemic_status else None
            ),
            resolved_spatial_scope=evidence.spatial_scope,
            resolved_state_role=subject.state_role if subject is not None else None,
            resolved_bitemporal_version_id=(
                subject.bitemporal_version_id if subject is not None else None
            ),
            resolved_base_stage3a_state_version_id=(
                subject.base_stage3a_state_version_id if subject is not None else None
            ),
            resolved_daily_state_id=subject.daily_state_id if subject is not None else None,
            resolved_cell_id=subject.cell_id if subject is not None else None,
            resolved_valid_date=_parse_date(subject.valid_date if subject is not None else None),
            trace_ref_ids=[support.support_id],
            resolution_source="FROZEN_GEOLOGICAL_EVIDENCE",
            resolution_status="RESOLVED",
        )

    def _resolve_metric(self, support: ClaimSupportRef) -> ResolvedClaimSupportRef:
        metric = self._lookup.metrics.get(support.support_id)
        if metric is None:
            return ResolvedClaimSupportRef(
                support_kind=support.support_kind,
                support_id=support.support_id,
                support_role=support.support_role,
                resolved_epistemic_status=None,
                resolved_spatial_scope=None,
                resolved_state_role=None,
                trace_ref_ids=[],
                resolution_source="FROZEN_STAGE4_METRIC",
                resolution_status="UNRESOLVED",
            )
        spatial_scope = (
            ClaimScope(
                scope_kind=ClaimScopeKind.CELL,
                valid_date=_parse_date(metric.valid_date),
                cell_id=metric.cell_id,
                state_role=metric.state_role,
                scope_basis="stage4_metric_subject",
            )
            if metric.cell_id is not None
            else None
        )
        return ResolvedClaimSupportRef(
            support_kind=support.support_kind,
            support_id=support.support_id,
            support_role=support.support_role,
            resolved_epistemic_status=None,
            resolved_spatial_scope=spatial_scope,
            resolved_state_role=metric.state_role,
            resolved_bitemporal_version_id=metric.bitemporal_version_id,
            resolved_base_stage3a_state_version_id=metric.base_stage3a_state_version_id,
            resolved_daily_state_id=metric.daily_state_id,
            resolved_cell_id=metric.cell_id,
            resolved_valid_date=_parse_date(metric.valid_date),
            trace_ref_ids=[metric.metric_id],
            resolution_source="FROZEN_STAGE4_METRIC",
            resolution_status="RESOLVED",
        )


@dataclass(frozen=True)
class SubjectBindingResult:
    """Resolved claim subject binding for a metric-backed proposal."""

    status: str
    reason: str | None
    resolved_metric_id: str | None = None
    resolved_bitemporal_version_id: str | None = None
    resolved_base_stage3a_state_version_id: str | None = None
    resolved_daily_state_id: str | None = None
    resolved_cell_id: str | None = None
    resolved_valid_date: str | None = None
    resolved_state_role: str | None = None
    mismatch_fields: tuple[str, ...] = ()


class ClaimSubjectResolver:
    """Bind claim subject fields to the authoritative Stage 4 metric subject."""

    def __init__(self, lookup: ClaimUpstreamLookup) -> None:
        self._lookup = lookup

    def validate_metric_subject(
        self,
        proposal: ClaimProposal,
        payload: MetricClaimValue | None,
    ) -> SubjectBindingResult:
        if payload is None:
            return SubjectBindingResult("PASS", None)
        metric = self._lookup.metrics.get(payload.source_metric_id)
        if metric is None:
            return SubjectBindingResult("FAIL", "REQUIRED_SUPPORT_MISSING")
        mismatches: list[str] = []
        comparisons = [
            ("bitemporal_version_id", proposal.bitemporal_version_id, metric.bitemporal_version_id),
            (
                "base_stage3a_state_version_id",
                proposal.base_stage3a_state_version_id or proposal.state_version_id,
                metric.base_stage3a_state_version_id,
            ),
            ("daily_state_id", proposal.daily_state_id, metric.daily_state_id),
            ("cell_id", proposal.cell_id, metric.cell_id),
            (
                "valid_date",
                str(proposal.valid_date) if proposal.valid_date is not None else None,
                metric.valid_date,
            ),
            ("state_role", proposal.state_role, metric.state_role),
        ]
        for field_name, declared, resolved in comparisons:
            if declared is not None and resolved is not None and declared != resolved:
                mismatches.append(field_name)
            if declared is not None and resolved is None:
                mismatches.append(field_name)
        if proposal.scope.scope_kind == ClaimScopeKind.CELL:
            if metric.cell_id is not None and proposal.scope.cell_id != metric.cell_id:
                mismatches.append("scope.cell_id")
            if (
                proposal.scope.valid_date is not None
                and metric.valid_date is not None
                and str(proposal.scope.valid_date) != metric.valid_date
            ):
                mismatches.append("scope.valid_date")
            if (
                proposal.scope.state_role is not None
                and metric.state_role is not None
                and proposal.scope.state_role != metric.state_role
            ):
                mismatches.append("scope.state_role")
        status = "FAIL" if mismatches else "PASS"
        return SubjectBindingResult(
            status=status,
            reason="CLAIM_SUBJECT_MISMATCH" if mismatches else None,
            resolved_metric_id=metric.metric_id,
            resolved_bitemporal_version_id=metric.bitemporal_version_id,
            resolved_base_stage3a_state_version_id=metric.base_stage3a_state_version_id,
            resolved_daily_state_id=metric.daily_state_id,
            resolved_cell_id=metric.cell_id,
            resolved_valid_date=metric.valid_date,
            resolved_state_role=metric.state_role,
            mismatch_fields=tuple(sorted(set(mismatches))),
        )

    def validate_geological_subject(
        self,
        proposal: ClaimProposal,
        payload: GeologicalConditionClaimValue | None,
    ) -> SubjectBindingResult:
        if payload is None:
            return SubjectBindingResult("PASS", None)
        subjects = self._lookup.geological_subjects.get(payload.source_evidence_id, [])
        declared = _declared_subject_fields(proposal)
        if not declared:
            subject = subjects[0] if subjects else None
            return _subject_result_from_record("PASS", None, subject)
        for subject in subjects:
            if _subject_matches_declared(subject, declared):
                return _subject_result_from_record("PASS", None, subject)
        mismatch_fields = tuple(sorted(declared))
        return _subject_result_from_record(
            "FAIL",
            "CLAIM_SUBJECT_MISMATCH",
            subjects[0] if subjects else None,
            mismatch_fields,
        )


def _declared_subject_fields(proposal: ClaimProposal) -> dict[str, str]:
    declared: dict[str, str] = {}
    values = {
        "bitemporal_version_id": proposal.bitemporal_version_id,
        "base_stage3a_state_version_id": (
            proposal.base_stage3a_state_version_id or proposal.state_version_id
        ),
        "daily_state_id": proposal.daily_state_id,
        "cell_id": proposal.cell_id,
        "valid_date": str(proposal.valid_date) if proposal.valid_date is not None else None,
        "state_role": proposal.state_role,
    }
    for field_name, value in values.items():
        if value is not None:
            declared[field_name] = value
    if proposal.scope.scope_kind == ClaimScopeKind.CELL:
        if proposal.scope.cell_id is not None:
            declared["cell_id"] = proposal.scope.cell_id
        if proposal.scope.valid_date is not None:
            declared["valid_date"] = str(proposal.scope.valid_date)
        if proposal.scope.state_role is not None:
            declared["state_role"] = proposal.scope.state_role
    return declared


def _subject_matches_declared(subject: SubjectRecord, declared: dict[str, str]) -> bool:
    values = {
        "bitemporal_version_id": subject.bitemporal_version_id,
        "base_stage3a_state_version_id": subject.base_stage3a_state_version_id,
        "daily_state_id": subject.daily_state_id,
        "cell_id": subject.cell_id,
        "valid_date": subject.valid_date,
        "state_role": subject.state_role,
    }
    return all(values.get(field_name) == value for field_name, value in declared.items())


def _subject_result_from_record(
    status: str,
    reason: str | None,
    subject: SubjectRecord | None,
    mismatch_fields: tuple[str, ...] = (),
) -> SubjectBindingResult:
    return SubjectBindingResult(
        status=status,
        reason=reason,
        resolved_metric_id=None,
        resolved_bitemporal_version_id=subject.bitemporal_version_id if subject else None,
        resolved_base_stage3a_state_version_id=(
            subject.base_stage3a_state_version_id if subject else None
        ),
        resolved_daily_state_id=subject.daily_state_id if subject else None,
        resolved_cell_id=subject.cell_id if subject else None,
        resolved_valid_date=subject.valid_date if subject else None,
        resolved_state_role=subject.state_role if subject else None,
        mismatch_fields=mismatch_fields,
    )


@dataclass(frozen=True)
class SpatialValidationResult:
    """Result of support-to-claim spatial containment."""

    status: str
    reason: str | None


class SpatialRelationEvaluator:
    """Evaluate structured spatial containment for Stage 5A claims."""

    def __init__(self, lookup: ClaimUpstreamLookup) -> None:
        self._lookup = lookup
        self._spatial_resolver = AuthoritativeSpatialResolver(lookup)

    def validate_fact_scope(
        self,
        claim_scope: ClaimScope,
        support_refs: list[ClaimSupportRef],
    ) -> SpatialValidationResult:
        if claim_scope.scope_kind == ClaimScopeKind.UNLOCATED:
            return SpatialValidationResult("FAIL", "SPATIAL_SCOPE_UNAVAILABLE")
        primary_supports = [
            ref
            for ref in support_refs
            if ref.support_role == ClaimSupportRole.PRIMARY_SUPPORT
            and ref.support_kind == SupportKind.GEOLOGICAL_EVIDENCE
        ]
        for support in primary_supports:
            resolved = self._spatial_resolver.resolve(support)
            if not resolved.scope_match:
                return SpatialValidationResult("FAIL", "SUPPORT_SCOPE_MISMATCH")
            support_scope = resolved.authoritative_scope
            if support_scope is None or support_scope.scope_kind == ClaimScopeKind.UNLOCATED:
                return SpatialValidationResult("FAIL", "SPATIAL_SCOPE_UNAVAILABLE")
            if not self.contains(support_scope, claim_scope):
                return SpatialValidationResult("FAIL", "CLAIM_SCOPE_EXCEEDS_SUPPORT")
        return SpatialValidationResult("PASS", None)

    def validate_metric_scope(
        self,
        claim_scope: ClaimScope,
        payload: MetricClaimValue | None,
    ) -> SpatialValidationResult:
        if payload is None:
            return SpatialValidationResult("PASS", None)
        formal = self._lookup.metrics.get(payload.source_metric_id)
        if formal is None or formal.cell_id is None:
            return SpatialValidationResult("FAIL", "REQUIRED_SUPPORT_MISSING")
        if claim_scope.scope_kind != ClaimScopeKind.CELL:
            return SpatialValidationResult("FAIL", "CLAIM_SCOPE_EXCEEDS_SUPPORT")
        if claim_scope.cell_id != formal.cell_id:
            return SpatialValidationResult("FAIL", "CLAIM_SCOPE_EXCEEDS_SUPPORT")
        return SpatialValidationResult("PASS", None)

    def contains(self, support: ClaimScope, claim: ClaimScope) -> bool:
        if (
            support.scope_kind == ClaimScopeKind.UNLOCATED
            or claim.scope_kind == ClaimScopeKind.UNLOCATED
        ):
            return False
        if claim.scope_kind == ClaimScopeKind.CELL:
            return support.scope_kind == ClaimScopeKind.CELL and support.cell_id == claim.cell_id
        if claim.scope_kind == ClaimScopeKind.LOCATED_POINT:
            return self._contains_point(support, claim.point_chainage)
        if claim.scope_kind == ClaimScopeKind.LOCATED_INTERVAL:
            return self._contains_interval(support, claim.start_chainage, claim.end_chainage)
        if claim.scope_kind == ClaimScopeKind.DAILY_SCOPE:
            return support.scope_kind == ClaimScopeKind.DAILY_SCOPE
        return False

    def _contains_point(self, support: ClaimScope, point: float | None) -> bool:
        if point is None:
            return False
        if support.scope_kind == ClaimScopeKind.LOCATED_POINT:
            return support.point_chainage is not None and isclose(
                support.point_chainage,
                point,
                rel_tol=0.0,
                abs_tol=FLOAT_TOLERANCE,
            )
        if support.scope_kind == ClaimScopeKind.LOCATED_INTERVAL:
            return (
                support.start_chainage is not None
                and support.end_chainage is not None
                and support.start_chainage < point <= support.end_chainage
            )
        return False

    def _contains_interval(
        self,
        support: ClaimScope,
        start: float | None,
        end: float | None,
    ) -> bool:
        if start is None or end is None:
            return False
        if support.scope_kind != ClaimScopeKind.LOCATED_INTERVAL:
            return False
        return (
            support.start_chainage is not None
            and support.end_chainage is not None
            and support.start_chainage <= start
            and end <= support.end_chainage
        )


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
