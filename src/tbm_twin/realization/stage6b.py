"""Stage 6B deterministic presentation and controlled planning pipeline."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tbm_twin.realization.evidence_pack import (
    METRIC_REVIEW_PRODUCT_CLAIM_TYPES,
    build_controlled_evidence_pack,
    slice_fact_locks,
)
from tbm_twin.realization.io import read_json, read_jsonl, stable_hash, stable_id
from tbm_twin.realization.models import LockedEngineeringFact, SliceSpec
from tbm_twin.realization.stage6b_models import (
    PRESENTATION_POLICY_VERSION,
    CanonicalFactSentence,
    ComposedBlock,
    ComposedRealization,
    ComposedSection,
    ProductRealizationContract,
    RealizationPlan,
    RealizationPlanSection,
    RealizationUnit,
    ResolvedPresentationScope,
    TaskAbstentionView,
)

GEOLOGICAL_CLAIM_TYPES = {
    "FORECAST_GEOLOGICAL_CONDITION",
    "OBSERVED_GEOLOGICAL_CONDITION",
}
ATTENTION_CLAIM_TYPES = {
    "OPERATIONAL_RESPONSE_ATTENTION",
    "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
    "COUPLED_ATTENTION_REVIEW",
    "FORWARD_GEOLOGICAL_ATTENTION",
}

GEOLOGICAL_FORMATTER_POLICIES = {
    "anomaly_level": "source_recorded_anomaly_level",
    "block_fall_or_collapse": "source_reported_block_fall_or_collapse_attention",
    "design_surrounding_rock_grade": "attribute_specific_label",
    "excavated_face_state": "attribute_specific_label",
    "face_state": "attribute_specific_label",
    "form_water_status": "attribute_specific_label",
    "geological_conclusion": "source_recorded_geological_conclusion",
    "geological_description": "source_recorded_geological_description",
    "joint_aperture": "attribute_specific_label",
    "joint_development": "attribute_specific_label",
    "joint_extension": "attribute_specific_label",
    "joint_roughness": "attribute_specific_label",
    "joint_spacing": "attribute_specific_label",
    "karst_development": "attribute_specific_label",
    "lithology": "attribute_specific_label",
    "narrative_water_observation": "source_recorded_water_observation",
    "risk_hint": "source_reported_risk_hint",
    "rock_mass_state": "attribute_specific_label",
    "rock_strength": "attribute_specific_label",
    "stability": "attribute_specific_label",
    "suggested_grade": "source_recorded_suggested_grade",
    "suggested_surrounding_rock_grade": "attribute_specific_label",
    "water_type": "attribute_specific_label",
    "weathering": "attribute_specific_label",
}

GEOLOGICAL_ATTRIBUTE_LABELS = {
    "design_surrounding_rock_grade": "记录的设计围岩等级",
    "excavated_face_state": "毛开挖面状态",
    "face_state": "掌子面状态",
    "form_water_status": "表单涌水状态",
    "joint_aperture": "节理张开性记录",
    "joint_development": "节理裂隙发育记录",
    "joint_extension": "节理延伸性记录",
    "joint_roughness": "节理粗糙度记录",
    "joint_spacing": "节理间距记录",
    "karst_development": "岩溶发育程度",
    "lithology": "岩性",
    "rock_mass_state": "岩体状态",
    "rock_strength": "岩石强度记录",
    "stability": "稳定性记录",
    "suggested_surrounding_rock_grade": "建议围岩等级",
    "water_type": "涌水类型",
    "weathering": "风化程度",
}

INSUFFICIENCY_STATEMENTS = {
    "UNKNOWN_SOURCE_VALUE": "来源存在但目标属性值未形成可表达事实, 不作补充推断。",
    "REQUIRED_METRIC_UNAVAILABLE": "该指标在当前状态下不可用, 不以 0 或正常状态替代。",
    "REQUIRED_EPISTEMIC_STATUS_MISSING": "缺少满足所需认识状态的证据, 不作事实化表达。",
    "CONTEXT_ONLY_ROLE": "当前证据仅具上下文角色, 不作为该任务的事实判断依据。",
    "STATE_ROLE_NOT_ALLOWED": "当前状态角色不满足该类 Claim 的表达约束。",
}

SECTION_TITLES = {
    "geological_forecast": "地质预报事实",
    "geological_observed": "地质观测事实",
    "operational_attention": "施工响应关注度",
    "geological_attention": "地质证据关注度",
    "coupled_attention": "耦合关注度",
    "forward_attention": "前方关注度",
    "insufficiency": "证据不足边界",
}

CHAINAGE_MIN = 1_000_000.0
CHAINAGE_MAX = 1_100_000.0
CHAINAGE_CANDIDATE_MIN = 100_000.0
CHAINAGE_CANDIDATE_MAX = 9_999_999.9


class PresentationScopeResolver:
    """Resolve display chainage without changing frozen FactLocks."""

    def __init__(self, construction_cells: list[dict[str, Any]]) -> None:
        self.cells = {str(row["cell_id"]): row for row in construction_cells}

    def resolve(self, lock: LockedEngineeringFact) -> ResolvedPresentationScope:
        scope = lock.spatial_scope
        kind = str(scope.get("scope_kind"))
        if kind == "LOCATED_INTERVAL":
            start = _as_float(scope.get("start_chainage"))
            end = _as_float(scope.get("end_chainage"))
            source_payload = {
                "fact_lock_id": lock.fact_lock_id,
                "spatial_scope": scope,
            }
            return ResolvedPresentationScope(
                scope_kind="LOCATED_INTERVAL",
                source_fact_lock_id=lock.fact_lock_id,
                source_cell_id=lock.cell_id,
                display_start_chainage=start,
                display_end_chainage=end,
                display_point_chainage=None,
                alignment_id=None,
                scope_source="FACT_LOCK_SPATIAL_SCOPE",
                scope_source_object_id=lock.fact_lock_id,
                scope_source_hash=stable_hash(source_payload),
                resolution_method="USE_FROZEN_FACT_LOCK_INTERVAL",
            )
        if kind == "LOCATED_POINT":
            point = _as_float(scope.get("point_chainage"))
            source_payload = {
                "fact_lock_id": lock.fact_lock_id,
                "spatial_scope": scope,
            }
            return ResolvedPresentationScope(
                scope_kind="LOCATED_POINT",
                source_fact_lock_id=lock.fact_lock_id,
                source_cell_id=lock.cell_id,
                display_start_chainage=None,
                display_end_chainage=None,
                display_point_chainage=point,
                alignment_id=None,
                scope_source="FACT_LOCK_SPATIAL_SCOPE",
                scope_source_object_id=lock.fact_lock_id,
                scope_source_hash=stable_hash(source_payload),
                resolution_method="USE_FROZEN_FACT_LOCK_POINT",
            )
        if kind == "CELL":
            cell_id = str(scope.get("cell_id") or lock.cell_id or "")
            cell = self.cells.get(cell_id)
            if not cell:
                msg = f"missing ConstructionStateCell for {cell_id}"
                raise KeyError(msg)
            return ResolvedPresentationScope(
                scope_kind="CELL_INTERVAL",
                source_fact_lock_id=lock.fact_lock_id,
                source_cell_id=cell_id,
                display_start_chainage=_as_float(cell["spatial_start"]),
                display_end_chainage=_as_float(cell["spatial_end"]),
                display_point_chainage=None,
                alignment_id=str(cell["alignment_id"]),
                scope_source="FROZEN_STAGE3A_CONSTRUCTION_STATE_CELL",
                scope_source_object_id=cell_id,
                scope_source_hash=stable_hash(cell),
                resolution_method="RESOLVE_CELL_GEOMETRY_FROM_FROZEN_STAGE3A",
            )
        msg = f"unsupported presentation scope kind: {kind}"
        raise ValueError(msg)


def build_task_abstention_view(
    abstentions: list[dict[str, Any]], slice_spec: SliceSpec
) -> TaskAbstentionView:
    """Build task-scoped abstention metadata using Stage6A slicing semantics."""

    selected = [row for row in abstentions if _abstention_matches_slice(row, slice_spec)]
    safe_records = [
        {
            "abstention_id": row["abstention_id"],
            "valid_date": row.get("valid_date"),
            "cell_id": row.get("cell_id"),
            "state_role": row.get("state_role"),
            "claim_type": row.get("claim_type"),
            "abstention_reason": row.get("abstention_reason"),
            "failed_rules": list(row.get("failed_rules", [])),
            "bitemporal_version_id": row.get("bitemporal_version_id"),
            "daily_state_id": row.get("daily_state_id"),
        }
        for row in sorted(selected, key=lambda item: str(item["abstention_id"]))
    ]
    payload = {
        "slice_spec": slice_spec.model_dump(mode="json"),
        "records": safe_records,
    }
    return TaskAbstentionView(
        task_abstention_view_id=stable_id("task_abstention_view", payload),
        slice_spec=slice_spec.model_dump(mode="json"),
        abstention_count=len(safe_records),
        counts_by_claim_type=dict(Counter(str(row["claim_type"]) for row in safe_records)),
        counts_by_reason=dict(Counter(str(row["abstention_reason"]) for row in safe_records)),
        records=safe_records,
        view_hash=stable_hash(payload),
    )


def build_realization_units(
    locks: list[LockedEngineeringFact],
    resolver: PresentationScopeResolver,
) -> list[RealizationUnit]:
    """Build exact deterministic units; metrics intentionally do not cross cell boundaries."""

    grouped: dict[str, list[LockedEngineeringFact]] = defaultdict(list)
    scopes = {lock.fact_lock_id: resolver.resolve(lock) for lock in locks}
    for lock in locks:
        key_payload = _grouping_key(lock, scopes[lock.fact_lock_id])
        grouped[stable_hash(key_payload)].append(lock)

    units = []
    for _, members in sorted(grouped.items()):
        sorted_members = sorted(members, key=lambda item: item.fact_lock_id)
        first = sorted_members[0]
        scope = scopes[first.fact_lock_id]
        source_evidence_ids = sorted(
            {
                str(first.claim_value.get("source_evidence_id"))
                for first in sorted_members
                if first.claim_value.get("source_evidence_id")
            }
        )
        trace_refs = sorted({trace for lock in sorted_members for trace in lock.trace_refs})
        payload = {
            "member_fact_lock_ids": [lock.fact_lock_id for lock in sorted_members],
            "member_lock_hashes": [lock.lock_hash for lock in sorted_members],
            "claim_type": first.claim_type,
            "claim_modality": first.claim_modality,
            "semantic_interpretation": first.semantic_interpretation,
            "claim_value": first.claim_value,
            "presentation_scope": scope.model_dump(mode="json"),
            "valid_date": first.valid_date,
            "state_role": first.state_role,
            "required_qualifiers": sorted(first.required_qualifiers),
            "source_evidence_ids": source_evidence_ids,
            "trace_refs": trace_refs,
            "canonical_render_policy_id": _formatter_policy_id(first),
        }
        units.append(
            RealizationUnit(
                realization_unit_id=stable_id("realization_unit", payload),
                member_fact_lock_ids=[lock.fact_lock_id for lock in sorted_members],
                member_lock_hashes=[lock.lock_hash for lock in sorted_members],
                claim_type=first.claim_type,
                claim_modality=first.claim_modality,
                semantic_interpretation=first.semantic_interpretation,
                claim_value=first.claim_value,
                presentation_scope=scope,
                valid_date=first.valid_date,
                state_role=first.state_role,
                required_qualifiers=sorted(first.required_qualifiers),
                source_evidence_ids=source_evidence_ids,
                trace_refs=trace_refs,
                canonical_render_policy_id=_formatter_policy_id(first),
                unit_hash=stable_hash(payload),
            )
        )
    return sorted(units, key=lambda item: item.realization_unit_id)


def build_canonical_sentence(unit: RealizationUnit) -> CanonicalFactSentence:
    """Render one deterministic, non-LLM canonical sentence."""

    text, numeric_tokens = _render_unit_text(unit)
    chainage_tokens = _chainage_tokens(unit.presentation_scope)
    payload = {
        "realization_unit_id": unit.realization_unit_id,
        "member_fact_lock_ids": unit.member_fact_lock_ids,
        "text": text,
        "claim_type": unit.claim_type,
        "modality": unit.claim_modality,
        "numeric_tokens": numeric_tokens,
        "unit_tokens": [],
        "chainage_tokens": chainage_tokens,
        "date_tokens": [unit.valid_date] if unit.valid_date else [],
        "trace_refs": unit.trace_refs,
        "formatter_policy_id": unit.canonical_render_policy_id,
    }
    return CanonicalFactSentence(
        canonical_sentence_id=stable_id("canonical_sentence", payload),
        realization_unit_id=unit.realization_unit_id,
        member_fact_lock_ids=unit.member_fact_lock_ids,
        text=text,
        claim_type=unit.claim_type,
        modality=unit.claim_modality,
        numeric_tokens=numeric_tokens,
        unit_tokens=[],
        chainage_tokens=chainage_tokens,
        date_tokens=[unit.valid_date] if unit.valid_date else [],
        trace_refs=unit.trace_refs,
        formatter_policy_id=unit.canonical_render_policy_id,
        sentence_hash=stable_hash(payload),
    )


def build_product_contract(product_type: str) -> ProductRealizationContract:
    """Return deterministic product realization constraints."""

    if product_type == "daily_review":
        typed_product_type = "daily_review"
        required_families: list[str] = [
            "FORECAST_GEOLOGICAL_CONDITION",
            "OBSERVED_GEOLOGICAL_CONDITION",
            "OPERATIONAL_RESPONSE_ATTENTION",
            "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
            "COUPLED_ATTENTION_REVIEW",
        ]
        optional_families: list[str] = []
        forbidden_families = ["FORWARD_GEOLOGICAL_ATTENTION"]
        allowed_state_roles = ["DAILY_REVIEW_CELL"]
        section_order = [
            "geological_observed",
            "geological_forecast",
            "operational_attention",
            "geological_attention",
            "coupled_attention",
            "insufficiency",
        ]
    elif product_type == "forward_attention":
        typed_product_type = "forward_attention"
        required_families = [
            "FORECAST_GEOLOGICAL_CONDITION",
            "FORWARD_GEOLOGICAL_ATTENTION",
        ]
        optional_families = []
        forbidden_families = [
            "OBSERVED_GEOLOGICAL_CONDITION",
            "OPERATIONAL_RESPONSE_ATTENTION",
            "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
            "COUPLED_ATTENTION_REVIEW",
        ]
        allowed_state_roles = ["FORWARD_ATTENTION_CELL"]
        section_order = [
            "geological_forecast",
            "forward_attention",
            "insufficiency",
        ]
    elif product_type == "metric_review":
        typed_product_type = "metric_review"
        required_families = sorted(METRIC_REVIEW_PRODUCT_CLAIM_TYPES)
        optional_families = []
        forbidden_families = [
            "FORECAST_GEOLOGICAL_CONDITION",
            "OBSERVED_GEOLOGICAL_CONDITION",
        ]
        allowed_state_roles = ["DAILY_REVIEW_CELL", "FORWARD_ATTENTION_CELL"]
        section_order = [
            "operational_attention",
            "geological_attention",
            "coupled_attention",
            "forward_attention",
            "insufficiency",
        ]
    else:
        typed_product_type = "all"
        required_families = [
            "FORECAST_GEOLOGICAL_CONDITION",
            "OBSERVED_GEOLOGICAL_CONDITION",
            *sorted(METRIC_REVIEW_PRODUCT_CLAIM_TYPES),
        ]
        optional_families = []
        forbidden_families = []
        allowed_state_roles = ["DAILY_REVIEW_CELL", "FORWARD_ATTENTION_CELL"]
        section_order = [
            "geological_observed",
            "geological_forecast",
            "operational_attention",
            "geological_attention",
            "coupled_attention",
            "forward_attention",
            "insufficiency",
        ]
    section_claim_type_map = {
        "geological_forecast": ["FORECAST_GEOLOGICAL_CONDITION"],
        "geological_observed": ["OBSERVED_GEOLOGICAL_CONDITION"],
        "operational_attention": ["OPERATIONAL_RESPONSE_ATTENTION"],
        "geological_attention": ["GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW"],
        "coupled_attention": ["COUPLED_ATTENTION_REVIEW"],
        "forward_attention": ["FORWARD_GEOLOGICAL_ATTENTION"],
        "insufficiency": [],
    }
    required_unit_policy = "ALL_TASK_UNITS_REQUIRED"
    contract_payload = {
        "product_type": typed_product_type,
        "required_families": required_families,
        "optional_families": optional_families,
        "forbidden_families": forbidden_families,
        "allowed_state_roles": allowed_state_roles,
        "section_order": section_order,
        "section_claim_type_map": section_claim_type_map,
        "required_unit_policy": required_unit_policy,
    }
    return ProductRealizationContract(
        product_type=typed_product_type,  # type: ignore[arg-type]
        required_families=required_families,
        optional_families=optional_families,
        forbidden_families=forbidden_families,
        allowed_state_roles=allowed_state_roles,
        section_order=section_order,
        section_claim_type_map=section_claim_type_map,
        required_unit_policy=required_unit_policy,
        contract_hash=stable_hash(contract_payload),
    )


class DeterministicFakeProvider:
    """Network-free provider that returns a legal plan for validator tests."""

    provider_name = "deterministic_fake_provider"

    def build_plan(
        self,
        pack_id: str,
        pack_hash: str,
        task_view: TaskAbstentionView,
        units: list[RealizationUnit],
        contract: ProductRealizationContract,
    ) -> RealizationPlan:
        sections = []
        for section_id in contract.section_order:
            claim_types = set(contract.section_claim_type_map[section_id])
            section_units = [
                unit.realization_unit_id for unit in units if unit.claim_type in claim_types
            ]
            if section_units:
                sections.append(
                    RealizationPlanSection(
                        section_id=section_id,
                        ordered_unit_ids=sorted(section_units),
                    )
                )
        payload = {
            "pack_id": pack_id,
            "task_abstention_view_id": task_view.task_abstention_view_id,
            "product_type": contract.product_type,
            "sections": [section.model_dump(mode="json") for section in sections],
            "omitted_optional_unit_ids": [],
            "contract_hash": contract.contract_hash,
            "pack_hash": pack_hash,
            "presentation_policy_version": PRESENTATION_POLICY_VERSION,
            "provider_name": self.provider_name,
        }
        return RealizationPlan(
            plan_id=stable_id("realization_plan", payload),
            pack_id=pack_id,
            task_abstention_view_id=task_view.task_abstention_view_id,
            product_type=contract.product_type,
            sections=sections,
            omitted_optional_unit_ids=[],
            contract_hash=contract.contract_hash,
            pack_hash=pack_hash,
            presentation_policy_version=PRESENTATION_POLICY_VERSION,
            provider_name=self.provider_name,
            plan_hash=stable_hash(payload),
        )


def validate_plan(
    plan: RealizationPlan,
    units: list[RealizationUnit],
    contract: ProductRealizationContract,
    pack_id: str,
    pack_hash: str,
    task_abstention_view_id: str,
) -> list[str]:
    """Reject plans that try to route unknown or forbidden units."""

    issues: list[str] = []
    units_by_id = {unit.realization_unit_id: unit for unit in units}
    seen: list[str] = []
    if plan.pack_id != pack_id:
        issues.append("PACK_ID_MISMATCH")
    if plan.product_type != contract.product_type:
        issues.append("PRODUCT_TYPE_MISMATCH")
    if plan.task_abstention_view_id != task_abstention_view_id:
        issues.append("TASK_ABSTENTION_VIEW_MISMATCH")
    if plan.pack_hash != pack_hash:
        issues.append("PACK_HASH_MISMATCH")
    if plan.contract_hash != contract.contract_hash:
        issues.append("CONTRACT_HASH_MISMATCH")
    if plan.presentation_policy_version != PRESENTATION_POLICY_VERSION:
        issues.append("PRESENTATION_POLICY_MISMATCH")
    expected_plan_hash = stable_hash(
        {
            "pack_id": plan.pack_id,
            "task_abstention_view_id": plan.task_abstention_view_id,
            "product_type": plan.product_type,
            "sections": [section.model_dump(mode="json") for section in plan.sections],
            "omitted_optional_unit_ids": plan.omitted_optional_unit_ids,
            "contract_hash": plan.contract_hash,
            "pack_hash": plan.pack_hash,
            "presentation_policy_version": plan.presentation_policy_version,
            "provider_name": plan.provider_name,
        }
    )
    if plan.plan_hash != expected_plan_hash:
        issues.append("PLAN_HASH_MISMATCH")
    allowed_sections = set(contract.section_order)
    section_ids = [section.section_id for section in plan.sections]
    if len(section_ids) != len(set(section_ids)):
        issues.append("DUPLICATE_SECTION")
    section_positions = {
        section_id: index for index, section_id in enumerate(contract.section_order)
    }
    known_section_positions = [
        section_positions[section_id]
        for section_id in section_ids
        if section_id in section_positions
    ]
    if known_section_positions != sorted(known_section_positions):
        issues.append("INVALID_SECTION_ORDER")
    for section in plan.sections:
        if section.section_id not in allowed_sections:
            issues.append("INVALID_SECTION")
        allowed_claims = set(contract.section_claim_type_map.get(section.section_id, []))
        for unit_id in section.ordered_unit_ids:
            if unit_id not in units_by_id:
                issues.append("UNKNOWN_UNIT")
                continue
            unit = units_by_id[unit_id]
            if unit.claim_type in contract.forbidden_families:
                issues.append("FORBIDDEN_FAMILY")
            if unit.claim_type not in allowed_claims:
                issues.append("FORBIDDEN_SECTION_ASSIGNMENT")
            seen.append(unit_id)
    if len(seen) != len(set(seen)):
        issues.append("DUPLICATE_UNIT_REFERENCE")
    selected_ids = set(seen)
    omitted_ids = set(plan.omitted_optional_unit_ids)
    if selected_ids & omitted_ids:
        issues.append("SELECTED_AND_OMITTED_UNIT")
    if omitted_ids - set(units_by_id):
        issues.append("UNKNOWN_OMITTED_UNIT")
    optional_families = set(contract.optional_families)
    for unit_id in omitted_ids & set(units_by_id):
        if units_by_id[unit_id].claim_type not in optional_families:
            issues.append("ILLEGAL_OPTIONAL_OMISSION")
    if units_by_id and not selected_ids:
        issues.append("ALL_UNITS_OMITTED")
    missing = set(units_by_id) - selected_ids - omitted_ids
    if missing and contract.required_unit_policy == "ALL_TASK_UNITS_REQUIRED":
        issues.append("REQUIRED_UNIT_OMISSION")
    return sorted(set(issues))


def compose_realization(
    plan: RealizationPlan,
    sentences_by_unit: dict[str, CanonicalFactSentence],
    task_view: TaskAbstentionView,
    contract: ProductRealizationContract,
) -> ComposedRealization:
    """Compose final text from frozen canonical sentences only."""

    composed_sections = []
    blocks: list[ComposedBlock] = []
    for section in plan.sections:
        sentence_ids = []
        lines = []
        heading = f"## {SECTION_TITLES.get(section.section_id, section.section_id)}"
        blocks.append(_composed_block("SECTION_HEADING", [section.section_id], heading))
        for unit_id in section.ordered_unit_ids:
            sentence = sentences_by_unit[unit_id]
            sentence_ids.append(sentence.canonical_sentence_id)
            lines.append(sentence.text)
            blocks.append(
                _composed_block(
                    "CANONICAL_FACT",
                    [sentence.canonical_sentence_id, unit_id],
                    sentence.text,
                )
            )
        composed_sections.append(
            ComposedSection(
                section_id=section.section_id,
                sentence_ids=sentence_ids,
                text="\n".join(lines),
            )
        )
    insufficiency = _insufficiency_statements(task_view)
    if insufficiency:
        heading = f"## {SECTION_TITLES['insufficiency']}"
        blocks.append(_composed_block("SECTION_HEADING", ["insufficiency"], heading))
        for statement in insufficiency:
            blocks.append(
                _composed_block("INSUFFICIENCY", [task_view.task_abstention_view_id], statement)
            )
    text = "\n\n".join(block.text for block in blocks)
    payload = {
        "plan_id": plan.plan_id,
        "product_type": contract.product_type,
        "blocks": [block.model_dump(mode="json") for block in blocks],
        "sections": [section.model_dump(mode="json") for section in composed_sections],
        "insufficiency_statements": insufficiency,
        "text": text,
    }
    return ComposedRealization(
        composed_realization_id=stable_id("composed_realization", payload),
        plan_id=plan.plan_id,
        product_type=contract.product_type,
        blocks=blocks,
        sections=composed_sections,
        insufficiency_statements=insufficiency,
        text=text,
        realization_hash=stable_hash(payload),
    )


def audit_post_realization(
    composed: ComposedRealization,
    sentences: list[CanonicalFactSentence],
) -> list[str]:
    """Audit final text for numeric, chainage and modality drift."""

    issues: list[str] = []
    sentence_ids = {sentence.canonical_sentence_id for sentence in sentences}
    canonical_sentence_texts = {sentence.text for sentence in sentences}
    reconstructed_text = "\n\n".join(block.text for block in composed.blocks)
    if composed.text != reconstructed_text:
        issues.append("UNAUTHORIZED_ENGINEERING_SENTENCE")
    extra_text = composed.text.replace(reconstructed_text, "", 1)
    for block in composed.blocks:
        if block.block_type == "CANONICAL_FACT":
            if not set(block.source_ids) & sentence_ids:
                issues.append("TRACE_FAILURE")
            if block.text not in canonical_sentence_texts:
                issues.append("UNAUTHORIZED_ENGINEERING_SENTENCE")
    canonical_text = "\n".join(
        block.text for block in composed.blocks if block.block_type == "CANONICAL_FACT"
    )
    audited_fact_text = "\n".join([canonical_text, extra_text])
    engineering_number_issues = audit_engineering_numbers(audited_fact_text, sentences)
    issues.extend(engineering_number_issues)
    chainage_issues = audit_chainage_tokens(audited_fact_text, sentences)
    issues.extend(chainage_issues)
    drift_issues = audit_canonical_drift(sentences)
    issues.extend(drift_issues)
    if "风险概率" in composed.text or "发生概率" in composed.text or "灾害概率" in composed.text:
        issues.append("ATTENTION_PROMOTED_TO_PROBABILITY")
    if (
        "地质导致" in composed.text
        or "由地质原因造成" in composed.text
        or re.search(r"地质.{0,12}导致.{0,12}(推力|扭矩|贯入度|转速|响应)", composed.text)
    ):
        issues.append("MECHANICAL_RESPONSE_PROMOTED_TO_GEOLOGICAL_CAUSE")
    if "预报资料" in composed.text and (
        "实际揭露为" in composed.text
        or "实际揭露:" in composed.text
        or "实际揭露结论为" in composed.text
    ):
        issues.append("FORECAST_PROMOTED_TO_OBSERVED")
    if any(
        ("UNKNOWN" in block.text or "未发现异常" in block.text) and "正常" in block.text
        for block in composed.blocks
        if block.block_type in {"CANONICAL_FACT", "CONNECTIVE"}
    ) or (("UNKNOWN" in extra_text or "未发现异常" in extra_text) and "正常" in extra_text):
        issues.append("UNKNOWN_PROMOTED_TO_NORMAL")
    return sorted(set(issues))


def _composed_block(block_type: str, source_ids: list[str], text: str) -> ComposedBlock:
    payload = {
        "block_type": block_type,
        "source_ids": source_ids,
        "text": text,
    }
    return ComposedBlock(
        block_id=stable_id("composed_block", payload),
        block_type=block_type,  # type: ignore[arg-type]
        source_ids=source_ids,
        text=text,
        block_hash=stable_hash(payload),
    )


def build_task_bundle(
    locks: list[LockedEngineeringFact],
    abstentions: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    slice_spec: SliceSpec,
) -> dict[str, Any]:
    """Build one deterministic Stage6B task bundle."""

    selected_locks = slice_fact_locks(locks, slice_spec)
    pack = build_controlled_evidence_pack(
        locks,
        abstentions,
        task_context="stage6b_task_pack",
        slice_spec=slice_spec,
    )
    resolver = PresentationScopeResolver(cells)
    units = build_realization_units(selected_locks, resolver)
    sentences = [build_canonical_sentence(unit) for unit in units]
    sentences_by_unit = {sentence.realization_unit_id: sentence for sentence in sentences}
    task_view = build_task_abstention_view(abstentions, slice_spec)
    contract = build_product_contract(slice_spec.product_type)
    plan = DeterministicFakeProvider().build_plan(
        pack.pack_id,
        pack.pack_hash,
        task_view,
        units,
        contract,
    )
    plan_issues = validate_plan(
        plan,
        units,
        contract,
        pack.pack_id,
        pack.pack_hash,
        task_view.task_abstention_view_id,
    )
    composed = compose_realization(plan, sentences_by_unit, task_view, contract)
    post_issues = audit_post_realization(composed, sentences)
    return {
        "pack": pack,
        "task_view": task_view,
        "contract": contract,
        "units": units,
        "sentences": sentences,
        "plan": plan,
        "plan_issues": plan_issues,
        "composed": composed,
        "post_issues": post_issues,
    }


def load_stage6b_inputs(repo_root: Path) -> dict[str, Any]:
    """Load frozen upstream inputs without modifying them."""

    return {
        "stage6a_method": read_json(
            repo_root / "artifacts/stage6a_fact_lock_evidence_pack_v1/method_version.json"
        ),
        "stage6a_locks": [
            LockedEngineeringFact(**row)
            for row in read_jsonl(
                repo_root / "artifacts/stage6a_fact_lock_evidence_pack_v1/fact_locks.jsonl"
            )
        ],
        "stage5b_abstentions": read_jsonl(
            repo_root / "artifacts/stage5b_deterministic_claim_builder_v1/claim_abstentions.jsonl"
        ),
        "stage3a_cells": read_jsonl(
            repo_root
            / "artifacts/stage3a_initial_epistemic_state_v1_1/construction_state_cells.jsonl"
        ),
    }


def _grouping_key(lock: LockedEngineeringFact, scope: ResolvedPresentationScope) -> dict[str, Any]:
    if lock.claim_type in ATTENTION_CLAIM_TYPES:
        return {
            "grouping_policy": "metric_one_cell_fact_lock_one_unit",
            "fact_lock_id": lock.fact_lock_id,
            "lock_hash": lock.lock_hash,
        }
    value = lock.claim_value
    return {
        "grouping_policy": "exact_geological_semantic_dedup",
        "valid_date": lock.valid_date,
        "state_role": lock.state_role,
        "claim_type": lock.claim_type,
        "claim_modality": lock.claim_modality,
        "source_evidence_id": value.get("source_evidence_id"),
        "attribute_name": value.get("attribute_name"),
        "normalized_value": value.get("normalized_value"),
        "attribute_dimension": value.get("attribute_dimension"),
        "authoritative_evidence_scope": _semantic_scope_payload(scope),
        "required_qualifiers": sorted(lock.required_qualifiers),
        "allowed_rendering_semantics": lock.allowed_rendering_semantics,
        "prohibited_transformations": lock.prohibited_transformations,
    }


def _semantic_scope_payload(scope: ResolvedPresentationScope) -> dict[str, Any]:
    return {
        "scope_kind": scope.scope_kind,
        "display_start_chainage": scope.display_start_chainage,
        "display_end_chainage": scope.display_end_chainage,
        "display_point_chainage": scope.display_point_chainage,
        "alignment_id": scope.alignment_id,
    }


def _abstention_matches_slice(row: dict[str, Any], slice_spec: SliceSpec) -> bool:
    if not _matches_product_type_for_abstention(row, slice_spec.product_type):
        return False
    if slice_spec.valid_date and row.get("valid_date") != slice_spec.valid_date:
        return False
    if slice_spec.state_role and row.get("state_role") != slice_spec.state_role:
        return False
    if slice_spec.cell_id and row.get("cell_id") != slice_spec.cell_id:
        return False
    return not (slice_spec.claim_type and row.get("claim_type") != slice_spec.claim_type)


def _matches_product_type_for_abstention(row: dict[str, Any], product_type: str) -> bool:
    if product_type == "all":
        return True
    if product_type == "daily_review":
        return row.get("state_role") == "DAILY_REVIEW_CELL"
    if product_type == "forward_attention":
        return row.get("state_role") == "FORWARD_ATTENTION_CELL"
    if product_type == "metric_review":
        return row.get("claim_type") in METRIC_REVIEW_PRODUCT_CLAIM_TYPES
    msg = f"unsupported product_type: {product_type}"
    raise ValueError(msg)


def _formatter_policy_id(lock: LockedEngineeringFact) -> str:
    if lock.claim_type in ATTENTION_CLAIM_TYPES:
        metric_name = str(lock.claim_value.get("metric_name"))
        return f"metric_{metric_name.lower()}_fixed_3dp_nonprobabilistic"
    attribute = str(lock.claim_value.get("attribute_name", ""))
    return f"geology_{GEOLOGICAL_FORMATTER_POLICIES.get(attribute, 'safe_passthrough')}"


def _render_unit_text(unit: RealizationUnit) -> tuple[str, list[dict[str, Any]]]:
    scope_text = _scope_text(unit.presentation_scope)
    date_text = f"{unit.valid_date}, " if unit.valid_date else ""
    if unit.claim_type in ATTENTION_CLAIM_TYPES:
        return _render_metric_sentence(unit, date_text, scope_text)
    value = str(unit.claim_value.get("normalized_value", ""))
    attribute = str(unit.claim_value.get("attribute_name", ""))
    if unit.claim_type == "FORECAST_GEOLOGICAL_CONDITION":
        prefix = f"{date_text}针对{scope_text}, 既有地质预报资料中"
        suffix = "该表述保持为预报来源记录, 不作为实际揭露结论。"
    else:
        prefix = f"{date_text}针对{scope_text}, 地质观测资料中"
        suffix = "该表述保持为观测来源记录。"
    if attribute == "risk_hint":
        text = f"{prefix}风险提示字段记录为: {value}。{suffix}"
    elif attribute == "anomaly_level":
        text = f"{prefix}异常等级字段记录为: {value}。{suffix}"
    elif attribute == "block_fall_or_collapse":
        text = f"{prefix}掉块或坍塌相关字段记录为: {value}。{suffix}"
    elif attribute == "geological_conclusion":
        text = f"{prefix}地质结论字段记录为: {value}。{suffix}"
    elif attribute == "suggested_grade":
        text = f"{prefix}建议围岩等级字段记录为: {value}。{suffix}"
    elif attribute == "geological_description":
        text = f"{prefix}地质描述字段记录为: {value}。{suffix}"
    elif attribute == "narrative_water_observation":
        text = f"{prefix}水文描述字段记录为: {value}。{suffix}"
    else:
        label = GEOLOGICAL_ATTRIBUTE_LABELS.get(attribute, attribute)
        text = f"{prefix}{label}记录为: {value}。{suffix}"
    return text, _source_value_numeric_tokens(value)


def _render_metric_sentence(
    unit: RealizationUnit, date_text: str, scope_text: str
) -> tuple[str, list[dict[str, Any]]]:
    raw = float(unit.claim_value["metric_value"])
    display = f"{raw:.3f}"
    metric = str(unit.claim_value["metric_name"])
    token = {
        "token_type": "metric_value",
        "raw_value": raw,
        "display_value": display,
        "numeric_format_policy": "fixed_3_decimal_display_preserve_raw_value",
    }
    if unit.claim_type == "OPERATIONAL_RESPONSE_ATTENTION":
        text = (
            f"{date_text}{scope_text}施工响应关注度 RAI 为 {display}。"
            "该值为非概率关注指标, 不表示地质原因。"
        )
    elif unit.claim_type == "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW":
        text = f"{date_text}{scope_text}地质证据关注度 GRS 为 {display}。该值为非概率关注指标。"
    elif unit.claim_type == "COUPLED_ATTENTION_REVIEW":
        text = (
            f"{date_text}{scope_text} GRCI 为 {display}, "
            "表示非概率性的地质证据—施工响应耦合关注程度。"
        )
    else:
        text = (
            f"{date_text}{scope_text}前方地质证据关注度 {metric} 为 {display}, "
            "该值保持 ahead-of-face source-constrained 语义。"
        )
    return text, [token]


def _scope_text(scope: ResolvedPresentationScope) -> str:
    if scope.display_point_chainage is not None:
        return f"里程 {scope.display_point_chainage:.1f}"
    if scope.display_start_chainage is not None and scope.display_end_chainage is not None:
        return f"里程 {scope.display_start_chainage:.1f}-{scope.display_end_chainage:.1f}"
    return "当前任务范围"


def _chainage_tokens(scope: ResolvedPresentationScope) -> list[dict[str, Any]]:
    rows = []
    if scope.display_point_chainage is not None:
        rows.append(
            {
                "token_type": "chainage_point",
                "raw_value": scope.display_point_chainage,
                "display_value": f"{scope.display_point_chainage:.1f}",
                "source": scope.scope_source,
                "source_object_id": scope.scope_source_object_id,
            }
        )
    for label, value in [
        ("chainage_start", scope.display_start_chainage),
        ("chainage_end", scope.display_end_chainage),
    ]:
        if value is not None:
            rows.append(
                {
                    "token_type": label,
                    "raw_value": value,
                    "display_value": f"{value:.1f}",
                    "source": scope.scope_source,
                    "source_object_id": scope.scope_source_object_id,
                }
            )
    return rows


def _insufficiency_statements(task_view: TaskAbstentionView) -> list[str]:
    statements = []
    for reason in sorted(task_view.counts_by_reason):
        template = INSUFFICIENCY_STATEMENTS.get(reason)
        if template:
            statements.append(f"{reason}: {template}")
    return statements


def audit_engineering_numbers(text: str, sentences: list[CanonicalFactSentence]) -> list[str]:
    """Check engineering numeric tokens are authorized by canonical sentences."""

    authorized = _authorized_numeric_values(sentences)
    issues = []
    for number in _engineering_numbers(text):
        if _is_chainage_value(number):
            continue
        if number not in authorized:
            issues.append("UNTRACED_ENGINEERING_NUMBER")
    return issues


def extract_engineering_numbers(text: str) -> list[str]:
    """Extract engineering-relevant numeric tokens from text."""

    return _engineering_numbers(text)


def audit_chainage_tokens(text: str, sentences: list[CanonicalFactSentence]) -> list[str]:
    """Check chainage-like numeric tokens trace to canonical chainage tokens."""

    authorized = _authorized_chainage_values(sentences)
    issues = []
    for number in _engineering_numbers(text):
        if _is_chainage_value(number) and number not in authorized:
            issues.append("UNTRACED_CHAINAGE")
    return issues


def audit_canonical_drift(sentences: list[CanonicalFactSentence]) -> list[str]:
    """Validate canonical tokens remain internally bound to their text."""

    issues = []
    for sentence in sentences:
        for token in sentence.numeric_tokens:
            display = str(token["display_value"])
            if display not in sentence.text:
                issues.append("CANONICAL_NUMERIC_DRIFT")
            if (
                token.get("token_type") == "metric_value"
                and token.get("numeric_format_policy")
                != "fixed_3_decimal_display_preserve_raw_value"
            ):
                issues.append("CANONICAL_NUMERIC_DRIFT")
            if (
                token.get("token_type") == "source_value_number"
                and token.get("numeric_format_policy") != "source_text_numeric_preserved"
            ):
                issues.append("CANONICAL_NUMERIC_DRIFT")
        for token in sentence.chainage_tokens:
            if str(token["display_value"]) not in sentence.text:
                issues.append("CANONICAL_CHAINAGE_DRIFT")
        if sentence.modality == "GEOLOGICAL_FORECAST" and "预报资料" not in sentence.text:
            issues.append("CANONICAL_MODALITY_DRIFT")
        if sentence.modality == "GEOLOGICAL_OBSERVED" and "观测资料" not in sentence.text:
            issues.append("CANONICAL_MODALITY_DRIFT")
        if sentence.modality == "DERIVED_ATTENTION" and "概率" in sentence.text.replace(
            "非概率", ""
        ):
            issues.append("CANONICAL_MODALITY_DRIFT")
    return issues


def _engineering_numbers(text: str) -> list[str]:
    matches = re.finditer(r"(?<![A-Za-z_\d.])-?\d+(?:\.\d+)?(?![A-Za-z_\d.])", text)
    return [match.group(0) for match in matches if _is_engineering_number_match(text, match)]


def _source_value_numeric_tokens(value: str) -> list[dict[str, Any]]:
    return [
        {
            "token_type": "source_value_number",
            "raw_value": number,
            "display_value": number,
            "numeric_format_policy": "source_text_numeric_preserved",
        }
        for number in _engineering_numbers(value)
        if not _is_chainage_value(number)
    ]


def _is_engineering_number_match(text: str, match: re.Match[str]) -> bool:
    line_start = text.rfind("\n", 0, match.start()) + 1
    line_end = text.find("\n", match.end())
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    relative_start = match.start() - line_start
    relative_end = match.end() - line_start
    for date_match in re.finditer(r"\d{4}-\d{1,2}-\d{1,2}", line):
        if date_match.start() <= relative_start and relative_end <= date_match.end():
            return False
    prefix = line[:relative_start].strip()
    suffix = line[relative_end:]
    if prefix in {"", "#", "##", "###", "####"} and re.match(r"[.、]\s", suffix):
        return False
    return not (
        prefix.startswith("#") and not prefix.strip("#").strip() and re.match(r"(\s|[.、])", suffix)
    )


def _authorized_numeric_values(sentences: list[CanonicalFactSentence]) -> set[str]:
    return {
        str(token["display_value"]) for sentence in sentences for token in sentence.numeric_tokens
    }


def _authorized_chainage_values(sentences: list[CanonicalFactSentence]) -> set[str]:
    return {
        str(token["display_value"]) for sentence in sentences for token in sentence.chainage_tokens
    }


def _is_chainage_value(number: str) -> bool:
    try:
        value = abs(float(number))
    except ValueError:
        return False
    return CHAINAGE_CANDIDATE_MIN <= value <= CHAINAGE_CANDIDATE_MAX


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
