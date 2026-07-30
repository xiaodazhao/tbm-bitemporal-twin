"""Dynamic evidence and applicability models."""

from tbm_twin.evidence.models import (
    ApplicabilityResult,
    EvidenceApplicabilityAssignment,
    EvidenceBase,
    EvidenceQualityGrade,
    EvidenceType,
    GeologicalEvidence,
    ResponseEvidence,
)

__all__ = [
    "ApplicabilityResult",
    "EvidenceApplicabilityAssignment",
    "EvidenceBase",
    "EvidenceQualityGrade",
    "EvidenceType",
    "GeologicalEvidence",
    "ResponseEvidence",
    "assign_evidence_to_episode",
    "build_response_evidence",
    "normalize_geological_evidence",
]


def __getattr__(name: str) -> object:
    """Lazily expose helper functions without creating package import cycles."""

    if name == "assign_evidence_to_episode":
        from tbm_twin.evidence.applicability import assign_evidence_to_episode

        return assign_evidence_to_episode
    if name == "build_response_evidence":
        from tbm_twin.evidence.response_builder import build_response_evidence

        return build_response_evidence
    if name == "normalize_geological_evidence":
        from tbm_twin.evidence.geology_normalizer import normalize_geological_evidence

        return normalize_geological_evidence
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
