"""Strict Stage 6B controlled realization models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

STRICT = ConfigDict(frozen=True, extra="forbid")

STAGE6B_METHOD_VERSION = "stage6b_controlled_realization_v1_candidate"
STAGE6B_SCHEMA_VERSION = "stage6b_controlled_realization.v1"
STAGE6B_STATUS = "READY_FOR_REAL_MODEL_SMOKE"
STAGE6B_OUTPUT = "artifacts/stage6b_controlled_realization_v1_candidate"
STAGE6B_GENERATED_AT = "2026-08-12T00:00:00+08:00"
PRESENTATION_POLICY_VERSION = "stage6b_presentation_policy_v1_candidate"

ProductType = Literal["all", "daily_review", "forward_attention", "metric_review"]


class ResolvedPresentationScope(BaseModel):
    """Human-readable presentation geometry traced to frozen scope sources."""

    model_config = STRICT

    scope_kind: str
    source_fact_lock_id: str
    source_cell_id: str | None
    display_start_chainage: float | None
    display_end_chainage: float | None
    display_point_chainage: float | None
    alignment_id: str | None
    scope_source: str
    scope_source_object_id: str
    scope_source_hash: str
    resolution_method: str


class TaskAbstentionView(BaseModel):
    """Task-scoped negative capability metadata."""

    model_config = STRICT

    task_abstention_view_id: str
    slice_spec: dict[str, Any]
    abstention_count: int
    counts_by_claim_type: dict[str, int]
    counts_by_reason: dict[str, int]
    records: list[dict[str, Any]]
    view_hash: str


class RealizationUnit(BaseModel):
    """Deterministic presentation unit backed only by member FactLocks."""

    model_config = STRICT

    realization_unit_id: str
    member_fact_lock_ids: list[str]
    member_lock_hashes: list[str]
    claim_type: str
    claim_modality: str
    semantic_interpretation: str
    claim_value: dict[str, Any]
    presentation_scope: ResolvedPresentationScope
    valid_date: str | None
    state_role: str
    required_qualifiers: list[str]
    source_evidence_ids: list[str]
    trace_refs: list[str]
    canonical_render_policy_id: str
    unit_hash: str


class CanonicalFactSentence(BaseModel):
    """Deterministically rendered safe sentence for one RealizationUnit."""

    model_config = STRICT

    canonical_sentence_id: str
    realization_unit_id: str
    member_fact_lock_ids: list[str]
    text: str
    claim_type: str
    modality: str
    numeric_tokens: list[dict[str, Any]]
    unit_tokens: list[str]
    chainage_tokens: list[dict[str, Any]]
    date_tokens: list[str]
    trace_refs: list[str]
    formatter_policy_id: str
    sentence_hash: str


class ProductRealizationContract(BaseModel):
    """Task product rules that constrain planning and composition."""

    model_config = STRICT

    product_type: ProductType
    required_families: list[str]
    optional_families: list[str]
    forbidden_families: list[str]
    allowed_state_roles: list[str]
    section_order: list[str]
    section_claim_type_map: dict[str, list[str]]
    required_unit_policy: str
    contract_hash: str


class RealizationPlanSection(BaseModel):
    """One section in an LLM or fake provider plan."""

    model_config = STRICT

    section_id: str
    ordered_unit_ids: list[str]


class RealizationPlan(BaseModel):
    """LLM-constrained plan; it never contains generated engineering text."""

    model_config = STRICT

    plan_id: str
    pack_id: str
    task_abstention_view_id: str
    product_type: ProductType
    sections: list[RealizationPlanSection]
    omitted_optional_unit_ids: list[str]
    contract_hash: str
    pack_hash: str
    presentation_policy_version: str
    provider_name: str
    plan_hash: str


class ComposedSection(BaseModel):
    """Deterministic final section assembled from canonical sentences."""

    model_config = STRICT

    section_id: str
    sentence_ids: list[str]
    text: str


class ComposedBlock(BaseModel):
    """Atomic deterministic block allowed in composed realization text."""

    model_config = STRICT

    block_id: str
    block_type: Literal["SECTION_HEADING", "CANONICAL_FACT", "INSUFFICIENCY", "CONNECTIVE"]
    source_ids: list[str]
    text: str
    block_hash: str


class ComposedRealization(BaseModel):
    """Final controlled text container produced without LLM rewriting."""

    model_config = STRICT

    composed_realization_id: str
    plan_id: str
    product_type: ProductType
    blocks: list[ComposedBlock]
    sections: list[ComposedSection]
    insufficiency_statements: list[str]
    text: str
    realization_hash: str
