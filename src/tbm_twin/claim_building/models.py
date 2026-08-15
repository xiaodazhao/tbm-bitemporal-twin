"""Stage 5B claim-building records."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tbm_twin.claims.models import ClaimType

STRICT = ConfigDict(frozen=True, extra="forbid")
STAGE5B_CANDIDATE_METHOD_VERSION = "stage5b_deterministic_claim_builder_v1_candidate"
STAGE5B_FORMAL_METHOD_VERSION = "stage5b_deterministic_claim_builder_v1_frozen"
STAGE5B_METHOD_VERSION = STAGE5B_CANDIDATE_METHOD_VERSION
STAGE5B_SCHEMA_VERSION = "stage5b_deterministic_claim_materialization.v1"


class ClaimOpportunity(BaseModel):
    """A deterministic chance to ask Stage5A whether a claim is expressible."""

    model_config = STRICT

    opportunity_id: str
    semantic_key: str
    claim_type: ClaimType
    valid_date: str
    bitemporal_version_id: str | None = None
    base_stage3a_state_version_id: str | None = None
    daily_state_id: str | None = None
    cell_id: str | None = None
    state_role: str
    source_kind: str
    source_object_ids: list[str]
    source_origin: Literal["FORMAL_UPSTREAM"]
    opportunity_basis: str
    builder_version: str = STAGE5B_METHOD_VERSION
    payload: dict[str, Any] = Field(default_factory=dict)


class ProposalConstructionRecord(BaseModel):
    """Stage5B proposal-construction outcome for one opportunity."""

    model_config = STRICT

    opportunity_id: str
    proposal_id: str | None = None
    claim_type: ClaimType
    status: Literal["CONSTRUCTED", "NOT_CONSTRUCTIBLE"]
    reason: str | None = None
    builder_version: str = STAGE5B_METHOD_VERSION


class ClaimAbstentionRecord(BaseModel):
    """Materialized Stage5B abstention for an evaluated opportunity."""

    model_config = STRICT

    abstention_id: str
    opportunity_id: str
    proposal_id: str
    decision_id: str
    claim_type: ClaimType
    valid_date: str
    bitemporal_version_id: str | None = None
    base_stage3a_state_version_id: str | None = None
    daily_state_id: str | None = None
    cell_id: str | None = None
    state_role: str
    abstention_reason: str
    failed_rules: list[str]
    resolved_support_summary: str
    builder_version: str = STAGE5B_METHOD_VERSION
