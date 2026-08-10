"""Strict Stage 5A typed engineering claim models."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STAGE5A_METHOD_VERSION = "stage5a_typed_claim_contract_v1_candidate"
STAGE5A_SCHEMA_VERSION = "stage5a_typed_claim_contract.v1"
STAGE5A_CONTRACT_VERSION = "claim_contract_v1"
STRICT = ConfigDict(frozen=True, extra="forbid")


class ClaimType(StrEnum):
    """Stage 5A V1 source-constrained claim types."""

    OPERATIONAL_RESPONSE_ATTENTION = "OPERATIONAL_RESPONSE_ATTENTION"
    GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW = "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW"
    COUPLED_ATTENTION_REVIEW = "COUPLED_ATTENTION_REVIEW"
    FORWARD_GEOLOGICAL_ATTENTION = "FORWARD_GEOLOGICAL_ATTENTION"
    OBSERVED_GEOLOGICAL_CONDITION = "OBSERVED_GEOLOGICAL_CONDITION"
    FORECAST_GEOLOGICAL_CONDITION = "FORECAST_GEOLOGICAL_CONDITION"


class ClaimScopeKind(StrEnum):
    """Structured claim scope kinds."""

    LOCATED_POINT = "LOCATED_POINT"
    LOCATED_INTERVAL = "LOCATED_INTERVAL"
    CELL = "CELL"
    DAILY_SCOPE = "DAILY_SCOPE"
    UNLOCATED = "UNLOCATED"


class ClaimModality(StrEnum):
    """Epistemic/linguistic modality of a structured claim."""

    OPERATIONAL_DERIVED = "OPERATIONAL_DERIVED"
    DERIVED_ATTENTION = "DERIVED_ATTENTION"
    GEOLOGICAL_OBSERVED = "GEOLOGICAL_OBSERVED"
    GEOLOGICAL_FORECAST = "GEOLOGICAL_FORECAST"


class ClaimSemanticInterpretation(StrEnum):
    """Structured semantic interpretation, including explicitly forbidden proposals."""

    OPERATIONAL_RESPONSE_ATTENTION = "OPERATIONAL_RESPONSE_ATTENTION"
    GEOLOGICAL_EVIDENCE_ATTENTION = "GEOLOGICAL_EVIDENCE_ATTENTION"
    COUPLED_ATTENTION = "COUPLED_ATTENTION"
    OBSERVED_GEOLOGICAL_CONDITION = "OBSERVED_GEOLOGICAL_CONDITION"
    FORECAST_GEOLOGICAL_CONDITION = "FORECAST_GEOLOGICAL_CONDITION"
    RISK_PROBABILITY = "RISK_PROBABILITY"
    HAZARD_PROBABILITY = "HAZARD_PROBABILITY"
    FAILURE_PROBABILITY = "FAILURE_PROBABILITY"
    CAUSAL_GEOLOGICAL_DIAGNOSIS = "CAUSAL_GEOLOGICAL_DIAGNOSIS"
    CAUSAL_MECHANICAL_DIAGNOSIS = "CAUSAL_MECHANICAL_DIAGNOSIS"


class ClaimExpressibility(StrEnum):
    """Deterministic Stage 5A contract outcome."""

    EXPRESSIBLE = "EXPRESSIBLE"
    ABSTAIN = "ABSTAIN"


class ClaimAbstentionReason(StrEnum):
    """Formal reasons for not expressing a claim."""

    REQUIRED_METRIC_UNAVAILABLE = "REQUIRED_METRIC_UNAVAILABLE"
    REQUIRED_SUPPORT_MISSING = "REQUIRED_SUPPORT_MISSING"
    REQUIRED_EPISTEMIC_STATUS_MISSING = "REQUIRED_EPISTEMIC_STATUS_MISSING"
    STATE_ROLE_NOT_ALLOWED = "STATE_ROLE_NOT_ALLOWED"
    EPISTEMIC_PROMOTION_FORBIDDEN = "EPISTEMIC_PROMOTION_FORBIDDEN"
    UNKNOWN_SOURCE_VALUE = "UNKNOWN_SOURCE_VALUE"
    SPATIAL_SCOPE_UNAVAILABLE = "SPATIAL_SCOPE_UNAVAILABLE"
    SUPPORT_SEMANTIC_MISMATCH = "SUPPORT_SEMANTIC_MISMATCH"
    SUPPORT_KIND_NOT_ALLOWED = "SUPPORT_KIND_NOT_ALLOWED"
    SUPPORT_SCOPE_MISMATCH = "SUPPORT_SCOPE_MISMATCH"
    METRIC_IDENTITY_MISMATCH = "METRIC_IDENTITY_MISMATCH"
    METRIC_VALUE_MISMATCH = "METRIC_VALUE_MISMATCH"
    METRIC_SEMANTICS_MISMATCH = "METRIC_SEMANTICS_MISMATCH"
    MALFORMED_CLAIM_VALUE = "MALFORMED_CLAIM_VALUE"
    ATTRIBUTE_VALUE_MISMATCH = "ATTRIBUTE_VALUE_MISMATCH"
    ATTRIBUTE_NOT_FOUND = "ATTRIBUTE_NOT_FOUND"
    CLAIM_SUBJECT_MISMATCH = "CLAIM_SUBJECT_MISMATCH"
    FORBIDDEN_SEMANTIC_INTERPRETATION = "FORBIDDEN_SEMANTIC_INTERPRETATION"
    CONTEXT_ONLY_ROLE = "CONTEXT_ONLY_ROLE"
    CLAIM_SCOPE_EXCEEDS_SUPPORT = "CLAIM_SCOPE_EXCEEDS_SUPPORT"
    UNSUPPORTED_CLAIM_TYPE = "UNSUPPORTED_CLAIM_TYPE"


class ClaimQualifier(StrEnum):
    """Structured qualifiers carried forward for later language generation."""

    FORECAST = "FORECAST"
    PREDICTED = "PREDICTED"
    INDICATED_AHEAD = "INDICATED_AHEAD"
    AHEAD_OF_FACE = "AHEAD_OF_FACE"
    PLC_INFERRED = "PLC_INFERRED"
    NONPROBABILISTIC_ATTENTION = "NONPROBABILISTIC_ATTENTION"
    SOURCE_CONSTRAINED = "SOURCE_CONSTRAINED"


class SupportKind(StrEnum):
    """Formal upstream objects that Stage 5A may reference by ID."""

    CONSTRUCTION_STATE_VERSION = "CONSTRUCTION_STATE_VERSION"
    DAILY_CONSTRUCTION_STATE = "DAILY_CONSTRUCTION_STATE"
    STATE_RAI = "STATE_RAI"
    STATE_GRS = "STATE_GRS"
    STATE_GRCI = "STATE_GRCI"
    RAI_FAMILY_COMPONENT = "RAI_FAMILY_COMPONENT"
    GRS_DIMENSION_COMPONENT = "GRS_DIMENSION_COMPONENT"
    RESPONSE_EVIDENCE = "RESPONSE_EVIDENCE"
    GEOLOGICAL_EVIDENCE = "GEOLOGICAL_EVIDENCE"
    EXCAVATION_EPISODE = "EXCAVATION_EPISODE"
    SOURCE_SPAN = "SOURCE_SPAN"
    SOURCE_ASSET = "SOURCE_ASSET"


class ClaimSupportRole(StrEnum):
    """Role played by a support reference."""

    PRIMARY_SUPPORT = "PRIMARY_SUPPORT"
    DERIVATION_SUPPORT = "DERIVATION_SUPPORT"
    TRACE_SUPPORT = "TRACE_SUPPORT"


class ClaimScope(BaseModel):
    """Structured temporal, spatial and state-role scope."""

    model_config = STRICT

    scope_kind: ClaimScopeKind
    valid_date: date | None = None
    cell_id: str | None = None
    daily_state_id: str | None = None
    state_role: str | None = None
    start_chainage: float | None = None
    end_chainage: float | None = None
    point_chainage: float | None = None
    scope_basis: str

    @model_validator(mode="after")
    def validate_scope_geometry(self) -> ClaimScope:
        """Ensure scope kind and chainage geometry agree."""

        if self.scope_kind == ClaimScopeKind.LOCATED_POINT and self.point_chainage is None:
            msg = "LOCATED_POINT scope requires point_chainage"
            raise ValueError(msg)
        if self.scope_kind == ClaimScopeKind.LOCATED_INTERVAL:
            if self.start_chainage is None or self.end_chainage is None:
                msg = "LOCATED_INTERVAL scope requires start_chainage and end_chainage"
                raise ValueError(msg)
            if self.start_chainage >= self.end_chainage:
                msg = "LOCATED_INTERVAL scope requires start_chainage < end_chainage"
                raise ValueError(msg)
        if self.scope_kind == ClaimScopeKind.CELL and self.cell_id is None:
            msg = "CELL scope requires cell_id"
            raise ValueError(msg)
        return self


class ClaimSupportRef(BaseModel):
    """ID-only support reference to a frozen upstream object."""

    model_config = STRICT

    support_kind: SupportKind
    support_id: str
    support_role: ClaimSupportRole
    epistemic_status: str | None = None
    state_role: str | None = None
    semantic_tags: list[str] = Field(default_factory=list)
    spatial_scope: ClaimScope | None = None
    trace_ref_ids: list[str] = Field(default_factory=list)


class ResolvedClaimSupportRef(BaseModel):
    """Authoritative support reference materialized from frozen upstream lookup."""

    model_config = STRICT

    support_kind: SupportKind
    support_id: str
    support_role: ClaimSupportRole
    resolved_epistemic_status: str | None = None
    resolved_spatial_scope: ClaimScope | None = None
    resolved_state_role: str | None = None
    resolved_bitemporal_version_id: str | None = None
    resolved_base_stage3a_state_version_id: str | None = None
    resolved_daily_state_id: str | None = None
    resolved_cell_id: str | None = None
    resolved_valid_date: date | None = None
    trace_ref_ids: list[str] = Field(default_factory=list)
    resolution_source: str
    resolution_status: str


class ClaimContract(BaseModel):
    """Source-constrained expressibility contract for one claim type."""

    model_config = STRICT

    contract_id: str
    contract_version: str
    schema_version: str
    claim_type: ClaimType
    allowed_state_roles: list[str]
    required_support_kinds: list[SupportKind]
    allowed_support_kinds: list[SupportKind]
    forbidden_support_kinds: list[SupportKind] = Field(default_factory=list)
    allowed_modalities: list[ClaimModality]
    allowed_semantic_interpretations: list[ClaimSemanticInterpretation]
    required_epistemic_statuses: list[str] = Field(default_factory=list)
    forbidden_epistemic_promotions: list[str] = Field(default_factory=list)
    required_metric: str | None = None
    requires_spatial_location: bool = False
    required_qualifiers: list[ClaimQualifier] = Field(default_factory=list)
    forbidden_semantics: list[ClaimSemanticInterpretation]
    generation_eligible: bool
    metric_semantics: str | None = None
    notes: str


class MetricClaimValue(BaseModel):
    """Typed Stage 5A metric claim payload bound to a formal Stage 4 metric object."""

    model_config = STRICT

    metric_name: str
    metric_value: float
    metric_status: str
    metric_semantics: str
    is_probability: bool
    is_hazard_probability: bool
    is_causal_estimate: bool
    source_metric_id: str

    @field_validator("metric_value")
    @classmethod
    def validate_metric_value_range(cls, value: float) -> float:
        """Stage 4 RAI/GRS/GRCI values are normalized attention values."""

        if value < 0.0 or value > 1.0:
            msg = "metric_value must be in [0, 1]"
            raise ValueError(msg)
        return value


class GeologicalConditionClaimValue(BaseModel):
    """Typed geological condition payload bound to structured geological evidence."""

    model_config = STRICT

    source_evidence_id: str
    attribute_name: str
    normalized_value: str
    attribute_dimension: str | None = None


ClaimValue = MetricClaimValue | GeologicalConditionClaimValue


class ClaimProposal(BaseModel):
    """Structured proposal evaluated by a ClaimContract."""

    model_config = STRICT

    proposal_id: str
    claim_type: ClaimType
    bitemporal_version_id: str | None = None
    base_stage3a_state_version_id: str | None = None
    state_version_id: str | None = None
    daily_state_id: str | None = None
    cell_id: str | None = None
    state_role: str
    valid_date: date | None = None
    scope: ClaimScope
    modality: ClaimModality
    semantic_interpretation: ClaimSemanticInterpretation
    claim_value: ClaimValue | None = None
    support_refs: list[ClaimSupportRef]
    metric_statuses: dict[str, str] = Field(default_factory=dict)
    source_epistemic_statuses: list[str] = Field(default_factory=list)
    has_unknown_source_value: bool = False
    required_qualifiers: list[ClaimQualifier] = Field(default_factory=list)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("support_refs")
    @classmethod
    def require_support_roles(cls, value: list[ClaimSupportRef]) -> list[ClaimSupportRef]:
        """Require explicit support role on every support ref."""

        if not value:
            msg = "ClaimProposal requires at least one support_ref"
            raise ValueError(msg)
        return value


class ClaimDecision(BaseModel):
    """Deterministic contract evaluation result."""

    model_config = STRICT

    decision_id: str
    proposal_id: str
    contract_id: str | None
    claim_type: ClaimType
    expressibility: ClaimExpressibility
    abstention_reason: ClaimAbstentionReason | None
    failed_rules: list[str]
    passed_rules: list[str]
    required_qualifiers: list[ClaimQualifier]
    resolved_support_refs: list[ResolvedClaimSupportRef]
    schema_version: str = STAGE5A_SCHEMA_VERSION

    @model_validator(mode="after")
    def validate_decision_consistency(self) -> ClaimDecision:
        """Ensure expressibility and abstention fields cannot contradict each other."""

        if self.expressibility == ClaimExpressibility.EXPRESSIBLE:
            if self.abstention_reason is not None:
                msg = "EXPRESSIBLE decision cannot include abstention_reason"
                raise ValueError(msg)
            if self.failed_rules:
                msg = "EXPRESSIBLE decision cannot include failed_rules"
                raise ValueError(msg)
            unresolved_primary = [
                ref
                for ref in self.resolved_support_refs
                if ref.support_role == ClaimSupportRole.PRIMARY_SUPPORT
                and ref.resolution_status != "RESOLVED"
            ]
            if unresolved_primary:
                msg = "EXPRESSIBLE decision requires resolved primary support"
                raise ValueError(msg)
        if self.expressibility == ClaimExpressibility.ABSTAIN:
            if self.abstention_reason is None:
                msg = "ABSTAIN decision requires abstention_reason"
                raise ValueError(msg)
            if not self.failed_rules:
                msg = "ABSTAIN decision requires failed_rules"
                raise ValueError(msg)
        return self


class TypedEngineeringClaim(BaseModel):
    """Schema-only Stage 5A typed engineering claim object."""

    model_config = STRICT

    claim_id: str
    schema_version: str
    claim_type: ClaimType
    bitemporal_version_id: str | None = None
    base_stage3a_state_version_id: str | None = None
    state_version_id: str | None = None
    daily_state_id: str | None = None
    cell_id: str | None = None
    state_role: str
    valid_date: date | None = None
    spatial_scope: ClaimScope
    claim_modality: ClaimModality
    semantic_interpretation: ClaimSemanticInterpretation
    claim_value: ClaimValue
    support_refs: list[ClaimSupportRef]
    contract_id: str
    expressibility_status: ClaimExpressibility
    abstention_reason: ClaimAbstentionReason | None
    required_qualifiers: list[ClaimQualifier]
    trace_refs: list[str]
    metadata: dict[str, str | int | float | bool | None]

    @model_validator(mode="after")
    def validate_claim_consistency(self) -> TypedEngineeringClaim:
        """Ensure materialized claims cannot contradict their expressibility status."""

        if (
            self.expressibility_status == ClaimExpressibility.EXPRESSIBLE
            and self.abstention_reason is not None
        ):
            msg = "EXPRESSIBLE claim cannot include abstention_reason"
            raise ValueError(msg)
        if (
            self.expressibility_status == ClaimExpressibility.ABSTAIN
            and self.abstention_reason is None
        ):
            msg = "ABSTAIN claim requires abstention_reason"
            raise ValueError(msg)
        return self


RUNTIME_ID_IGNORED_KEYS = frozenset({"generated_at", "generated_at_utc"})


def _strip_runtime_id_fields(value: Any) -> Any:
    """Remove runtime metadata that must never affect business IDs."""

    if isinstance(value, dict):
        return {
            key: _strip_runtime_id_fields(item)
            for key, item in value.items()
            if key not in RUNTIME_ID_IGNORED_KEYS
        }
    if isinstance(value, list):
        return [_strip_runtime_id_fields(item) for item in value]
    return value


def canonical_payload(value: BaseModel | dict[str, Any]) -> str:
    """Return deterministic JSON for ID generation."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    stable_payload = _strip_runtime_id_fields(payload)
    return json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_id(prefix: str, payload: BaseModel | dict[str, Any]) -> str:
    """Generate a stable business ID independent of runtime metadata."""

    digest = hashlib.sha256(canonical_payload(payload).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"
