"""Strict Stage 6A realization-boundary models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

STRICT = ConfigDict(frozen=True, extra="forbid")

STAGE6A_METHOD_VERSION = "stage6a_fact_lock_evidence_pack_v1_frozen"
STAGE6A_SCHEMA_VERSION = "stage6a_fact_lock_evidence_pack.v1"
STAGE6A_STATUS = "FROZEN"
STAGE6A_GENERATED_AT = "2026-08-12T00:00:00+08:00"
STAGE6A_OUTPUT = "artifacts/stage6a_fact_lock_evidence_pack_v1"

STAGE5B_ARTIFACT = "artifacts/stage5b_deterministic_claim_builder_v1"
STAGE5C_ARTIFACT = "artifacts/stage5c_claim_expressibility_analysis_v1"
STAGE4_ARTIFACT = "artifacts/stage4_bitemporal_state_metrics_v1_1"
STAGE5A_ARTIFACT = "artifacts/stage5a_typed_claim_contract_v1_1"


class LockedEngineeringFact(BaseModel):
    """Immutable deterministic projection of one EXPRESSIBLE TypedEngineeringClaim."""

    model_config = STRICT

    fact_lock_id: str
    source_claim_id: str
    claim_type: str
    valid_date: str | None
    bitemporal_version_id: str | None
    base_stage3a_state_version_id: str | None
    state_version_id: str | None
    daily_state_id: str | None
    cell_id: str | None
    state_role: str
    spatial_scope: dict[str, Any]
    claim_modality: str
    semantic_interpretation: str
    claim_value: dict[str, Any]
    required_qualifiers: list[str]
    authoritative_support_refs: list[dict[str, Any]]
    trace_refs: list[str]
    allowed_rendering_semantics: list[str]
    prohibited_transformations: list[str]
    source_contract_id: str
    source_schema_version: str
    source_decision_id: str
    source_opportunity_id: str
    source_proposal_id: str
    lock_hash: str

    @model_validator(mode="after")
    def validate_lock_boundary(self) -> LockedEngineeringFact:
        """Reject common semantic-boundary violations."""

        if not self.source_claim_id:
            msg = "LockedEngineeringFact requires source_claim_id"
            raise ValueError(msg)
        if not self.authoritative_support_refs:
            msg = "LockedEngineeringFact requires authoritative support"
            raise ValueError(msg)
        if (
            self.claim_type == "FORECAST_GEOLOGICAL_CONDITION"
            and self.claim_modality != "GEOLOGICAL_FORECAST"
        ):
            msg = "FORECAST_GEOLOGICAL_CONDITION must retain forecast modality"
            raise ValueError(msg)
        if (
            self.claim_type == "OBSERVED_GEOLOGICAL_CONDITION"
            and self.claim_modality != "GEOLOGICAL_OBSERVED"
        ):
            msg = "OBSERVED_GEOLOGICAL_CONDITION must retain observed modality"
            raise ValueError(msg)
        if self.claim_type in {
            "OPERATIONAL_RESPONSE_ATTENTION",
            "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
            "COUPLED_ATTENTION_REVIEW",
            "FORWARD_GEOLOGICAL_ATTENTION",
        }:
            if self.claim_value.get("is_probability") is not False:
                msg = "Attention metric fact must not become a probability"
                raise ValueError(msg)
            if self.claim_value.get("is_hazard_probability") is not False:
                msg = "Attention metric fact must not become a hazard probability"
                raise ValueError(msg)
            if self.claim_value.get("is_causal_estimate") is not False:
                msg = "Attention metric fact must not become a causal estimate"
                raise ValueError(msg)
        return self


class RenderingContract(BaseModel):
    """Machine-readable contract for future surface realization."""

    model_config = STRICT

    contract_id: str
    contract_hash: str
    schema_version: str
    may: list[str]
    must: list[str]
    must_not: list[str]
    claim_type_policies: dict[str, dict[str, list[str] | str]]


class ControlledEvidencePack(BaseModel):
    """Minimal controlled input for future realization."""

    model_config = STRICT

    pack_id: str
    schema_version: str
    method_version: str
    task_context: str
    valid_date: str | None = None
    knowledge_context: dict[str, Any]
    locked_facts: list[LockedEngineeringFact]
    abstention_summary: list[dict[str, Any]]
    generation_contract: RenderingContract
    provenance_index: dict[str, dict[str, Any]]
    pack_hash: str

    @model_validator(mode="after")
    def validate_authoritative_facts_are_locked(self) -> ControlledEvidencePack:
        """Ensure the pack exposes only FactLocks as authoritative engineering facts."""

        fact_ids = {fact.fact_lock_id for fact in self.locked_facts}
        for fact_id in self.provenance_index:
            if fact_id not in fact_ids:
                msg = "provenance_index keys must be locked fact IDs"
                raise ValueError(msg)
        return self


class SliceSpec(BaseModel):
    """Deterministic Stage6A pack slicing filters."""

    model_config = STRICT

    valid_date: str | None = None
    state_role: str | None = None
    cell_id: str | None = None
    claim_type: str | None = None
    product_type: Literal["daily_review", "forward_attention", "metric_review", "all"] = "all"
