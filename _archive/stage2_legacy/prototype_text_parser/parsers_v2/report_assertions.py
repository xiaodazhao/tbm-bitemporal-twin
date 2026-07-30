"""ReportAssertion helpers."""

from __future__ import annotations

from tbm_twin.geology.parsers_v2.models import (
    ReportAssertion,
    SourceSpan,
    V2SpatialScope,
)
from tbm_twin.geology.parsers_v2.provenance import stable_id


def make_assertion(
    *,
    document_id: str,
    assertion_type: str,
    spatial_scope: V2SpatialScope,
    raw_text: str,
    source_spans: list[SourceSpan],
    derived_from_evidence_ids: list[str],
    consistency_status: str = "NOT_CHECKED",
    conflict_details: list[str] | None = None,
) -> ReportAssertion:
    """Build a deterministic report assertion."""

    return ReportAssertion(
        assertion_id=stable_id("assertion", document_id, assertion_type, raw_text),
        document_id=document_id,
        assertion_type=assertion_type,
        spatial_scope=spatial_scope,
        raw_text=raw_text,
        source_spans=source_spans,
        derived_from_evidence_ids=derived_from_evidence_ids,
        consistency_status=consistency_status,
        conflict_details=conflict_details or [],
    )
