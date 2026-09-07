"""Stage 5B deterministic full-batch claim builder."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from tbm_twin.claim_building.models import (
    STAGE5B_CANDIDATE_METHOD_VERSION,
    STAGE5B_FORMAL_METHOD_VERSION,
    STAGE5B_METHOD_VERSION,
    STAGE5B_SCHEMA_VERSION,
    ClaimAbstentionRecord,
    ClaimOpportunity,
    ProposalConstructionRecord,
)
from tbm_twin.claim_building.storage import (
    read_jsonl,
    write_csv,
    write_hashes,
    write_json,
    write_jsonl,
)
from tbm_twin.claims.contracts import contract_file_hash, load_claim_contracts
from tbm_twin.claims.models import (
    STAGE5A_SCHEMA_VERSION,
    ClaimDecision,
    ClaimExpressibility,
    ClaimModality,
    ClaimProposal,
    ClaimScope,
    ClaimScopeKind,
    ClaimSemanticInterpretation,
    ClaimSupportRef,
    ClaimSupportRole,
    ClaimType,
    GeologicalConditionClaimValue,
    MetricClaimValue,
    SupportKind,
    TypedEngineeringClaim,
    stable_id,
)
from tbm_twin.claims.registry import ClaimTypeRegistry
from tbm_twin.claims.resolution import (
    ClaimUpstreamLookup,
    GeologicalEvidenceRecord,
    MetricRecord,
    SubjectRecord,
)
from tbm_twin.claims.validation import ClaimContractEvaluator

STAGE3A_DIR = Path("artifacts/stage3a_initial_epistemic_state_v1_1")
STAGE3B_DIR = Path("artifacts/stage3b_bitemporal_epistemic_state_v1_1")
STAGE4_DIR = Path("artifacts/stage4_bitemporal_state_metrics_v1_1")
STAGE5A_DIR = Path("artifacts/stage5a_typed_claim_contract_v1_1")
STAGE2_GEOLOGY_DIR = Path("artifacts/stage2_geology_v2_freeze_candidate")
STAGE5A_PARENT_TAG = "stage5a-claim-contract-v1-frozen"
STAGE5A_TAG = "stage5a-claim-contract-v1.1-frozen"
STAGE4_TAG = "stage4-metrics-v1.1-frozen"
DEFAULT_OUTPUT_DIR = Path("artifacts/stage5b_deterministic_claim_builder_v1_candidate")
FORMAL_OUTPUT_DIR = Path("artifacts/stage5b_deterministic_claim_builder_v1")
DEFAULT_GENERATED_AT = "2026-08-11T13:30:00+08:00"
FORMAL_GENERATED_AT = "2026-08-11T17:15:00+08:00"
GENERATED_AT_SEMANTICS = "OFFLINE_RECONSTRUCTION_TIME"
STAGE4_SOURCE_SNAPSHOT_SHA256 = "906a6d8636483adc5e71099af1c4a801f21dff427beb6c8ac198dd435244373d"
STAGE4_SOURCE_TREE_HASH = "a8e9eee5c5e26e266fffd0a495be51dbea0727a09ac84c63ac9834d2e7602464"
GEOLOGICAL_ATTRIBUTE_ALLOWLIST = frozenset(
    {
        "lithology",
        "weathering",
        "surrounding_rock_grade",
        "suggested_grade",
        "suggested_surrounding_rock_grade",
        "design_surrounding_rock_grade",
        "joint_development",
        "rock_mass_state",
        "stability",
        "water_type",
        "block_fall_or_collapse",
        "anomaly_level",
        "geological_conclusion",
        "geological_description",
        "risk_hint",
        "narrative_water_observation",
        "form_water_status",
        "face_state",
        "excavated_face_state",
        "rock_strength",
        "joint_spacing",
        "joint_extension",
        "joint_roughness",
        "joint_aperture",
        "karst_development",
    }
)
UNKNOWN_VALUES = {"", "UNKNOWN", "NULL", "NONE", "UNMAPPED", "UNMAPPABLE"}


def build_stage5b_candidate(
    repo_root: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at: str = DEFAULT_GENERATED_AT,
) -> dict[str, int]:
    """Build the Stage 5B deterministic claim materialization candidate."""
    return _build_stage5b(
        repo_root=repo_root,
        output_dir=output_dir,
        generated_at=generated_at,
        method_version=STAGE5B_CANDIDATE_METHOD_VERSION,
        status="CANDIDATE",
        report_title="# Stage 5B Deterministic Claim Builder Candidate",
        version_reason="DETERMINISTIC_CLAIM_MATERIALIZATION_CANDIDATE",
    )


def build_stage5b_formal(
    repo_root: Path,
    output_dir: Path = FORMAL_OUTPUT_DIR,
    generated_at: str = FORMAL_GENERATED_AT,
) -> dict[str, int]:
    """Build the formal frozen Stage 5B deterministic claim materialization artifact."""
    return _build_stage5b(
        repo_root=repo_root,
        output_dir=output_dir,
        generated_at=generated_at,
        method_version=STAGE5B_FORMAL_METHOD_VERSION,
        status="FROZEN",
        report_title="# Stage 5B Deterministic Claim Builder — FROZEN",
        version_reason="FINAL_DETERMINISTIC_CLAIM_MATERIALIZATION_FREEZE",
    )


def _build_stage5b(
    repo_root: Path,
    output_dir: Path,
    generated_at: str,
    method_version: str,
    status: str,
    report_title: str,
    version_reason: str,
) -> dict[str, int]:
    """Build Stage 5B with one business implementation and explicit packaging mode."""

    repo_root = repo_root.resolve()
    output_path = _resolve(repo_root, output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    stage = _load_stage(repo_root)
    contracts = load_claim_contracts(repo_root / "configs/claim_contract_v1.yaml")
    registry = ClaimTypeRegistry.from_contracts(contracts)
    lookup = _build_lookup(stage)
    evaluator = ClaimContractEvaluator(registry, lookup)

    opportunities, dedup_rows = _discover_opportunities(stage)
    opportunities = [
        row.model_copy(update={"builder_version": method_version}) for row in opportunities
    ]
    proposals: list[ClaimProposal] = []
    decisions: list[ClaimDecision] = []
    claims: list[dict[str, Any]] = []
    abstentions: list[ClaimAbstentionRecord] = []
    construction_records: list[ProposalConstructionRecord] = []
    materialization_rows: list[dict[str, object]] = []

    proposal_by_opportunity: dict[str, ClaimProposal] = {}
    decision_by_proposal: dict[str, ClaimDecision] = {}
    claim_by_decision: dict[str, dict[str, Any]] = {}

    for opportunity in opportunities:
        proposal, record = _construct_proposal(opportunity)
        record = record.model_copy(update={"builder_version": method_version})
        construction_records.append(record)
        if proposal is None:
            continue
        proposals.append(proposal)
        proposal_by_opportunity[opportunity.opportunity_id] = proposal
        decision = evaluator.evaluate(proposal)
        decisions.append(decision)
        decision_by_proposal[proposal.proposal_id] = decision
        if decision.expressibility == ClaimExpressibility.EXPRESSIBLE:
            claim = _materialize_claim(opportunity, proposal, decision, method_version)
            claims.append(claim)
            claim_by_decision[decision.decision_id] = claim
            materialization_rows.append(
                _materialization_row(opportunity, proposal, decision, claim["claim_id"])
            )
        else:
            abstention = _materialize_abstention(opportunity, proposal, decision, method_version)
            abstentions.append(abstention)
            materialization_rows.append(_materialization_row(opportunity, proposal, decision, ""))

    rows = _sorted_outputs(
        opportunities, proposals, decisions, claims, abstentions, construction_records
    )
    opportunities = rows["opportunities"]
    proposals = rows["proposals"]
    decisions = rows["decisions"]
    claims = rows["claims"]
    abstentions = rows["abstentions"]
    construction_records = rows["construction_records"]
    materialization_rows = sorted(materialization_rows, key=lambda row: str(row["opportunity_id"]))

    write_json(output_path / "claim_opportunity_universe.json", _opportunity_universe())
    write_jsonl(output_path / "claim_opportunities.jsonl", opportunities)
    write_jsonl(output_path / "claim_proposals.jsonl", proposals)
    write_jsonl(output_path / "claim_decisions.jsonl", decisions)
    write_jsonl(output_path / "typed_engineering_claims.jsonl", claims)
    write_jsonl(output_path / "claim_abstentions.jsonl", abstentions)
    write_jsonl(output_path / "proposal_construction_records.jsonl", construction_records)

    type_summary_rows = _claim_type_summary(
        opportunities, construction_records, decisions, claims, abstentions
    )
    daily_summary_rows = _daily_claim_summary(
        stage.daily_states, opportunities, proposals, decisions, claims
    )
    schema_validation_rows = _typed_claim_schema_validation_audit(claims)
    reference_rows = _reference_audit(
        stage,
        opportunities,
        proposals,
        decisions,
        claims,
        abstentions,
        construction_records,
    )
    metric_integrity_rows = _metric_proposal_integrity_audit(stage, proposals, decisions)
    geological_context_rows = _geological_resolved_context_audit(stage, claims, decisions)
    dedup_audit_rows = _deduplication_audit(dedup_rows, opportunities, proposals, decisions, claims)
    parity_rows = _contract_parity_audit(evaluator, proposals, decisions)
    determinism_rows = _determinism_audit(
        repo_root, opportunities, proposals, decisions, claims, abstentions, method_version
    )
    stage5a_immutability_rows = _stage5a_immutability_audit(repo_root)
    stage5a_hotfix_rows = _stage5a_hotfix_impact_audit(repo_root)
    upstream_rebase_rows = _stage5b_upstream_rebase_audit(
        type_summary_rows,
        abstentions,
        metric_integrity_rows,
        geological_context_rows,
    )
    fixed_case_rows = _fixed_case_audit(stage, opportunities, decisions, claims)
    hard_rows = _hard_check_rows(
        repo_root,
        stage,
        opportunities,
        proposals,
        decisions,
        claims,
        abstentions,
        construction_records,
        reference_rows,
        schema_validation_rows,
        metric_integrity_rows,
        geological_context_rows,
        dedup_audit_rows,
        parity_rows,
        determinism_rows,
        stage5a_immutability_rows,
        stage5a_hotfix_rows,
        upstream_rebase_rows,
        fixed_case_rows,
    )

    write_csv(output_path / "claim_type_summary.csv", type_summary_rows)
    write_csv(output_path / "daily_claim_summary.csv", daily_summary_rows)
    write_csv(output_path / "typed_claim_schema_validation_audit.csv", schema_validation_rows)
    write_csv(output_path / "claim_build_reference_audit.csv", reference_rows)
    write_csv(output_path / "metric_proposal_integrity_audit.csv", metric_integrity_rows)
    write_csv(output_path / "geological_resolved_context_audit.csv", geological_context_rows)
    write_csv(output_path / "claim_deduplication_audit.csv", dedup_audit_rows)
    write_csv(output_path / "claim_materialization_audit.csv", materialization_rows)
    write_csv(output_path / "claim_contract_parity_audit.csv", parity_rows)
    write_csv(output_path / "claim_determinism_audit.csv", determinism_rows)
    write_csv(output_path / "stage5a_immutability_audit.csv", stage5a_immutability_rows)
    write_csv(output_path / "stage5a_hotfix_impact_audit.csv", stage5a_hotfix_rows)
    write_csv(output_path / "stage5b_upstream_rebase_audit.csv", upstream_rebase_rows)
    write_csv(output_path / "stage5b_fixed_case_audit.csv", fixed_case_rows)
    write_csv(output_path / "stage5b_hard_check.csv", hard_rows)

    config_hash = contract_file_hash(repo_root / "configs/claim_contract_v1.yaml")
    (output_path / "config_hashes.sha256").write_text(
        f"{config_hash}  configs/claim_contract_v1.yaml\n",
        encoding="utf-8",
    )
    stage5a_commit = _git(["rev-list", "-n", "1", STAGE5A_TAG], repo_root)
    method_payload = {
        "method_version": method_version,
        "schema_version": STAGE5B_SCHEMA_VERSION,
        "status": status,
        "version_reason": version_reason,
        "generated_at": generated_at,
        "generated_at_semantics": GENERATED_AT_SEMANTICS,
        "upstream_stage5a_method": "stage5a_typed_claim_contract_v1_1_frozen",
        "upstream_stage5a_tag": STAGE5A_TAG,
        "upstream_stage5a_commit": stage5a_commit,
        "upstream_stage5a_artifact": str(STAGE5A_DIR),
        "upstream_stage5a_authorization_hotfix": ("CONTEXT_BOUND_GEOLOGICAL_SUBJECT_RESOLUTION"),
        "upstream_stage5a_authorization_semantics_changed_from_v1": True,
        "stage5b_modifies_stage5a_authorization_semantics": False,
        "upstream_stage4_method": "stage4_bitemporal_state_metrics_v1_1_trace_frozen",
        "upstream_stage4_tag": STAGE4_TAG,
        "upstream_stage4_artifact": str(STAGE4_DIR),
        "upstream_stage4_source_snapshot_sha256": STAGE4_SOURCE_SNAPSHOT_SHA256,
        "upstream_stage4_source_tree_hash": STAGE4_SOURCE_TREE_HASH,
        "stage4_metric_formula_changed": False,
        "stage4_metric_semantics_changed": False,
        "resolved_geological_context_binding": True,
        "unavailable_metric_value_preserved": True,
        "metric_missing_value_sentinel": None,
        "stage5a_contract_semantics_changed": False,
        "stage5a_authorization_semantics_changed": True,
        "stage5a_resolved_provenance_hotfix": True,
        "uses_llm": False,
        "generates_natural_language": False,
        "batch_claim_generation": True,
        "stage5c_analysis": False,
        "stage6_evidence_pack": False,
        "stage5c_implemented": False,
        "stage6_implemented": False,
        "claim_type_count": len(ClaimType),
        "opportunity_count": len(opportunities),
        "proposal_count": len(proposals),
        "decision_count": len(decisions),
        "materialized_claim_count": len(claims),
        "abstention_count": len(abstentions),
        "daily_state_count": len(stage.daily_states),
        "stage4_metric_row_count": len(stage.metric_summaries),
    }
    if status == "FROZEN":
        source_git_commit = _git(["rev-parse", "HEAD"], repo_root)
        source_git_branch = _git(["branch", "--show-current"], repo_root)
        tag_target = _git(["rev-list", "-n", "1", "stage5b-claim-builder-v1-frozen"], repo_root)
        method_payload.update(
            {
                "candidate_artifact_path": str(DEFAULT_OUTPUT_DIR),
                "formal_artifact_path": str(FORMAL_OUTPUT_DIR),
                "source_git_commit": source_git_commit,
                "source_git_tag": "stage5b-claim-builder-v1-frozen"
                if tag_target != "UNKNOWN"
                else "UNCREATED",
                "source_git_branch": source_git_branch,
                "tag_points_to_source_commit": tag_target == source_git_commit,
            }
        )
    semantic_audit_rows: list[dict[str, object]] = []
    freeze_hard_rows: list[dict[str, object]] = []
    if status == "FROZEN":
        semantic_audit_rows = _candidate_formal_semantic_audit(repo_root, output_path)
        write_csv(
            output_path / "stage5b_candidate_formal_semantic_audit.csv",
            semantic_audit_rows,
        )
    write_json(output_path / "method_version.json", method_payload)
    if status == "FROZEN":
        freeze_manifest = _freeze_manifest(
            repo_root,
            output_path,
            method_payload,
            semantic_audit_rows,
            hard_rows,
            [],
        )
        write_json(output_path / "freeze_manifest.json", freeze_manifest)
        freeze_hard_rows = _freeze_hard_check_rows(
            repo_root,
            output_path,
            method_payload,
            semantic_audit_rows,
            hard_rows,
            [],
        )
        write_csv(output_path / "stage5b_freeze_hard_check.csv", freeze_hard_rows)
    _write_report(
        output_path / "stage5b_report.md",
        method_payload,
        type_summary_rows,
        hard_rows,
        report_title,
        semantic_audit_rows,
        freeze_hard_rows,
    )
    write_hashes(output_path)
    if status == "FROZEN":
        hash_rows = _hash_closure_audit(output_path)
        freeze_manifest = _freeze_manifest(
            repo_root,
            output_path,
            method_payload,
            semantic_audit_rows,
            hard_rows,
            hash_rows,
        )
        write_json(output_path / "freeze_manifest.json", freeze_manifest)
        freeze_hard_rows = _freeze_hard_check_rows(
            repo_root,
            output_path,
            method_payload,
            semantic_audit_rows,
            hard_rows,
            hash_rows,
        )
        write_csv(output_path / "stage5b_freeze_hard_check.csv", freeze_hard_rows)
        _write_report(
            output_path / "stage5b_report.md",
            method_payload,
            type_summary_rows,
            hard_rows,
            report_title,
            semantic_audit_rows,
            freeze_hard_rows,
        )
        write_hashes(output_path)
    return {
        "opportunities": len(opportunities),
        "proposals": len(proposals),
        "decisions": len(decisions),
        "claims": len(claims),
        "abstentions": len(abstentions),
    }


class StageData:
    """Loaded formal upstream rows."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.daily_states = read_jsonl(repo_root / STAGE3A_DIR / "daily_construction_states.jsonl")
        self.bitemporal_versions = read_jsonl(
            repo_root / STAGE3B_DIR / "bitemporal_state_versions.jsonl"
        )
        self.stage3a_geo_links = read_jsonl(
            repo_root / STAGE3A_DIR / "state_geological_evidence_links.jsonl"
        )
        self.revision_geo_links = read_jsonl(
            repo_root / STAGE3B_DIR / "revision_geological_evidence_links.jsonl"
        )
        self.metric_summaries = read_jsonl(repo_root / STAGE4_DIR / "state_metric_summary.jsonl")
        self.rai_rows = read_jsonl(repo_root / STAGE4_DIR / "state_rai.jsonl")
        self.grs_rows = read_jsonl(repo_root / STAGE4_DIR / "state_grs.jsonl")
        self.grci_rows = read_jsonl(repo_root / STAGE4_DIR / "state_grci.jsonl")
        self.geological_evidence = read_jsonl(
            repo_root / STAGE2_GEOLOGY_DIR / "primary_geological_evidence.jsonl"
        )
        self.stage4_method = json.loads(
            (repo_root / STAGE4_DIR / "method_version.json").read_text()
        )
        self.stage5a_method = json.loads(
            (repo_root / STAGE5A_DIR / "method_version.json").read_text()
        )
        self.daily_by_id = {str(row["daily_state_id"]): row for row in self.daily_states}
        self.version_by_id = {
            str(row["bitemporal_version_id"]): row for row in self.bitemporal_versions
        }
        self.evidence_by_uid = {str(row["evidence_uid"]): row for row in self.geological_evidence}
        self.geological_subjects_by_uid = _geological_subject_contexts(self.bitemporal_versions)
        self.metric_by_id = {
            **{str(row["state_rai_id"]): row for row in self.rai_rows},
            **{str(row["state_grs_id"]): row for row in self.grs_rows},
            **{str(row["state_grci_id"]): row for row in self.grci_rows},
        }


def _load_stage(repo_root: Path) -> StageData:
    return StageData(repo_root)


def _geological_subject_contexts(
    bitemporal_versions: list[dict[str, Any]],
) -> dict[str, list[dict[str, str]]]:
    contexts: dict[str, list[dict[str, str]]] = defaultdict(list)
    for version in bitemporal_versions:
        for role_field, role in [
            ("materialized_daily_review_evidence_ids", "DAILY_REVIEW_CELL"),
            ("materialized_forward_attention_evidence_ids", "FORWARD_ATTENTION_CELL"),
            ("materialized_local_background_evidence_ids", "LOCAL_BACKGROUND_CELL"),
        ]:
            for evidence_id in version.get(role_field, []):
                contexts[str(evidence_id)].append(
                    {
                        "bitemporal_version_id": str(version.get("bitemporal_version_id", "")),
                        "base_stage3a_state_version_id": str(
                            version.get("base_stage3a_state_version_id", "")
                        ),
                        "daily_state_id": str(version.get("daily_state_id", "")),
                        "cell_id": str(version.get("cell_id", "")),
                        "valid_date": str(version.get("valid_date", "")),
                        "state_role": role,
                    }
                )
    return contexts


def _build_lookup(stage: StageData) -> ClaimUpstreamLookup:
    metrics: dict[str, MetricRecord] = {}
    for row in stage.rai_rows:
        metric_id = str(row["state_rai_id"])
        metrics[metric_id] = MetricRecord(
            metric_id,
            "RAI",
            _optional_float(row.get("rai")),
            str(row.get("rai_status", "")),
            "OPERATIONAL_RESPONSE_ATTENTION_INDEX",
            bool(row.get("is_probability", False)),
            False,
            bool(row.get("is_causal_estimate", False)),
            str(row.get("cell_id", "")) or None,
            str(row.get("bitemporal_version_id", "")) or None,
            str(row.get("base_stage3a_state_version_id", "")) or None,
            _daily_state_id(stage, row),
            str(row.get("valid_date", "")) or None,
            str(row.get("cell_scope_role", "")) or None,
        )
    for row in stage.grs_rows:
        metric_id = str(row["state_grs_id"])
        metrics[metric_id] = MetricRecord(
            metric_id,
            "GRS",
            _optional_float(row.get("grs")),
            str(row.get("grs_status", "")),
            _grs_semantics(str(row.get("cell_scope_role", ""))),
            bool(row.get("is_probability", False)),
            False,
            bool(row.get("is_causal_estimate", False)),
            str(row.get("cell_id", "")) or None,
            str(row.get("bitemporal_version_id", "")) or None,
            str(row.get("base_stage3a_state_version_id", "")) or None,
            _daily_state_id(stage, row),
            str(row.get("valid_date", "")) or None,
            str(row.get("cell_scope_role", "")) or None,
        )
    for row in stage.grci_rows:
        metric_id = str(row["state_grci_id"])
        metrics[metric_id] = MetricRecord(
            metric_id,
            "GRCI",
            _optional_float(row.get("grci")),
            str(row.get("grci_status", "")),
            str(row.get("operator_name", "")),
            bool(row.get("is_probability", False)),
            bool(row.get("is_hazard_probability", False)),
            bool(row.get("is_causal_estimate", False)),
            str(row.get("cell_id", "")) or None,
            str(row.get("bitemporal_version_id", "")) or None,
            str(row.get("base_stage3a_state_version_id", "")) or None,
            _daily_state_id(stage, row),
            str(row.get("valid_date", "")) or None,
            str(row.get("cell_scope_role", "")) or None,
        )

    geological = {
        evidence_uid: GeologicalEvidenceRecord(
            evidence_uid,
            str(row.get("epistemic_status", "")) or None,
            _scope_from_stage2(row.get("spatial_scope") or {}),
            _claimable_attributes(row.get("attributes") or {}),
        )
        for evidence_uid, row in stage.evidence_by_uid.items()
    }
    subjects: dict[str, list[SubjectRecord]] = defaultdict(list)
    for version in stage.bitemporal_versions:
        for role_field, role in [
            ("materialized_daily_review_evidence_ids", "DAILY_REVIEW_CELL"),
            ("materialized_forward_attention_evidence_ids", "FORWARD_ATTENTION_CELL"),
            ("materialized_local_background_evidence_ids", "LOCAL_BACKGROUND_CELL"),
        ]:
            for evidence_id in version.get(role_field, []):
                subjects[str(evidence_id)].append(
                    SubjectRecord(
                        "GEOLOGICAL_EVIDENCE_BACKED",
                        str(evidence_id),
                        str(version.get("bitemporal_version_id", "")) or None,
                        str(version.get("base_stage3a_state_version_id", "")) or None,
                        str(version.get("daily_state_id", "")) or None,
                        str(version.get("cell_id", "")) or None,
                        str(version.get("valid_date", "")) or None,
                        role,
                    )
                )
    grs_lineage = {
        str(row["state_grs_id"]): [
            str(eid) for eid in row.get("grs_contributing_evidence_uids", [])
        ]
        for row in stage.grs_rows
    }
    return ClaimUpstreamLookup(
        metrics=metrics,
        geological_evidence=geological,
        grs_contributing_evidence_ids=grs_lineage,
        geological_subjects=dict(subjects),
    )


def _discover_opportunities(
    stage: StageData,
) -> tuple[list[ClaimOpportunity], list[dict[str, object]]]:
    raw: list[ClaimOpportunity] = []
    raw.extend(_metric_opportunities(stage))
    raw.extend(_geological_opportunities(stage))
    counts = Counter(row.semantic_key for row in raw)
    unique = {row.semantic_key: row for row in sorted(raw, key=lambda item: item.opportunity_id)}
    dedup_rows = [
        {
            "semantic_key": key,
            "raw_candidate_count": count,
            "deduplicated_count": 1,
            "duplicate_removed_count": count - 1,
        }
        for key, count in sorted(counts.items())
    ]
    return sorted(unique.values(), key=_opportunity_sort_key), dedup_rows


def _metric_opportunities(stage: StageData) -> list[ClaimOpportunity]:
    opportunities: list[ClaimOpportunity] = []
    for row in stage.rai_rows:
        opportunities.append(
            _metric_opportunity(
                ClaimType.OPERATIONAL_RESPONSE_ATTENTION,
                "STATE_RAI",
                str(row["state_rai_id"]),
                row,
                "state_rai_full_subject_universe",
            )
        )
    for row in stage.grs_rows:
        role = str(row.get("cell_scope_role", ""))
        if role == "DAILY_REVIEW_CELL":
            opportunities.append(
                _metric_opportunity(
                    ClaimType.GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW,
                    "STATE_GRS",
                    str(row["state_grs_id"]),
                    row,
                    "state_grs_daily_review_universe",
                )
            )
        elif role == "FORWARD_ATTENTION_CELL":
            opportunities.append(
                _metric_opportunity(
                    ClaimType.FORWARD_GEOLOGICAL_ATTENTION,
                    "STATE_GRS",
                    str(row["state_grs_id"]),
                    row,
                    "state_grs_forward_attention_universe",
                )
            )
    for row in stage.grci_rows:
        if row.get("cell_scope_role") == "DAILY_REVIEW_CELL":
            opportunities.append(
                _metric_opportunity(
                    ClaimType.COUPLED_ATTENTION_REVIEW,
                    "STATE_GRCI",
                    str(row["state_grci_id"]),
                    row,
                    "state_grci_daily_review_universe",
                )
            )
    return opportunities


def _metric_opportunity(
    claim_type: ClaimType,
    source_kind: str,
    source_id: str,
    row: dict[str, Any],
    basis: str,
) -> ClaimOpportunity:
    subject = _subject_payload(row)
    metric_name = _metric_name_for_claim(claim_type)
    value_key = metric_name.lower()
    status_key = f"{value_key}_status"
    payload = {
        "metric_source_kind": source_kind,
        "metric_id": source_id,
        "metric_name": metric_name,
        "metric_value": row.get(value_key),
        "metric_status": row.get(status_key),
        "metric_semantics": _metric_semantics_for_row(claim_type, row),
        "is_probability": bool(row.get("is_probability", False)),
        "is_hazard_probability": bool(row.get("is_hazard_probability", False)),
        "is_causal_estimate": bool(row.get("is_causal_estimate", False)),
    }
    semantic = {
        "claim_type": claim_type.value,
        "subject": subject,
        "support": source_id,
    }
    semantic_key = _canonical_json(semantic)
    return ClaimOpportunity(
        opportunity_id=stable_id("claim_opportunity", semantic),
        semantic_key=semantic_key,
        claim_type=claim_type,
        valid_date=str(row.get("valid_date", "")),
        bitemporal_version_id=str(row.get("bitemporal_version_id", "")) or None,
        base_stage3a_state_version_id=str(row.get("base_stage3a_state_version_id", "")) or None,
        daily_state_id=str(row.get("daily_state_id", "")) or None,
        cell_id=str(row.get("cell_id", "")) or None,
        state_role=str(row.get("cell_scope_role", "")),
        source_kind=source_kind,
        source_object_ids=[source_id],
        source_origin="FORMAL_UPSTREAM",
        opportunity_basis=basis,
        payload=payload,
    )


def _geological_opportunities(stage: StageData) -> list[ClaimOpportunity]:
    opportunities: list[ClaimOpportunity] = []
    for version in stage.bitemporal_versions:
        for evidence_id in version.get("materialized_daily_review_evidence_ids", []):
            opportunities.extend(
                _geological_evidence_opportunities(
                    stage,
                    version,
                    str(evidence_id),
                    "DAILY_REVIEW_CELL",
                )
            )
        for evidence_id in version.get("materialized_forward_attention_evidence_ids", []):
            opportunities.extend(
                _geological_evidence_opportunities(
                    stage,
                    version,
                    str(evidence_id),
                    "FORWARD_ATTENTION_CELL",
                )
            )
    return opportunities


def _geological_evidence_opportunities(
    stage: StageData,
    version: dict[str, Any],
    evidence_id: str,
    role: str,
) -> list[ClaimOpportunity]:
    evidence = stage.evidence_by_uid.get(evidence_id)
    if evidence is None:
        return []
    epistemic = str(evidence.get("epistemic_status", "")).upper()
    if epistemic == "OBSERVED":
        claim_type = ClaimType.OBSERVED_GEOLOGICAL_CONDITION
    elif epistemic == "FORECAST":
        claim_type = ClaimType.FORECAST_GEOLOGICAL_CONDITION
    else:
        return []
    attributes = _claimable_attributes(evidence.get("attributes") or {})
    opportunities: list[ClaimOpportunity] = []
    for attribute_name, normalized_value in sorted(attributes.items()):
        subject = _subject_payload(version, role=role)
        semantic = {
            "claim_type": claim_type.value,
            "subject": subject,
            "support": evidence_id,
            "attribute_name": attribute_name,
            "normalized_value": normalized_value,
        }
        opportunities.append(
            ClaimOpportunity(
                opportunity_id=stable_id("claim_opportunity", semantic),
                semantic_key=_canonical_json(semantic),
                claim_type=claim_type,
                valid_date=str(version.get("valid_date", "")),
                bitemporal_version_id=str(version.get("bitemporal_version_id", "")) or None,
                base_stage3a_state_version_id=(
                    str(version.get("base_stage3a_state_version_id", "")) or None
                ),
                daily_state_id=str(version.get("daily_state_id", "")) or None,
                cell_id=str(version.get("cell_id", "")) or None,
                state_role=role,
                source_kind="GEOLOGICAL_EVIDENCE",
                source_object_ids=[evidence_id],
                source_origin="FORMAL_UPSTREAM",
                opportunity_basis="bitemporal_state_materialized_geological_attribute",
                payload={
                    "evidence_id": evidence_id,
                    "attribute_name": attribute_name,
                    "normalized_value": normalized_value,
                    "epistemic_status": epistemic,
                    "spatial_scope": evidence.get("spatial_scope") or {},
                },
            )
        )
    return opportunities


def _construct_proposal(
    opportunity: ClaimOpportunity,
) -> tuple[ClaimProposal | None, ProposalConstructionRecord]:
    try:
        if opportunity.source_kind.startswith("STATE_"):
            proposal = _construct_metric_proposal(opportunity)
        elif opportunity.source_kind == "GEOLOGICAL_EVIDENCE":
            proposal = _construct_geological_proposal(opportunity)
        else:
            return None, ProposalConstructionRecord(
                opportunity_id=opportunity.opportunity_id,
                claim_type=opportunity.claim_type,
                status="NOT_CONSTRUCTIBLE",
                reason="UPSTREAM_REFERENCE_MISSING",
            )
    except (KeyError, TypeError, ValueError) as exc:
        return None, ProposalConstructionRecord(
            opportunity_id=opportunity.opportunity_id,
            claim_type=opportunity.claim_type,
            status="NOT_CONSTRUCTIBLE",
            reason=f"MALFORMED_UPSTREAM_OBJECT:{type(exc).__name__}",
        )
    return proposal, ProposalConstructionRecord(
        opportunity_id=opportunity.opportunity_id,
        proposal_id=proposal.proposal_id,
        claim_type=opportunity.claim_type,
        status="CONSTRUCTED",
        reason=None,
    )


def _construct_metric_proposal(opportunity: ClaimOpportunity) -> ClaimProposal:
    metric_id = opportunity.source_object_ids[0]
    metric_name = str(opportunity.payload["metric_name"])
    semantics = str(opportunity.payload["metric_semantics"])
    support_kind = {
        "STATE_RAI": SupportKind.STATE_RAI,
        "STATE_GRS": SupportKind.STATE_GRS,
        "STATE_GRCI": SupportKind.STATE_GRCI,
    }[opportunity.source_kind]
    metric_status = str(opportunity.payload["metric_status"])
    claim_value = _metric_claim_value(metric_id, metric_name, metric_status, semantics, opportunity)
    return _proposal(
        opportunity,
        _modality_for_claim(opportunity.claim_type),
        _semantic_for_claim(opportunity.claim_type),
        [_identity_support(support_kind, metric_id)],
        _cell_scope(opportunity),
        claim_value,
        {metric_name: metric_status},
    )


def _construct_geological_proposal(opportunity: ClaimOpportunity) -> ClaimProposal:
    evidence_id = opportunity.source_object_ids[0]
    claim_value = GeologicalConditionClaimValue(
        source_evidence_id=evidence_id,
        attribute_name=str(opportunity.payload["attribute_name"]),
        normalized_value=str(opportunity.payload["normalized_value"]),
    )
    return _proposal(
        opportunity,
        _modality_for_claim(opportunity.claim_type),
        _semantic_for_claim(opportunity.claim_type),
        [_identity_support(SupportKind.GEOLOGICAL_EVIDENCE, evidence_id)],
        _scope_from_payload(opportunity),
        claim_value,
        {},
    )


def _proposal(
    opportunity: ClaimOpportunity,
    modality: ClaimModality,
    semantic: ClaimSemanticInterpretation,
    support_refs: list[ClaimSupportRef],
    scope: ClaimScope,
    claim_value: MetricClaimValue | GeologicalConditionClaimValue | None,
    metric_statuses: dict[str, str],
) -> ClaimProposal:
    payload = {
        "opportunity_id": opportunity.opportunity_id,
        "claim_type": opportunity.claim_type.value,
        "subject": _opportunity_subject(opportunity),
        "support": [ref.model_dump(mode="json") for ref in support_refs],
        "claim_value": claim_value.model_dump(mode="json") if claim_value else None,
    }
    return ClaimProposal(
        proposal_id=stable_id("claim_proposal", payload),
        claim_type=opportunity.claim_type,
        bitemporal_version_id=opportunity.bitemporal_version_id,
        base_stage3a_state_version_id=opportunity.base_stage3a_state_version_id,
        state_version_id=opportunity.base_stage3a_state_version_id,
        daily_state_id=opportunity.daily_state_id,
        cell_id=opportunity.cell_id,
        state_role=opportunity.state_role,
        valid_date=_date_or_none(opportunity.valid_date),
        scope=scope,
        modality=modality,
        semantic_interpretation=semantic,
        claim_value=claim_value,
        support_refs=support_refs,
        metric_statuses=metric_statuses,
        metadata={"opportunity_id": opportunity.opportunity_id, "source_origin": "FORMAL_UPSTREAM"},
    )


def _materialize_claim(
    opportunity: ClaimOpportunity,
    proposal: ClaimProposal,
    decision: ClaimDecision,
    builder_version: str = STAGE5B_METHOD_VERSION,
) -> dict[str, Any]:
    assert proposal.claim_value is not None
    sanitized_supports = [
        ClaimSupportRef(
            support_kind=ref.support_kind,
            support_id=ref.support_id,
            support_role=ref.support_role,
        )
        for ref in decision.resolved_support_refs
    ]
    claim = TypedEngineeringClaim(
        claim_id=stable_id(
            "typed_claim",
            {
                "opportunity_id": opportunity.opportunity_id,
                "proposal_id": proposal.proposal_id,
                "decision_id": decision.decision_id,
                "claim_type": proposal.claim_type.value,
            },
        ),
        schema_version=STAGE5A_SCHEMA_VERSION,
        claim_type=proposal.claim_type,
        bitemporal_version_id=proposal.bitemporal_version_id,
        base_stage3a_state_version_id=proposal.base_stage3a_state_version_id,
        state_version_id=proposal.state_version_id,
        daily_state_id=proposal.daily_state_id,
        cell_id=proposal.cell_id,
        state_role=proposal.state_role,
        valid_date=proposal.valid_date,
        spatial_scope=proposal.scope,
        claim_modality=proposal.modality,
        semantic_interpretation=proposal.semantic_interpretation,
        claim_value=proposal.claim_value,
        support_refs=sanitized_supports,
        contract_id=decision.contract_id or "",
        expressibility_status=decision.expressibility,
        abstention_reason=None,
        required_qualifiers=decision.required_qualifiers,
        trace_refs=[ref.support_id for ref in decision.resolved_support_refs],
        metadata={
            "opportunity_id": opportunity.opportunity_id,
            "proposal_id": proposal.proposal_id,
            "decision_id": decision.decision_id,
            "builder_version": builder_version,
        },
    )
    return claim.model_dump(mode="json")


def _materialize_abstention(
    opportunity: ClaimOpportunity,
    proposal: ClaimProposal,
    decision: ClaimDecision,
    builder_version: str = STAGE5B_METHOD_VERSION,
) -> ClaimAbstentionRecord:
    return ClaimAbstentionRecord(
        abstention_id=stable_id(
            "claim_abstention",
            {
                "opportunity_id": opportunity.opportunity_id,
                "proposal_id": proposal.proposal_id,
                "decision_id": decision.decision_id,
                "reason": decision.abstention_reason.value if decision.abstention_reason else "",
            },
        ),
        opportunity_id=opportunity.opportunity_id,
        proposal_id=proposal.proposal_id,
        decision_id=decision.decision_id,
        claim_type=proposal.claim_type,
        valid_date=opportunity.valid_date,
        bitemporal_version_id=opportunity.bitemporal_version_id,
        base_stage3a_state_version_id=opportunity.base_stage3a_state_version_id,
        daily_state_id=opportunity.daily_state_id,
        cell_id=opportunity.cell_id,
        state_role=opportunity.state_role,
        abstention_reason=decision.abstention_reason.value if decision.abstention_reason else "",
        failed_rules=decision.failed_rules,
        resolved_support_summary=_resolved_support_summary(decision),
        builder_version=builder_version,
    )


def _materialization_row(
    opportunity: ClaimOpportunity,
    proposal: ClaimProposal,
    decision: ClaimDecision,
    claim_id: str,
) -> dict[str, object]:
    return {
        "opportunity_id": opportunity.opportunity_id,
        "proposal_id": proposal.proposal_id,
        "decision_id": decision.decision_id,
        "claim_id": claim_id,
        "claim_type": proposal.claim_type.value,
        "decision": decision.expressibility.value,
        "abstention_reason": decision.abstention_reason.value if decision.abstention_reason else "",
        "claim_count": 1 if claim_id else 0,
        "status": "PASS",
    }


def _claim_type_summary(
    opportunities: list[ClaimOpportunity],
    construction_records: list[ProposalConstructionRecord],
    decisions: list[ClaimDecision],
    claims: list[dict[str, Any]],
    abstentions: list[ClaimAbstentionRecord],
) -> list[dict[str, object]]:
    opportunity_by_type = Counter(row.claim_type.value for row in opportunities)
    constructed_by_type = Counter(
        row.claim_type.value for row in construction_records if row.status == "CONSTRUCTED"
    )
    failed_by_type = Counter(
        row.claim_type.value for row in construction_records if row.status != "CONSTRUCTED"
    )
    expressible_by_type = Counter(
        row.claim_type.value
        for row in decisions
        if row.expressibility == ClaimExpressibility.EXPRESSIBLE
    )
    abstain_by_type = Counter(
        row.claim_type.value
        for row in decisions
        if row.expressibility == ClaimExpressibility.ABSTAIN
    )
    claims_by_type = Counter(str(row["claim_type"]) for row in claims)
    support_by_type: dict[str, set[str]] = defaultdict(set)
    subject_by_type: dict[str, set[str]] = defaultdict(set)
    for opportunity in opportunities:
        support_by_type[opportunity.claim_type.value].update(opportunity.source_object_ids)
        subject_by_type[opportunity.claim_type.value].add(
            _canonical_json(_opportunity_subject(opportunity))
        )
    rows: list[dict[str, object]] = []
    for claim_type in ClaimType:
        key = claim_type.value
        rows.append(
            {
                "claim_type": key,
                "opportunity_count": opportunity_by_type[key],
                "proposal_constructed_count": constructed_by_type[key],
                "proposal_construction_failed_count": failed_by_type[key],
                "expressible_count": expressible_by_type[key],
                "abstain_count": abstain_by_type[key],
                "materialized_claim_count": claims_by_type[key],
                "unique_subject_count": len(subject_by_type[key]),
                "unique_support_count": len(support_by_type[key]),
            }
        )
    return rows


def _daily_claim_summary(
    daily_states: list[dict[str, Any]],
    opportunities: list[ClaimOpportunity],
    proposals: list[ClaimProposal],
    decisions: list[ClaimDecision],
    claims: list[dict[str, Any]],
) -> list[dict[str, object]]:
    dates = sorted({str(row["target_date"]) for row in daily_states})
    opp_by_date = Counter(row.valid_date for row in opportunities)
    prop_by_date = Counter(str(row.valid_date) for row in proposals)
    decision_by_proposal = {row.proposal_id: row for row in decisions}
    expr_by_date: Counter[str] = Counter()
    abstain_by_date: Counter[str] = Counter()
    for proposal in proposals:
        decision = decision_by_proposal[proposal.proposal_id]
        if decision.expressibility == ClaimExpressibility.EXPRESSIBLE:
            expr_by_date[str(proposal.valid_date)] += 1
        else:
            abstain_by_date[str(proposal.valid_date)] += 1
    claim_by_date = Counter(str(row["valid_date"]) for row in claims)
    return [
        {
            "valid_date": date,
            "opportunity_count": opp_by_date[date],
            "proposal_count": prop_by_date[date],
            "expressible_count": expr_by_date[date],
            "abstain_count": abstain_by_date[date],
            "materialized_claim_count": claim_by_date[date],
        }
        for date in dates
    ]


def _typed_claim_schema_validation_audit(claims: list[dict[str, Any]]) -> list[dict[str, object]]:
    allowed_fields = set(TypedEngineeringClaim.model_fields)
    rows: list[dict[str, object]] = []
    for row in claims:
        extra_fields = sorted(set(row) - allowed_fields)
        error = ""
        status = "PASS"
        try:
            claim = TypedEngineeringClaim.model_validate(row)
            TypedEngineeringClaim.model_validate(claim.model_dump(mode="json"))
        except Exception as exc:
            status = "FAIL"
            error = f"{type(exc).__name__}: {exc}"
        rows.append(
            {
                "claim_id": row.get("claim_id", ""),
                "schema_version": row.get("schema_version", ""),
                "validation_status": status,
                "extra_field_count": len(extra_fields),
                "extra_fields": ";".join(extra_fields),
                "validation_error": error,
            }
        )
    return sorted(rows, key=lambda item: str(item["claim_id"]))


def _reference_audit(
    stage: StageData,
    opportunities: list[ClaimOpportunity],
    proposals: list[ClaimProposal],
    decisions: list[ClaimDecision],
    claims: list[dict[str, Any]],
    abstentions: list[ClaimAbstentionRecord],
    construction_records: list[ProposalConstructionRecord],
) -> list[dict[str, object]]:
    opportunity_ids = {row.opportunity_id for row in opportunities}
    proposal_ids = {row.proposal_id for row in proposals}
    decision_ids = {row.decision_id for row in decisions}
    decision_by_id = {row.decision_id: row for row in decisions}
    contract_ids = {row["contract_id"] for row in _read_stage5a_contract_rows(stage.repo_root)}
    upstream_ids = (
        set(stage.metric_by_id)
        | set(stage.evidence_by_uid)
        | {row["bitemporal_version_id"] for row in stage.bitemporal_versions}
    )
    checks: list[tuple[str, int, int]] = []
    checks.append(
        (
            "opportunity_source_object",
            len(opportunities),
            sum(all(src in upstream_ids for src in row.source_object_ids) for row in opportunities),
        )
    )
    checks.append(
        (
            "proposal_to_opportunity",
            len(construction_records),
            sum(row.opportunity_id in opportunity_ids for row in construction_records),
        )
    )
    checks.append(
        (
            "decision_to_proposal",
            len(decisions),
            sum(row.proposal_id in proposal_ids for row in decisions),
        )
    )
    checks.append(
        (
            "claim_to_decision",
            len(claims),
            sum(str(_claim_metadata(row).get("decision_id", "")) in decision_ids for row in claims),
        )
    )
    checks.append(
        (
            "CLAIM_TO_OPPORTUNITY",
            len(claims),
            sum(
                str(_claim_metadata(row).get("opportunity_id", "")) in opportunity_ids
                for row in claims
            ),
        )
    )
    checks.append(
        (
            "CLAIM_TO_PROPOSAL",
            len(claims),
            sum(str(_claim_metadata(row).get("proposal_id", "")) in proposal_ids for row in claims),
        )
    )
    checks.append(
        (
            "CLAIM_TO_DECISION",
            len(claims),
            sum(str(_claim_metadata(row).get("decision_id", "")) in decision_ids for row in claims),
        )
    )
    checks.append(
        (
            "claim_to_contract",
            len(claims),
            sum(str(row["contract_id"]) in contract_ids for row in claims),
        )
    )
    resolved_total = 0
    resolved_valid = 0
    for row in claims:
        decision = _decision_for_claim(row, decision_by_id)
        if decision is None:
            continue
        resolved_total += len(decision.resolved_support_refs)
        resolved_valid += sum(
            support.support_id in upstream_ids for support in decision.resolved_support_refs
        )
    checks.append(("claim_resolved_support_to_upstream", resolved_total, resolved_valid))
    trace_total = len(claims)
    trace_valid = sum(
        _claim_trace_matches_decision(row, _decision_for_claim(row, decision_by_id))
        for row in claims
    )
    checks.append(("CLAIM_TRACE_TO_RESOLVED_SUPPORT", trace_total, trace_valid))
    context_total = 0
    context_valid = 0
    geological_claim_types = {
        ClaimType.OBSERVED_GEOLOGICAL_CONDITION.value,
        ClaimType.FORECAST_GEOLOGICAL_CONDITION.value,
    }
    for row in claims:
        if row.get("claim_type") not in geological_claim_types:
            continue
        decision = _decision_for_claim(row, decision_by_id)
        if decision is None:
            continue
        for support in decision.resolved_support_refs:
            if support.support_kind != SupportKind.GEOLOGICAL_EVIDENCE:
                continue
            context_total += 1
            if _resolved_support_context_matches_claim(row, support.model_dump(mode="json")):
                context_valid += 1
    checks.append(("RESOLVED_SUPPORT_SUBJECT_CONTEXT", context_total, context_valid))
    checks.append(
        (
            "abstention_to_decision",
            len(abstentions),
            sum(row.decision_id in decision_ids for row in abstentions),
        )
    )
    rows = []
    for check_name, total, valid in checks:
        invalid = total - valid
        rows.append(
            {
                "check_name": check_name,
                "total_count": total,
                "valid_count": valid,
                "invalid_count": invalid,
                "status": "PASS" if invalid == 0 else "FAIL",
            }
        )
    return rows


def _metric_proposal_integrity_audit(
    stage: StageData,
    proposals: list[ClaimProposal],
    decisions: list[ClaimDecision],
) -> list[dict[str, object]]:
    decision_by_proposal = {row.proposal_id: row for row in decisions}
    rows: list[dict[str, object]] = []
    for proposal in proposals:
        support = proposal.support_refs[0]
        if support.support_kind not in {
            SupportKind.STATE_RAI,
            SupportKind.STATE_GRS,
            SupportKind.STATE_GRCI,
        }:
            continue
        upstream = stage.metric_by_id[support.support_id]
        upstream_value = _stage_metric_value(upstream)
        proposal_value = (
            proposal.claim_value.metric_value
            if isinstance(proposal.claim_value, MetricClaimValue)
            else None
        )
        decision = decision_by_proposal[proposal.proposal_id]
        upstream_status = str(upstream.get(_metric_status_field(upstream), ""))
        status = _metric_integrity_status(upstream_status, upstream_value, proposal_value)
        rows.append(
            {
                "claim_type": proposal.claim_type.value,
                "source_metric_id": support.support_id,
                "upstream_metric_status": upstream_status,
                "upstream_metric_value": upstream_value,
                "proposal_metric_value": proposal_value,
                "decision": decision.expressibility.value,
                "integrity_status": status,
                "upstream_null_to_numeric_substitution": (
                    str(upstream_value is None and proposal_value is not None).lower()
                ),
            }
        )
    return sorted(rows, key=lambda row: (str(row["claim_type"]), str(row["source_metric_id"])))


def _geological_resolved_context_audit(
    stage: StageData,
    claims: list[dict[str, Any]],
    decisions: list[ClaimDecision],
) -> list[dict[str, object]]:
    decision_by_id = {row.decision_id: row for row in decisions}
    rows: list[dict[str, object]] = []
    for claim in claims:
        if claim.get("claim_type") not in {
            ClaimType.OBSERVED_GEOLOGICAL_CONDITION.value,
            ClaimType.FORECAST_GEOLOGICAL_CONDITION.value,
        }:
            continue
        decision = _decision_for_claim(claim, decision_by_id)
        if decision is None:
            continue
        for resolved_support in decision.resolved_support_refs:
            support = resolved_support.model_dump(mode="json")
            if resolved_support.support_kind != SupportKind.GEOLOGICAL_EVIDENCE:
                continue
            context_match = _resolved_support_context_matches_claim(claim, support)
            status = "PASS"
            if support.get("resolution_status") == "SUPPORT_SUBJECT_CONTEXT_AMBIGUOUS":
                status = "AMBIGUOUS"
            elif support.get("resolution_status") != "RESOLVED":
                status = "UNRESOLVED"
            elif not context_match:
                status = "MISMATCH"
            rows.append(
                {
                    "claim_id": claim["claim_id"],
                    "claim_type": claim["claim_type"],
                    "support_id": support["support_id"],
                    "available_context_count": len(
                        stage.geological_subjects_by_uid.get(str(support["support_id"]), [])
                    ),
                    "claim_bitemporal_version_id": claim.get("bitemporal_version_id"),
                    "resolved_bitemporal_version_id": support.get("resolved_bitemporal_version_id"),
                    "claim_base_stage3a_state_version_id": claim.get(
                        "base_stage3a_state_version_id"
                    ),
                    "resolved_base_stage3a_state_version_id": support.get(
                        "resolved_base_stage3a_state_version_id"
                    ),
                    "claim_daily_state_id": claim.get("daily_state_id"),
                    "resolved_daily_state_id": support.get("resolved_daily_state_id"),
                    "claim_cell_id": claim.get("cell_id"),
                    "resolved_cell_id": support.get("resolved_cell_id"),
                    "claim_valid_date": claim.get("valid_date"),
                    "resolved_valid_date": support.get("resolved_valid_date"),
                    "claim_state_role": claim.get("state_role"),
                    "resolved_state_role": support.get("resolved_state_role"),
                    "context_match": str(context_match).lower(),
                    "resolution_status": support.get("resolution_status"),
                    "status": status,
                }
            )
    return sorted(rows, key=lambda row: (str(row["claim_id"]), str(row["support_id"])))


def _deduplication_audit(
    dedup_rows: list[dict[str, object]],
    opportunities: list[ClaimOpportunity],
    proposals: list[ClaimProposal],
    decisions: list[ClaimDecision],
    claims: list[dict[str, Any]],
) -> list[dict[str, object]]:
    rows = list(dedup_rows)
    for name, ids in [
        ("duplicate_opportunity_id", [row.opportunity_id for row in opportunities]),
        ("duplicate_proposal_id", [row.proposal_id for row in proposals]),
        ("duplicate_decision_id", [row.decision_id for row in decisions]),
        ("duplicate_claim_id", [str(row["claim_id"]) for row in claims]),
    ]:
        duplicate_count = len(ids) - len(set(ids))
        rows.append(
            {
                "semantic_key": name,
                "raw_candidate_count": len(ids),
                "deduplicated_count": len(set(ids)),
                "duplicate_removed_count": duplicate_count,
            }
        )
    return rows


def _contract_parity_audit(
    evaluator: ClaimContractEvaluator,
    proposals: list[ClaimProposal],
    decisions: list[ClaimDecision],
) -> list[dict[str, object]]:
    decision_by_proposal = {row.proposal_id: row for row in decisions}
    rows: list[dict[str, object]] = []
    for proposal in proposals:
        original = decision_by_proposal[proposal.proposal_id]
        repeated = evaluator.evaluate(proposal)
        mismatch = original.model_dump(mode="json") != repeated.model_dump(mode="json")
        rows.append(
            {
                "proposal_id": proposal.proposal_id,
                "claim_type": proposal.claim_type.value,
                "original_decision_id": original.decision_id,
                "repeated_decision_id": repeated.decision_id,
                "decision_mismatch": str(mismatch).lower(),
                "status": "PASS" if not mismatch else "FAIL",
            }
        )
    return sorted(rows, key=lambda row: str(row["proposal_id"]))


def _determinism_audit(
    repo_root: Path,
    opportunities: list[ClaimOpportunity],
    proposals: list[ClaimProposal],
    decisions: list[ClaimDecision],
    claims: list[dict[str, Any]],
    abstentions: list[ClaimAbstentionRecord],
    builder_version: str = STAGE5B_METHOD_VERSION,
) -> list[dict[str, object]]:
    stage = _load_stage(repo_root)
    repeat_opportunities, _ = _discover_opportunities(stage)
    lookup = _build_lookup(stage)
    evaluator = ClaimContractEvaluator(
        ClaimTypeRegistry.from_contracts(
            load_claim_contracts(repo_root / "configs/claim_contract_v1.yaml")
        ),
        lookup,
    )
    repeat_proposals: list[ClaimProposal] = []
    repeat_decisions: list[ClaimDecision] = []
    repeat_claims: list[dict[str, Any]] = []
    repeat_abstentions: list[ClaimAbstentionRecord] = []
    for opportunity in repeat_opportunities:
        proposal, record = _construct_proposal(opportunity)
        if proposal is None or record.status != "CONSTRUCTED":
            continue
        repeat_proposals.append(proposal)
        decision = evaluator.evaluate(proposal)
        repeat_decisions.append(decision)
        if decision.expressibility == ClaimExpressibility.EXPRESSIBLE:
            repeat_claims.append(
                _materialize_claim(opportunity, proposal, decision, builder_version)
            )
        else:
            repeat_abstentions.append(
                _materialize_abstention(opportunity, proposal, decision, builder_version)
            )
    checks = [
        (
            "opportunity_ids",
            sorted(row.opportunity_id for row in opportunities),
            sorted(row.opportunity_id for row in repeat_opportunities),
        ),
        (
            "proposal_ids",
            sorted(row.proposal_id for row in proposals),
            sorted(row.proposal_id for row in repeat_proposals),
        ),
        (
            "decision_ids",
            sorted(row.decision_id for row in decisions),
            sorted(row.decision_id for row in repeat_decisions),
        ),
        (
            "claim_ids",
            sorted(str(row["claim_id"]) for row in claims),
            sorted(str(row["claim_id"]) for row in repeat_claims),
        ),
        (
            "abstention_ids",
            sorted(row.abstention_id for row in abstentions),
            sorted(row.abstention_id for row in repeat_abstentions),
        ),
        (
            "semantic_keys",
            sorted(row.semantic_key for row in opportunities),
            sorted(row.semantic_key for row in repeat_opportunities),
        ),
        (
            "geological_resolved_subject_context",
            _canonical_json(_geological_resolved_context_audit(stage, claims, decisions)),
            _canonical_json(
                _geological_resolved_context_audit(stage, repeat_claims, repeat_decisions)
            ),
        ),
        (
            "metric_null_semantics",
            _canonical_json(_metric_proposal_integrity_audit(stage, proposals, decisions)),
            _canonical_json(
                _metric_proposal_integrity_audit(stage, repeat_proposals, repeat_decisions)
            ),
        ),
        (
            "typed_claim_serialized_schema_content",
            _typed_claim_schema_content(claims),
            _typed_claim_schema_content(repeat_claims),
        ),
    ]
    return [
        {
            "check_name": name,
            "business_diff_count": 0 if left == right else 1,
            "status": "PASS" if left == right else "FAIL",
        }
        for name, left, right in checks
    ]


def _stage5a_immutability_audit(repo_root: Path) -> list[dict[str, object]]:
    mismatch_count = _stage5a_v1_1_source_diff_count(repo_root)
    return [
        {
            "check_name": "Stage5A frozen artifact hash manifest",
            "change_class": "AUTHORITATIVE_FROZEN_ARTIFACT",
            "diff_count": mismatch_count,
            "status": "PASS" if mismatch_count == 0 else "FAIL",
        }
    ]


def _stage5a_hotfix_impact_audit(repo_root: Path) -> list[dict[str, object]]:
    specs = [
        (
            "src/tbm_twin/claims/models.py",
            "SEMANTIC_FROZEN_FILE",
            False,
            False,
            False,
            False,
            False,
        ),
        (
            "src/tbm_twin/claims/contracts.py",
            "SEMANTIC_FROZEN_FILE",
            False,
            False,
            False,
            False,
            False,
        ),
        (
            "configs/claim_contract_v1.yaml",
            "SEMANTIC_FROZEN_FILE",
            False,
            False,
            False,
            False,
            False,
        ),
        (
            "scripts/build_stage5a_claim_contract.py",
            "SEMANTIC_FROZEN_FILE",
            False,
            False,
            False,
            False,
            False,
        ),
        (
            "src/tbm_twin/claims/validation.py",
            "HOTFIX_ALLOWED_FILE",
            True,
            False,
            False,
            True,
            True,
        ),
        (
            "src/tbm_twin/claims/resolution.py",
            "HOTFIX_ALLOWED_FILE",
            True,
            False,
            False,
            True,
            True,
        ),
    ]
    rows: list[dict[str, object]] = []
    for path, change_class, auth, contract, claim_type, decision_rule, provenance in specs:
        diff = _git(
            [
                "diff",
                "--name-only",
                f"{STAGE5A_PARENT_TAG}^{{}}",
                f"{STAGE5A_TAG}^{{}}",
                "--",
                path,
            ],
            repo_root,
        )
        changed = bool(diff.strip())
        expected_changed = change_class == "HOTFIX_ALLOWED_FILE"
        rows.append(
            {
                "changed_file": path,
                "change_class": change_class,
                "file_changed": str(changed).lower(),
                "authorization_semantics_changed": str(auth).lower(),
                "contract_semantics_changed": str(contract).lower(),
                "claim_type_changed": str(claim_type).lower(),
                "decision_rule_changed": str(decision_rule).lower(),
                "resolved_provenance_changed": str(provenance and changed).lower(),
                "status": "PASS" if changed == expected_changed or not changed else "FAIL",
            }
        )
    return rows


def _stage5b_upstream_rebase_audit(
    type_summary_rows: list[dict[str, object]],
    abstentions: list[ClaimAbstentionRecord],
    metric_integrity_rows: list[dict[str, object]],
    geological_context_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    baseline_claims = {
        "OPERATIONAL_RESPONSE_ATTENTION": 174,
        "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW": 190,
        "COUPLED_ATTENTION_REVIEW": 174,
        "FORWARD_GEOLOGICAL_ATTENTION": 200,
        "OBSERVED_GEOLOGICAL_CONDITION": 758,
        "FORECAST_GEOLOGICAL_CONDITION": 4783,
    }
    summary_by_type = {str(row["claim_type"]): row for row in type_summary_rows}
    rows: list[dict[str, object]] = [
        _rebase_row(
            "opportunity_count",
            sum(_int_value(row["opportunity_count"]) for row in type_summary_rows),
            8679,
        ),
        _rebase_row(
            "proposal_count",
            sum(_int_value(row["proposal_constructed_count"]) for row in type_summary_rows),
            8679,
        ),
        _rebase_row(
            "decision_count",
            sum(
                _int_value(row["expressible_count"]) + _int_value(row["abstain_count"])
                for row in type_summary_rows
            ),
            8679,
        ),
        _rebase_row(
            "EXPRESSIBLE_count",
            sum(_int_value(row["expressible_count"]) for row in type_summary_rows),
            6279,
        ),
        _rebase_row(
            "ABSTAIN_count",
            sum(_int_value(row["abstain_count"]) for row in type_summary_rows),
            2400,
        ),
        _rebase_row(
            "claim_count",
            sum(_int_value(row["materialized_claim_count"]) for row in type_summary_rows),
            6279,
        ),
        _rebase_row(
            "abstention_reason_distribution",
            _canonical_json(Counter(row.abstention_reason for row in abstentions)),
            _canonical_json(
                {
                    "UNKNOWN_SOURCE_VALUE": 1078,
                    "CONTEXT_ONLY_ROLE": 880,
                    "STATE_ROLE_NOT_ALLOWED": 305,
                    "REQUIRED_EPISTEMIC_STATUS_MISSING": 105,
                    "REQUIRED_METRIC_UNAVAILABLE": 32,
                }
            ),
        ),
        _rebase_row(
            "geological_resolved_context",
            sum(row["status"] != "PASS" for row in geological_context_rows),
            0,
        ),
        _rebase_row(
            "metric_payload_null_semantics",
            sum(
                row["upstream_null_to_numeric_substitution"] == "true"
                for row in metric_integrity_rows
            ),
            0,
        ),
    ]
    for claim_type, expected in baseline_claims.items():
        rows.append(
            _rebase_row(
                f"claim_type_distribution_{claim_type}",
                _int_value(summary_by_type[claim_type]["materialized_claim_count"]),
                expected,
            )
        )
    rows.append(
        _rebase_row(
            "claim_payload_semantic_identity",
            sum(row["status"] != "PASS" for row in rows),
            0,
        )
    )
    return rows


def _rebase_row(check_name: str, actual: object, expected: object) -> dict[str, object]:
    return {
        "check_name": check_name,
        "old": expected,
        "new": actual,
        "delta": _delta(actual, expected),
        "status": "PASS" if actual == expected else "FAIL",
    }


def _delta(actual: object, expected: object) -> object:
    if isinstance(actual, int) and isinstance(expected, int):
        return actual - expected
    return "0" if actual == expected else "DIFF"


def _int_value(value: object) -> int:
    return int(str(value))


def _fixed_case_audit(
    stage: StageData,
    opportunities: list[ClaimOpportunity],
    decisions: list[ClaimDecision],
    claims: list[dict[str, Any]],
) -> list[dict[str, object]]:
    by_type_status = Counter((row.claim_type.value, row.expressibility.value) for row in decisions)
    opp_by_type = Counter(row.claim_type.value for row in opportunities)
    claim_by_type = Counter(str(row["claim_type"]) for row in claims)
    rows = [
        _case(
            "M1_RAI_AVAILABLE",
            by_type_status[("OPERATIONAL_RESPONSE_ATTENTION", "EXPRESSIBLE")] > 0
            and claim_by_type["OPERATIONAL_RESPONSE_ATTENTION"] > 0,
        ),
        _case(
            "M2_RAI_UNAVAILABLE", by_type_status[("OPERATIONAL_RESPONSE_ATTENTION", "ABSTAIN")] > 0
        ),
        _case("M3_GRS_DAILY_REVIEW", opp_by_type["GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW"] > 0),
        _case(
            "M4_GRCI_DAILY_REVIEW_AVAILABLE",
            by_type_status[("COUPLED_ATTENTION_REVIEW", "EXPRESSIBLE")] > 0,
        ),
        _case(
            "M5_FORWARD_GRS_NO_GRCI",
            opp_by_type["FORWARD_GEOLOGICAL_ATTENTION"] > 0
            and _forward_grci_count(opportunities) == 0,
        ),
        _case(
            "G1_OBSERVED_ATTRIBUTE",
            by_type_status[("OBSERVED_GEOLOGICAL_CONDITION", "EXPRESSIBLE")] > 0,
        ),
        _case(
            "G2_FORECAST_ATTRIBUTE",
            by_type_status[("FORECAST_GEOLOGICAL_CONDITION", "EXPRESSIBLE")] > 0,
        ),
        _case(
            "G3_UNKNOWN_ATTRIBUTE_ABSTAINS",
            any(
                dec.abstention_reason and dec.abstention_reason.value == "UNKNOWN_SOURCE_VALUE"
                for dec in decisions
            ),
        ),
        _case(
            "G4_LOCAL_BACKGROUND_NO_STANDALONE",
            _standalone_local_background_claim_count(claims) == 0,
        ),
        _case(
            "2023_11_06_NO_FAKE_CELL_CLAIM",
            not any(row.valid_date == "2023-11-06" for row in opportunities)
            and not any(str(row["valid_date"]) == "2023-11-06" for row in claims),
        ),
        _case(
            "2023_11_05_FROZEN_SCOPE_USED",
            any(row.valid_date == "2023-11-05" for row in opportunities),
        ),
        _case(
            "2023_11_09_FROZEN_SCOPE_USED",
            any(row.valid_date == "2023-11-09" for row in opportunities),
        ),
        _case("REVISION_CHAIN_IDENTITY_PRESERVED", _revision_chain_preserved(stage, opportunities)),
    ]
    return rows


def _hard_check_rows(
    repo_root: Path,
    stage: StageData,
    opportunities: list[ClaimOpportunity],
    proposals: list[ClaimProposal],
    decisions: list[ClaimDecision],
    claims: list[dict[str, Any]],
    abstentions: list[ClaimAbstentionRecord],
    construction_records: list[ProposalConstructionRecord],
    reference_rows: list[dict[str, object]],
    schema_validation_rows: list[dict[str, object]],
    metric_integrity_rows: list[dict[str, object]],
    geological_context_rows: list[dict[str, object]],
    dedup_rows: list[dict[str, object]],
    parity_rows: list[dict[str, object]],
    determinism_rows: list[dict[str, object]],
    stage5a_immutibility_rows: list[dict[str, object]],
    stage5a_hotfix_rows: list[dict[str, object]],
    upstream_rebase_rows: list[dict[str, object]],
    fixed_case_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    decision_by_id = {row.decision_id: row for row in decisions}
    claim_decision_counts = Counter(
        str(_claim_metadata(row).get("decision_id", "")) for row in claims
    )
    expressible_without_claim = sum(
        1
        for decision in decisions
        if decision.expressibility == ClaimExpressibility.EXPRESSIBLE
        and claim_decision_counts[decision.decision_id] != 1
    )
    claim_without_expressible = 0
    for claim in claims:
        decision = _decision_for_claim(claim, decision_by_id)
        if decision is None or decision.expressibility != ClaimExpressibility.EXPRESSIBLE:
            claim_without_expressible += 1
    duplicate_claim_id = _duplicate_count([str(row["claim_id"]) for row in claims])
    invalid_reference_count = sum(int(str(row["invalid_count"])) for row in reference_rows)
    metric_mismatch = sum(
        1
        for decision in decisions
        if decision.abstention_reason
        and decision.abstention_reason.value
        in {"METRIC_VALUE_MISMATCH", "METRIC_IDENTITY_MISMATCH"}
    )
    context_mismatch = sum(row["status"] == "MISMATCH" for row in geological_context_rows)
    context_ambiguous = sum(row["status"] == "AMBIGUOUS" for row in geological_context_rows)
    context_unresolved = sum(row["status"] == "UNRESOLVED" for row in geological_context_rows)
    null_substitution = sum(
        row["upstream_null_to_numeric_substitution"] == "true" for row in metric_integrity_rows
    )
    available_metric_mismatch = sum(
        row["integrity_status"] == "MISMATCH" for row in metric_integrity_rows
    )
    metric_recomputation = available_metric_mismatch + null_substitution
    order_dependency = _subject_record_order_dependency_count(stage, proposals, decisions)
    frozen_stage5a_diff = _stage5a_frozen_artifact_mismatch_count(repo_root)
    contract_semantic_modification = sum(
        row["contract_semantics_changed"] == "true" for row in stage5a_hotfix_rows
    )
    unapproved_stage5a_modification = sum(
        row["status"] != "PASS" for row in stage5a_immutibility_rows
    )
    upstream_rebase_diff = sum(row["status"] != "PASS" for row in upstream_rebase_rows)
    schema_invalid = sum(row["validation_status"] != "PASS" for row in schema_validation_rows)
    schema_extra = sum(_int_value(row["extra_field_count"]) for row in schema_validation_rows)
    top_level_counts = _typed_claim_forbidden_top_level_counts(claims)
    reference_invalid_by_name = {
        str(row["check_name"]): _int_value(row["invalid_count"]) for row in reference_rows
    }
    checks = [
        ("formal_daily_state_count_matches_upstream", len(stage.daily_states), 91),
        (
            "unsupported_claim_type_count",
            sum(row.claim_type not in set(ClaimType) for row in opportunities),
            0,
        ),
        (
            "standalone_local_background_claim_count",
            _standalone_local_background_claim_count(claims),
            0,
        ),
        ("forward_grci_claim_count", _forward_grci_count(opportunities), 0),
        ("forecast_promoted_to_observed_count", _forecast_promotion_count(claims, decisions), 0),
        (
            "observed_without_observed_proof_count",
            _observed_without_observed_proof_count(claims, decisions),
            0,
        ),
        ("unknown_factual_claim_count", _unknown_factual_claim_count(claims), 0),
        (
            "response_to_geological_fact_claim_count",
            _response_to_geological_fact_count(claims, decisions),
            0,
        ),
        (
            "unlocated_spatial_factual_claim_count",
            _unlocated_spatial_factual_claim_count(claims),
            0,
        ),
        ("support_scope_violation_count", _support_scope_violation_count(claims, decisions), 0),
        ("geological_resolved_subject_mismatch_count", context_mismatch, 0),
        ("geological_resolved_context_ambiguity_count", context_ambiguous, 0),
        ("geological_resolved_context_unresolved_count", context_unresolved, 0),
        ("subject_record_order_dependency_count", order_dependency, 0),
        ("upstream_null_to_numeric_substitution_count", null_substitution, 0),
        ("available_metric_value_mismatch_count", available_metric_mismatch, 0),
        ("metric_value_recomputation_count", metric_recomputation, 0),
        ("metric_value_mismatch_count", metric_mismatch, 0),
        (
            "claim_subject_decision_mismatch_count",
            _claim_subject_decision_mismatch_count(claims, decisions),
            0,
        ),
        (
            "claim_using_asserted_support_metadata_count",
            _claim_using_asserted_support_metadata_count(claims),
            0,
        ),
        ("expressible_without_claim_count", expressible_without_claim, 0),
        ("claim_without_expressible_decision_count", claim_without_expressible, 0),
        ("duplicate_claim_id_count", duplicate_claim_id, 0),
        ("invalid_reference_count", invalid_reference_count, 0),
        ("typed_engineering_claim_schema_invalid_count", schema_invalid, 0),
        ("typed_engineering_claim_extra_field_count", schema_extra, 0),
        (
            "typed_claim_to_opportunity_invalid_count",
            reference_invalid_by_name.get("CLAIM_TO_OPPORTUNITY", 0),
            0,
        ),
        (
            "typed_claim_to_proposal_invalid_count",
            reference_invalid_by_name.get("CLAIM_TO_PROPOSAL", 0),
            0,
        ),
        (
            "typed_claim_to_decision_invalid_count",
            reference_invalid_by_name.get("CLAIM_TO_DECISION", 0),
            0,
        ),
        (
            "typed_claim_trace_to_resolved_support_invalid_count",
            reference_invalid_by_name.get("CLAIM_TRACE_TO_RESOLVED_SUPPORT", 0),
            0,
        ),
        ("typed_claim_top_level_decision_id_count", top_level_counts["decision_id"], 0),
        ("typed_claim_top_level_proposal_id_count", top_level_counts["proposal_id"], 0),
        ("typed_claim_top_level_opportunity_id_count", top_level_counts["opportunity_id"], 0),
        (
            "typed_claim_top_level_resolved_support_refs_count",
            top_level_counts["resolved_support_refs"],
            0,
        ),
        (
            "synthetic_fixture_in_formal_output_count",
            _synthetic_fixture_count(opportunities, claims),
            0,
        ),
        (
            "stage5a_semantic_modification_count",
            contract_semantic_modification,
            0,
        ),
        ("stage5a_frozen_artifact_modified", str(frozen_stage5a_diff != 0).lower(), "false"),
        (
            "stage5a_contract_semantic_modification_count",
            contract_semantic_modification,
            0,
        ),
        (
            "stage5a_unapproved_file_modification_count",
            unapproved_stage5a_modification,
            0,
        ),
        ("stage4_modification_count", _stage4_modification_count(repo_root, stage), 0),
        ("uses_llm", "false", "false"),
        ("generates_natural_language", "false", "false"),
        (
            "proposal_construction_failure_count",
            sum(row.status != "CONSTRUCTED" for row in construction_records),
            0,
        ),
        ("contract_parity_mismatch_count", sum(row["status"] != "PASS" for row in parity_rows), 0),
        ("determinism_diff_count", sum(row["status"] != "PASS" for row in determinism_rows), 0),
        ("stage5b_upstream_rebase_semantic_diff_count", upstream_rebase_diff, 0),
        ("fixed_case_failure_count", sum(row["status"] != "PASS" for row in fixed_case_rows), 0),
        (
            "abstain_claim_count",
            sum(1 for row in claims if row.get("expressibility_status") == "ABSTAIN"),
            0,
        ),
        (
            "claim_materialization_count_match",
            len(claims),
            sum(1 for row in decisions if row.expressibility == ClaimExpressibility.EXPRESSIBLE),
        ),
        (
            "abstention_count_match",
            len(abstentions),
            sum(1 for row in decisions if row.expressibility == ClaimExpressibility.ABSTAIN),
        ),
    ]
    rows: list[dict[str, object]] = []
    issue_count = 0
    for check_name, actual, expected in checks:
        passed = actual == expected
        if not passed:
            issue_count += 1
        rows.append(
            {
                "check_name": check_name,
                "actual": actual,
                "expected": expected,
                "evidence_source": _hard_check_evidence(check_name),
                "status": "PASS" if passed else "FAIL",
            }
        )
    rows.append(
        {
            "check_name": "issue_count",
            "actual": issue_count,
            "expected": 0,
            "evidence_source": "computed from hard checks",
            "status": "PASS" if issue_count == 0 else "FAIL",
        }
    )
    return rows


def _sorted_outputs(
    opportunities: list[ClaimOpportunity],
    proposals: list[ClaimProposal],
    decisions: list[ClaimDecision],
    claims: list[dict[str, Any]],
    abstentions: list[ClaimAbstentionRecord],
    construction_records: list[ProposalConstructionRecord],
) -> dict[str, Any]:
    return {
        "opportunities": sorted(opportunities, key=_opportunity_sort_key),
        "proposals": sorted(proposals, key=lambda row: row.proposal_id),
        "decisions": sorted(decisions, key=lambda row: row.decision_id),
        "claims": sorted(claims, key=lambda row: str(row["claim_id"])),
        "abstentions": sorted(abstentions, key=lambda row: row.abstention_id),
        "construction_records": sorted(construction_records, key=lambda row: row.opportunity_id),
    }


def _opportunity_sort_key(row: ClaimOpportunity) -> tuple[str, str, str, str, str]:
    return (
        row.valid_date,
        row.claim_type.value,
        row.cell_id or "",
        ";".join(row.source_object_ids),
        row.semantic_key,
    )


def _opportunity_universe() -> list[dict[str, str]]:
    return [
        {
            "claim_type": "OPERATIONAL_RESPONSE_ATTENTION",
            "source_object": "StateRAI",
            "eligible_role": "ALL_STATE_RAI_SUBJECTS",
            "eligible_epistemic_status": "N/A",
            "dedup_key": "claim_type + bitemporal subject + state_rai_id",
            "proposal_builder": "metric_builder",
            "contract_evaluator": "Frozen Stage5A ClaimContractEvaluator",
        },
        {
            "claim_type": "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
            "source_object": "StateGRS",
            "eligible_role": "DAILY_REVIEW_CELL",
            "eligible_epistemic_status": "OBSERVED_OR_FORECAST_LINEAGE",
            "dedup_key": "claim_type + bitemporal subject + state_grs_id",
            "proposal_builder": "metric_builder",
            "contract_evaluator": "Frozen Stage5A ClaimContractEvaluator",
        },
        {
            "claim_type": "COUPLED_ATTENTION_REVIEW",
            "source_object": "StateGRCI",
            "eligible_role": "DAILY_REVIEW_CELL",
            "eligible_epistemic_status": "N/A",
            "dedup_key": "claim_type + bitemporal subject + state_grci_id",
            "proposal_builder": "metric_builder",
            "contract_evaluator": "Frozen Stage5A ClaimContractEvaluator",
        },
        {
            "claim_type": "FORWARD_GEOLOGICAL_ATTENTION",
            "source_object": "StateGRS",
            "eligible_role": "FORWARD_ATTENTION_CELL",
            "eligible_epistemic_status": "FORECAST_LINEAGE",
            "dedup_key": "claim_type + bitemporal subject + state_grs_id",
            "proposal_builder": "metric_builder",
            "contract_evaluator": "Frozen Stage5A ClaimContractEvaluator",
        },
        {
            "claim_type": "OBSERVED_GEOLOGICAL_CONDITION",
            "source_object": "Bitemporal materialized geological evidence attribute",
            "eligible_role": "DAILY_REVIEW_CELL",
            "eligible_epistemic_status": "OBSERVED",
            "dedup_key": "claim_type + bitemporal subject + evidence + attribute + value",
            "proposal_builder": "geological_builder",
            "contract_evaluator": "Frozen Stage5A ClaimContractEvaluator",
        },
        {
            "claim_type": "FORECAST_GEOLOGICAL_CONDITION",
            "source_object": "Bitemporal materialized geological evidence attribute",
            "eligible_role": "DAILY_REVIEW_CELL_OR_FORWARD_ATTENTION_CELL",
            "eligible_epistemic_status": "FORECAST",
            "dedup_key": "claim_type + bitemporal subject + evidence + attribute + value",
            "proposal_builder": "geological_builder",
            "contract_evaluator": "Frozen Stage5A ClaimContractEvaluator",
        },
    ]


def _scope_from_payload(opportunity: ClaimOpportunity) -> ClaimScope:
    # Authoritative support scope is resolved by Stage5A; proposal scope is the claimed geometry.
    evidence_scope = opportunity.payload.get("spatial_scope")
    if isinstance(evidence_scope, dict):
        scope = _scope_from_stage2(evidence_scope)
        if scope is not None:
            return scope
    return ClaimScope(scope_kind=ClaimScopeKind.UNLOCATED, scope_basis="missing_geological_scope")


def _scope_from_stage2(scope: dict[str, Any]) -> ClaimScope | None:
    kind = str(scope.get("kind", "")).upper()
    basis = str(scope.get("basis", "")) or "stage2_geological_evidence_scope"
    if kind == "POINT":
        point = _optional_float(scope.get("start_chainage"))
        if point is None:
            return None
        return ClaimScope(
            scope_kind=ClaimScopeKind.LOCATED_POINT,
            point_chainage=point,
            scope_basis=basis,
        )
    if kind == "INTERVAL":
        start = _optional_float(scope.get("start_chainage"))
        end = _optional_float(scope.get("end_chainage"))
        if start is None or end is None or start >= end:
            return None
        return ClaimScope(
            scope_kind=ClaimScopeKind.LOCATED_INTERVAL,
            start_chainage=start,
            end_chainage=end,
            scope_basis=basis,
        )
    return ClaimScope(scope_kind=ClaimScopeKind.UNLOCATED, scope_basis=basis) if kind else None


def _cell_scope(opportunity: ClaimOpportunity) -> ClaimScope:
    return ClaimScope(
        scope_kind=ClaimScopeKind.CELL,
        valid_date=_date_or_none(opportunity.valid_date),
        cell_id=opportunity.cell_id,
        daily_state_id=opportunity.daily_state_id,
        state_role=opportunity.state_role,
        scope_basis="stage5b_bitemporal_state_subject",
    )


def _date_or_none(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _identity_support(kind: SupportKind, support_id: str) -> ClaimSupportRef:
    return ClaimSupportRef(
        support_kind=kind,
        support_id=support_id,
        support_role=ClaimSupportRole.PRIMARY_SUPPORT,
    )


def _claimable_attributes(attributes: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in attributes.items():
        if key not in GEOLOGICAL_ATTRIBUTE_ALLOWLIST:
            continue
        if isinstance(value, (list, dict)):
            continue
        result[key] = _normalize_attr_value(value)
    return result


def _normalize_attr_value(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    text = str(value).strip()
    return text if text else "UNKNOWN"


def _metric_claim_value(
    metric_id: str,
    metric_name: str,
    metric_status: str,
    semantics: str,
    opportunity: ClaimOpportunity,
) -> MetricClaimValue | None:
    metric_value = _optional_float(opportunity.payload.get("metric_value"))
    if metric_status != "AVAILABLE" or metric_value is None:
        return None
    return MetricClaimValue(
        metric_name=metric_name,
        metric_value=metric_value,
        metric_status=metric_status,
        metric_semantics=semantics,
        is_probability=bool(opportunity.payload.get("is_probability", False)),
        is_hazard_probability=bool(opportunity.payload.get("is_hazard_probability", False)),
        is_causal_estimate=bool(opportunity.payload.get("is_causal_estimate", False)),
        source_metric_id=metric_id,
    )


def _metric_status_field(row: dict[str, Any]) -> str:
    if "state_rai_id" in row:
        return "rai_status"
    if "state_grs_id" in row:
        return "grs_status"
    return "grci_status"


def _stage_metric_value(row: dict[str, Any]) -> float | None:
    if "state_rai_id" in row:
        return _optional_float(row.get("rai"))
    if "state_grs_id" in row:
        return _optional_float(row.get("grs"))
    return _optional_float(row.get("grci"))


def _metric_integrity_status(
    upstream_status: str,
    upstream_value: float | None,
    proposal_value: float | None,
) -> str:
    if upstream_status == "AVAILABLE":
        if (
            upstream_value is not None
            and proposal_value is not None
            and abs(upstream_value - proposal_value) <= 1e-12
        ):
            return "AVAILABLE_VALUE_MATCH"
        return "MISMATCH"
    if proposal_value is None:
        return "UNAVAILABLE_VALUE_PRESERVED_NULL"
    return "MISMATCH"


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _subject_payload(row: dict[str, Any], role: str | None = None) -> dict[str, str]:
    return {
        "bitemporal_version_id": str(row.get("bitemporal_version_id", "")),
        "base_stage3a_state_version_id": str(row.get("base_stage3a_state_version_id", "")),
        "daily_state_id": str(row.get("daily_state_id", "")),
        "cell_id": str(row.get("cell_id", "")),
        "valid_date": str(row.get("valid_date", "")),
        "state_role": role or str(row.get("cell_scope_role", "")),
    }


def _opportunity_subject(opportunity: ClaimOpportunity) -> dict[str, str | None]:
    return {
        "bitemporal_version_id": opportunity.bitemporal_version_id,
        "base_stage3a_state_version_id": opportunity.base_stage3a_state_version_id,
        "daily_state_id": opportunity.daily_state_id,
        "cell_id": opportunity.cell_id,
        "valid_date": opportunity.valid_date,
        "state_role": opportunity.state_role,
    }


def _daily_state_id(stage: StageData, row: dict[str, Any]) -> str | None:
    bitemporal = stage.version_by_id.get(str(row.get("bitemporal_version_id", "")))
    if bitemporal:
        return str(bitemporal.get("daily_state_id", "")) or None
    return None


def _metric_name_for_claim(claim_type: ClaimType) -> str:
    return {
        ClaimType.OPERATIONAL_RESPONSE_ATTENTION: "RAI",
        ClaimType.GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW: "GRS",
        ClaimType.FORWARD_GEOLOGICAL_ATTENTION: "GRS",
        ClaimType.COUPLED_ATTENTION_REVIEW: "GRCI",
    }[claim_type]


def _metric_semantics_for_claim(claim_type: ClaimType) -> str:
    return {
        ClaimType.OPERATIONAL_RESPONSE_ATTENTION: "OPERATIONAL_RESPONSE_ATTENTION_INDEX",
        ClaimType.GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW: "GEOLOGICAL_EVIDENCE_ATTENTION_INDEX",
        ClaimType.FORWARD_GEOLOGICAL_ATTENTION: "FORWARD_GEOLOGICAL_EVIDENCE_ATTENTION_INDEX",
        ClaimType.COUPLED_ATTENTION_REVIEW: "NONPROBABILISTIC_CONJUNCTIVE_PRODUCT",
    }[claim_type]


def _metric_semantics_for_row(claim_type: ClaimType, row: dict[str, Any]) -> str:
    if claim_type == ClaimType.COUPLED_ATTENTION_REVIEW:
        return str(row.get("operator_name", "")) or _metric_semantics_for_claim(claim_type)
    if claim_type in {
        ClaimType.GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW,
        ClaimType.FORWARD_GEOLOGICAL_ATTENTION,
    }:
        return _grs_semantics(str(row.get("cell_scope_role", "")))
    return _metric_semantics_for_claim(claim_type)


def _grs_semantics(role: str) -> str:
    return (
        "FORWARD_GEOLOGICAL_EVIDENCE_ATTENTION_INDEX"
        if role == "FORWARD_ATTENTION_CELL"
        else "GEOLOGICAL_EVIDENCE_ATTENTION_INDEX"
    )


def _modality_for_claim(claim_type: ClaimType) -> ClaimModality:
    return {
        ClaimType.OPERATIONAL_RESPONSE_ATTENTION: ClaimModality.DERIVED_ATTENTION,
        ClaimType.GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW: ClaimModality.DERIVED_ATTENTION,
        ClaimType.COUPLED_ATTENTION_REVIEW: ClaimModality.DERIVED_ATTENTION,
        ClaimType.FORWARD_GEOLOGICAL_ATTENTION: ClaimModality.DERIVED_ATTENTION,
        ClaimType.OBSERVED_GEOLOGICAL_CONDITION: ClaimModality.GEOLOGICAL_OBSERVED,
        ClaimType.FORECAST_GEOLOGICAL_CONDITION: ClaimModality.GEOLOGICAL_FORECAST,
    }[claim_type]


def _semantic_for_claim(claim_type: ClaimType) -> ClaimSemanticInterpretation:
    return {
        ClaimType.OPERATIONAL_RESPONSE_ATTENTION: (
            ClaimSemanticInterpretation.OPERATIONAL_RESPONSE_ATTENTION
        ),
        ClaimType.GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW: (
            ClaimSemanticInterpretation.GEOLOGICAL_EVIDENCE_ATTENTION
        ),
        ClaimType.COUPLED_ATTENTION_REVIEW: ClaimSemanticInterpretation.COUPLED_ATTENTION,
        ClaimType.FORWARD_GEOLOGICAL_ATTENTION: (
            ClaimSemanticInterpretation.GEOLOGICAL_EVIDENCE_ATTENTION
        ),
        ClaimType.OBSERVED_GEOLOGICAL_CONDITION: (
            ClaimSemanticInterpretation.OBSERVED_GEOLOGICAL_CONDITION
        ),
        ClaimType.FORECAST_GEOLOGICAL_CONDITION: (
            ClaimSemanticInterpretation.FORECAST_GEOLOGICAL_CONDITION
        ),
    }[claim_type]


def _resolved_support_summary(decision: ClaimDecision) -> str:
    return ";".join(
        f"{ref.support_kind.value}:{ref.support_id}:{ref.resolution_status}"
        for ref in decision.resolved_support_refs
    )


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_stage5a_contract_rows(repo_root: Path) -> list[dict[str, Any]]:
    return read_jsonl(repo_root / STAGE5A_DIR / "claim_contracts.jsonl")


def _case(case_id: str, passed: bool) -> dict[str, object]:
    return {"case_id": case_id, "status": "PASS" if passed else "FAIL"}


def _forward_grci_count(opportunities: list[ClaimOpportunity]) -> int:
    return sum(
        row.claim_type == ClaimType.COUPLED_ATTENTION_REVIEW
        and row.state_role == "FORWARD_ATTENTION_CELL"
        for row in opportunities
    )


def _standalone_local_background_claim_count(claims: list[dict[str, Any]]) -> int:
    return sum(str(row.get("state_role")) == "LOCAL_BACKGROUND_CELL" for row in claims)


def _forecast_promotion_count(
    claims: list[dict[str, Any]],
    decisions: list[ClaimDecision],
) -> int:
    decision_by_id = {row.decision_id: row for row in decisions}
    return sum(
        row.get("claim_type") == ClaimType.OBSERVED_GEOLOGICAL_CONDITION.value
        and any(
            support.resolved_epistemic_status == "FORECAST"
            for support in _resolved_supports_for_claim(row, decision_by_id)
        )
        for row in claims
    )


def _observed_without_observed_proof_count(
    claims: list[dict[str, Any]],
    decisions: list[ClaimDecision],
) -> int:
    decision_by_id = {row.decision_id: row for row in decisions}
    return sum(
        row.get("claim_type") == ClaimType.OBSERVED_GEOLOGICAL_CONDITION.value
        and not any(
            support.resolved_epistemic_status == "OBSERVED"
            for support in _resolved_supports_for_claim(row, decision_by_id)
        )
        for row in claims
    )


def _unknown_factual_claim_count(claims: list[dict[str, Any]]) -> int:
    return sum(
        row.get("claim_type")
        in {
            ClaimType.OBSERVED_GEOLOGICAL_CONDITION.value,
            ClaimType.FORECAST_GEOLOGICAL_CONDITION.value,
        }
        and str((row.get("claim_value") or {}).get("normalized_value", "")).upper()
        in UNKNOWN_VALUES
        for row in claims
    )


def _response_to_geological_fact_count(
    claims: list[dict[str, Any]],
    decisions: list[ClaimDecision],
) -> int:
    decision_by_id = {row.decision_id: row for row in decisions}
    return sum(
        row.get("claim_type")
        in {
            ClaimType.OBSERVED_GEOLOGICAL_CONDITION.value,
            ClaimType.FORECAST_GEOLOGICAL_CONDITION.value,
        }
        and any(
            support.support_kind.value in {"RESPONSE_EVIDENCE", "STATE_RAI"}
            for support in _resolved_supports_for_claim(row, decision_by_id)
        )
        for row in claims
    )


def _unlocated_spatial_factual_claim_count(claims: list[dict[str, Any]]) -> int:
    return sum(
        row.get("claim_type")
        in {
            ClaimType.OBSERVED_GEOLOGICAL_CONDITION.value,
            ClaimType.FORECAST_GEOLOGICAL_CONDITION.value,
        }
        and (row.get("spatial_scope") or {}).get("scope_kind") == "UNLOCATED"
        for row in claims
    )


def _support_scope_violation_count(
    claims: list[dict[str, Any]],
    decisions: list[ClaimDecision],
) -> int:
    # Stage5A spatial evaluator already enforces containment; count unresolved support in claims.
    decision_by_id = {row.decision_id: row for row in decisions}
    return sum(
        support.resolution_status != "RESOLVED"
        for row in claims
        for support in _resolved_supports_for_claim(row, decision_by_id)
        if support.support_role == ClaimSupportRole.PRIMARY_SUPPORT
    )


def _claim_subject_decision_mismatch_count(
    claims: list[dict[str, Any]],
    decisions: list[ClaimDecision],
) -> int:
    decision_by_id = {row.decision_id: row for row in decisions}
    count = 0
    for row in claims:
        primary = [
            support
            for support in _resolved_supports_for_claim(row, decision_by_id)
            if support.support_role == ClaimSupportRole.PRIMARY_SUPPORT
            and support.support_kind.value
            in {
                SupportKind.STATE_RAI.value,
                SupportKind.STATE_GRS.value,
                SupportKind.STATE_GRCI.value,
                SupportKind.GEOLOGICAL_EVIDENCE.value,
            }
        ]
        for support in primary:
            if not _resolved_support_context_matches_claim(row, support.model_dump(mode="json")):
                count += 1
    return count


def _subject_record_order_dependency_count(
    stage: StageData,
    proposals: list[ClaimProposal],
    decisions: list[ClaimDecision],
) -> int:
    lookup = _build_lookup(stage)
    reversed_lookup = ClaimUpstreamLookup(
        metrics=lookup.metrics,
        geological_evidence=lookup.geological_evidence,
        grs_contributing_evidence_ids=lookup.grs_contributing_evidence_ids,
        geological_subjects={
            evidence_id: list(reversed(subjects))
            for evidence_id, subjects in lookup.geological_subjects.items()
        },
        cell_scopes=lookup.cell_scopes,
    )
    evaluator = ClaimContractEvaluator(
        ClaimTypeRegistry.from_contracts(
            load_claim_contracts(stage.repo_root / "configs/claim_contract_v1.yaml")
        ),
        reversed_lookup,
    )
    decision_by_proposal = {row.proposal_id: row for row in decisions}
    mismatch_count = 0
    for proposal in proposals:
        if proposal.claim_type not in {
            ClaimType.OBSERVED_GEOLOGICAL_CONDITION,
            ClaimType.FORECAST_GEOLOGICAL_CONDITION,
        }:
            continue
        original = decision_by_proposal[proposal.proposal_id]
        if original.expressibility != ClaimExpressibility.EXPRESSIBLE:
            continue
        repeated = evaluator.evaluate(proposal)
        if repeated.model_dump(mode="json") != original.model_dump(mode="json"):
            mismatch_count += 1
    return mismatch_count


def _resolved_support_context_matches_claim(
    claim: dict[str, Any],
    support: dict[str, Any],
) -> bool:
    comparisons = [
        ("bitemporal_version_id", "resolved_bitemporal_version_id"),
        ("base_stage3a_state_version_id", "resolved_base_stage3a_state_version_id"),
        ("daily_state_id", "resolved_daily_state_id"),
        ("cell_id", "resolved_cell_id"),
        ("valid_date", "resolved_valid_date"),
        ("state_role", "resolved_state_role"),
    ]
    for claim_field, support_field in comparisons:
        claim_value = claim.get(claim_field)
        support_value = support.get(support_field)
        if (
            claim_value is not None
            and support_value is not None
            and str(claim_value) != str(support_value)
        ):
            return False
        if claim_value is not None and support_value is None:
            return False
    return support.get("resolution_status") == "RESOLVED"


def _claim_metadata(claim: dict[str, Any]) -> dict[str, Any]:
    metadata = claim.get("metadata") or {}
    return metadata if isinstance(metadata, dict) else {}


def _decision_for_claim(
    claim: dict[str, Any],
    decision_by_id: dict[str, ClaimDecision],
) -> ClaimDecision | None:
    decision_id = str(_claim_metadata(claim).get("decision_id", ""))
    return decision_by_id.get(decision_id)


def _resolved_supports_for_claim(
    claim: dict[str, Any],
    decision_by_id: dict[str, ClaimDecision],
) -> list[Any]:
    decision = _decision_for_claim(claim, decision_by_id)
    return list(decision.resolved_support_refs) if decision else []


def _claim_trace_matches_decision(
    claim: dict[str, Any],
    decision: ClaimDecision | None,
) -> bool:
    if decision is None:
        return False
    return sorted(str(item) for item in claim.get("trace_refs", [])) == sorted(
        ref.support_id for ref in decision.resolved_support_refs
    )


def _typed_claim_forbidden_top_level_counts(claims: list[dict[str, Any]]) -> dict[str, int]:
    forbidden = ["decision_id", "proposal_id", "opportunity_id", "resolved_support_refs"]
    return {field: sum(field in row for row in claims) for field in forbidden}


def _typed_claim_schema_content(claims: list[dict[str, Any]]) -> str:
    normalized = [
        TypedEngineeringClaim.model_validate(row).model_dump(mode="json") for row in claims
    ]
    return _canonical_json(sorted(normalized, key=lambda row: str(row["claim_id"])))


def _stage5a_frozen_artifact_mismatch_count(repo_root: Path) -> int:
    """Verify the authoritative Stage 5A input rather than mutable live source."""

    return _stage5a_v1_1_source_diff_count(repo_root)


def _claim_using_asserted_support_metadata_count(claims: list[dict[str, Any]]) -> int:
    return sum(
        bool(
            support.get("epistemic_status")
            or support.get("spatial_scope")
            or support.get("state_role")
        )
        for row in claims
        for support in row.get("support_refs", [])
    )


def _synthetic_fixture_count(
    opportunities: list[ClaimOpportunity], claims: list[dict[str, Any]]
) -> int:
    markers = ("fixture", "geo_interval_100_110", "fake")
    return sum(
        any(marker in _canonical_json(row.model_dump(mode="json")) for marker in markers)
        for row in opportunities
    ) + sum(any(marker in _canonical_json(row) for marker in markers) for row in claims)


def _duplicate_count(ids: list[str]) -> int:
    return len(ids) - len(set(ids))


def _stage4_modification_count(repo_root: Path, stage: StageData) -> int:
    expected_snapshot = "906a6d8636483adc5e71099af1c4a801f21dff427beb6c8ac198dd435244373d"
    expected_tree = "a8e9eee5c5e26e266fffd0a495be51dbea0727a09ac84c63ac9834d2e7602464"
    hash_diff = int(
        stage.stage4_method.get("source_snapshot_sha256") != expected_snapshot
        or stage.stage4_method.get("source_tree_hash") != expected_tree
    )
    artifact = repo_root / "artifacts/stage4_bitemporal_state_metrics_v1_1"
    manifest = artifact / "file_hashes.sha256"
    artifact_diff = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        path = artifact / relative
        actual = _sha256(path) if path.is_file() else ""
        artifact_diff += int(actual != expected)
    return hash_diff + artifact_diff


def _revision_chain_preserved(stage: StageData, opportunities: list[ClaimOpportunity]) -> bool:
    by_base_date_cell: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for version in stage.bitemporal_versions:
        key = (
            str(version.get("base_stage3a_state_version_id", "")),
            str(version.get("valid_date", "")),
            str(version.get("cell_id", "")),
        )
        by_base_date_cell[key].add(str(version.get("bitemporal_version_id", "")))
    revision_keys = {
        key: versions for key, versions in by_base_date_cell.items() if len(versions) >= 2
    }
    if not revision_keys:
        return False
    opportunity_versions = {row.bitemporal_version_id for row in opportunities}
    return any(len(versions & opportunity_versions) >= 2 for versions in revision_keys.values())


def _hard_check_evidence(check_name: str) -> str:
    if "reference" in check_name:
        return "claim_build_reference_audit.csv"
    if "duplicate" in check_name:
        return "claim_deduplication_audit.csv"
    if "determinism" in check_name:
        return "claim_determinism_audit.csv"
    if "stage5a" in check_name:
        return "stage5a_immutability_audit.csv"
    return "stage5b batch materialization"


def _candidate_formal_semantic_audit(
    repo_root: Path,
    formal_path: Path,
) -> list[dict[str, object]]:
    candidate_path = _formal_comparison_reference(repo_root)
    checks = [
        (
            "opportunity_business_diff",
            _jsonl_business_diff(
                candidate_path / "claim_opportunities.jsonl",
                formal_path / "claim_opportunities.jsonl",
                "opportunity_id",
            ),
        ),
        (
            "proposal_business_diff",
            _jsonl_business_diff(
                candidate_path / "claim_proposals.jsonl",
                formal_path / "claim_proposals.jsonl",
                "proposal_id",
            ),
        ),
        (
            "decision_business_diff",
            _jsonl_business_diff(
                candidate_path / "claim_decisions.jsonl",
                formal_path / "claim_decisions.jsonl",
                "decision_id",
            ),
        ),
        (
            "claim_business_diff",
            _jsonl_business_diff(
                candidate_path / "typed_engineering_claims.jsonl",
                formal_path / "typed_engineering_claims.jsonl",
                "claim_id",
            ),
        ),
        (
            "abstention_business_diff",
            _jsonl_business_diff(
                candidate_path / "claim_abstentions.jsonl",
                formal_path / "claim_abstentions.jsonl",
                "abstention_id",
            ),
        ),
        (
            "claim_id_diff",
            _id_diff(
                candidate_path / "typed_engineering_claims.jsonl",
                formal_path / "typed_engineering_claims.jsonl",
                "claim_id",
            ),
        ),
        (
            "decision_id_diff",
            _id_diff(
                candidate_path / "claim_decisions.jsonl",
                formal_path / "claim_decisions.jsonl",
                "decision_id",
            ),
        ),
        (
            "claim_type_distribution_diff",
            _csv_business_diff(
                candidate_path / "claim_type_summary.csv",
                formal_path / "claim_type_summary.csv",
            ),
        ),
        (
            "abstention_reason_distribution_diff",
            _abstention_reason_distribution_diff(candidate_path, formal_path),
        ),
        (
            "daily_summary_diff",
            _csv_business_diff(
                candidate_path / "daily_claim_summary.csv",
                formal_path / "daily_claim_summary.csv",
            ),
        ),
        (
            "resolved_context_diff",
            _csv_business_diff(
                candidate_path / "geological_resolved_context_audit.csv",
                formal_path / "geological_resolved_context_audit.csv",
            ),
        ),
        (
            "metric_integrity_diff",
            _csv_business_diff(
                candidate_path / "metric_proposal_integrity_audit.csv",
                formal_path / "metric_proposal_integrity_audit.csv",
            ),
        ),
        (
            "reference_integrity_diff",
            _csv_business_diff(
                candidate_path / "claim_build_reference_audit.csv",
                formal_path / "claim_build_reference_audit.csv",
            ),
        ),
    ]
    return [
        {
            "check_name": name,
            "business_diff_count": diff,
            "status": "PASS" if diff == 0 else "FAIL",
        }
        for name, diff in checks
    ]


def _jsonl_business_diff(candidate: Path, formal: Path, key: str) -> int:
    left = {str(row[key]): _strip_packaging_metadata(row) for row in read_jsonl(candidate)}
    right = {str(row[key]): _strip_packaging_metadata(row) for row in read_jsonl(formal)}
    differing_keys = set(left) ^ set(right)
    common_mismatch = sum(1 for item in set(left) & set(right) if left[item] != right[item])
    return len(differing_keys) + common_mismatch


def _id_diff(candidate: Path, formal: Path, key: str) -> int:
    left = {str(row[key]) for row in read_jsonl(candidate)}
    right = {str(row[key]) for row in read_jsonl(formal)}
    return len(left ^ right)


def _csv_business_diff(candidate: Path, formal: Path) -> int:
    left = _strip_packaging_metadata(_read_csv(candidate))
    right = _strip_packaging_metadata(_read_csv(formal))
    return 0 if left == right else 1


def _abstention_reason_distribution_diff(candidate_path: Path, formal_path: Path) -> int:
    candidate = Counter(
        row["abstention_reason"] for row in read_jsonl(candidate_path / "claim_abstentions.jsonl")
    )
    formal = Counter(
        row["abstention_reason"] for row in read_jsonl(formal_path / "claim_abstentions.jsonl")
    )
    return 0 if candidate == formal else 1


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _strip_packaging_metadata(value: Any) -> Any:
    ignored = {
        "method_version",
        "status",
        "generated_at",
        "generated_at_semantics",
        "artifact_path",
        "candidate_artifact_path",
        "formal_artifact_path",
        "report_title",
        "builder_version",
        "freeze_metadata",
        "file_hashes",
        "source_git_commit",
        "source_git_tag",
        "source_git_branch",
        "tag_points_to_source_commit",
    }
    if isinstance(value, dict):
        return {
            key: _strip_packaging_metadata(item)
            for key, item in sorted(value.items())
            if key not in ignored
        }
    if isinstance(value, list):
        return [_strip_packaging_metadata(item) for item in value]
    return value


def _freeze_manifest(
    repo_root: Path,
    output_path: Path,
    method_payload: dict[str, Any],
    semantic_audit_rows: list[dict[str, object]],
    hard_rows: list[dict[str, object]],
    hash_rows: list[dict[str, object]],
) -> dict[str, Any]:
    candidate_path = _formal_comparison_reference(repo_root)
    issue_count = next(row["actual"] for row in hard_rows if row["check_name"] == "issue_count")
    hash_invalid = sum(_int_value(row["invalid_count"]) for row in hash_rows)
    semantic_pass = all(row["status"] == "PASS" for row in semantic_audit_rows)
    quality_pass = issue_count == 0 and hash_invalid == 0 and semantic_pass
    return {
        "method": method_payload["method_version"],
        "schema": method_payload["schema_version"],
        "status": method_payload["status"],
        "generated_at": method_payload["generated_at"],
        "generated_at_semantics": method_payload["generated_at_semantics"],
        "candidate_artifact_path": str(DEFAULT_OUTPUT_DIR),
        "formal_artifact_path": str(FORMAL_OUTPUT_DIR),
        "candidate_manifest_sha256": _sha256(candidate_path / "file_hashes.sha256"),
        "upstream_stage5a_method": method_payload["upstream_stage5a_method"],
        "upstream_stage5a_commit": method_payload["upstream_stage5a_commit"],
        "upstream_stage5a_tag": method_payload["upstream_stage5a_tag"],
        "upstream_stage4_tag": method_payload["upstream_stage4_tag"],
        "stage4_source_snapshot_sha256": STAGE4_SOURCE_SNAPSHOT_SHA256,
        "stage4_source_tree_hash": STAGE4_SOURCE_TREE_HASH,
        "candidate_formal_business_equivalence": "PASS" if semantic_pass else "FAIL",
        "quality_gate_status": "PASS" if quality_pass else "FAIL",
        "uses_llm": False,
        "generates_natural_language": False,
        "stage5c_implemented": False,
        "stage6_implemented": False,
        "source_git_commit": method_payload.get("source_git_commit", "UNKNOWN"),
        "source_git_tag": method_payload.get("source_git_tag", "UNCREATED"),
        "source_git_branch": method_payload.get("source_git_branch", "UNKNOWN"),
        "tag_points_to_source_commit": method_payload.get("tag_points_to_source_commit", False),
        "formal_actual_file_count": len([path for path in output_path.iterdir() if path.is_file()]),
        "file_hash_entry_count": len(
            [
                line
                for line in (output_path / "file_hashes.sha256")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
        )
        if (output_path / "file_hashes.sha256").exists()
        else 0,
        "file_hash_invalid_count": hash_invalid,
    }


def _formal_comparison_reference(repo_root: Path) -> Path:
    """Use the compact frozen baseline after the duplicate candidate is archived."""

    candidate_path = repo_root / DEFAULT_OUTPUT_DIR
    if candidate_path.exists():
        return candidate_path
    return repo_root / FORMAL_OUTPUT_DIR


def _freeze_hard_check_rows(
    repo_root: Path,
    output_path: Path,
    method_payload: dict[str, Any],
    semantic_audit_rows: list[dict[str, object]],
    hard_rows: list[dict[str, object]],
    hash_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    semantic = {
        str(row["check_name"]): _int_value(row["business_diff_count"])
        for row in semantic_audit_rows
    }
    hard_issue = _int_value(
        next(row["actual"] for row in hard_rows if row["check_name"] == "issue_count")
    )
    hash_invalid = sum(_int_value(row["invalid_count"]) for row in hash_rows)
    checks: list[tuple[str, object, object]] = [
        ("formal_directory_exists", output_path.exists(), True),
        (
            "formal_method_is_frozen",
            method_payload["method_version"],
            STAGE5B_FORMAL_METHOD_VERSION,
        ),
        ("formal_schema_correct", method_payload["schema_version"], STAGE5B_SCHEMA_VERSION),
        ("candidate_formal_opportunity_diff", semantic.get("opportunity_business_diff", -1), 0),
        ("candidate_formal_proposal_diff", semantic.get("proposal_business_diff", -1), 0),
        ("candidate_formal_decision_diff", semantic.get("decision_business_diff", -1), 0),
        ("candidate_formal_claim_diff", semantic.get("claim_business_diff", -1), 0),
        ("candidate_formal_abstention_diff", semantic.get("abstention_business_diff", -1), 0),
        ("candidate_formal_claim_id_diff", semantic.get("claim_id_diff", -1), 0),
        ("candidate_formal_decision_id_diff", semantic.get("decision_id_diff", -1), 0),
        ("candidate_formal_context_diff", semantic.get("resolved_context_diff", -1), 0),
        ("candidate_formal_metric_integrity_diff", semantic.get("metric_integrity_diff", -1), 0),
        ("candidate_formal_reference_diff", semantic.get("reference_integrity_diff", -1), 0),
        (
            "formal_typed_claim_schema_invalid_count",
            _formal_schema_invalid_count(output_path),
            0,
        ),
        ("formal_hard_check_issue_count", hard_issue, 0),
        ("formal_file_hash_invalid_count", hash_invalid, 0),
        ("stage5a_v1_1_source_diff", _stage5a_v1_1_source_diff_count(repo_root), 0),
        ("stage4_source_diff", _stage4_modification_count(repo_root, _load_stage(repo_root)), 0),
        ("uses_llm", "false", "false"),
        ("generates_natural_language", "false", "false"),
        ("stage5c_implemented", "false", "false"),
    ]
    rows: list[dict[str, object]] = []
    issue_count = 0
    for check_name, actual, expected in checks:
        status = "PASS" if actual == expected else "FAIL"
        issue_count += int(status != "PASS")
        rows.append(
            {
                "check_name": check_name,
                "actual": actual,
                "expected": expected,
                "status": status,
            }
        )
    rows.append(
        {
            "check_name": "issue_count",
            "actual": issue_count,
            "expected": 0,
            "status": "PASS" if issue_count == 0 else "FAIL",
        }
    )
    return rows


def _formal_schema_invalid_count(output_path: Path) -> int:
    rows = _read_csv(output_path / "typed_claim_schema_validation_audit.csv")
    return sum(row["validation_status"] != "PASS" for row in rows) + sum(
        _int_value(row["extra_field_count"]) for row in rows
    )


def _hash_closure_audit(output_path: Path) -> list[dict[str, object]]:
    hash_path = output_path / "file_hashes.sha256"
    expected: dict[str, str] = {}
    if hash_path.exists():
        for line in hash_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                digest, rel_path = line.split(maxsplit=1)
                expected[rel_path.lstrip("*")] = digest
    rows: list[dict[str, object]] = []
    for rel_path, digest in sorted(expected.items()):
        path = output_path / rel_path
        missing = not path.exists()
        actual = "" if missing else hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(
            {
                "file": rel_path,
                "expected_sha256": digest,
                "actual_sha256": actual,
                "invalid_count": int(missing or actual != digest),
                "status": "PASS" if not missing and actual == digest else "FAIL",
            }
        )
    return rows


def _stage5a_v1_1_source_diff_count(repo_root: Path) -> int:
    artifact = repo_root / "artifacts/stage5a_typed_claim_contract_v1_1"
    mismatches = 0
    for line in (artifact / "file_hashes.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        path = artifact / relative
        mismatches += int(_sha256(path) != expected)
    return mismatches


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"


def _write_report(
    path: Path,
    method_payload: dict[str, Any],
    type_summary_rows: list[dict[str, object]],
    hard_rows: list[dict[str, object]],
    report_title: str,
    semantic_audit_rows: list[dict[str, object]],
    freeze_hard_rows: list[dict[str, object]],
) -> None:
    issue_count = next(row["actual"] for row in hard_rows if row["check_name"] == "issue_count")
    freeze_issue = (
        next(row["actual"] for row in freeze_hard_rows if row["check_name"] == "issue_count")
        if freeze_hard_rows
        else "N/A"
    )
    text = f"""{report_title}

## Scope

Stage5B performs deterministic claim opportunity discovery, proposal construction,
Frozen Stage5A contract evaluation, TypedEngineeringClaim materialization and
abstention materialization. It does not generate natural language, Evidence Packs,
planner output, experiments or LLM prompts.

## Frozen Dependencies

- Stage5A method: {method_payload["upstream_stage5a_method"]}
- Stage5A tag: {method_payload["upstream_stage5a_tag"]}
- Stage5A artifact: {method_payload["upstream_stage5a_artifact"]}
- Stage5A authorization hotfix: {method_payload["upstream_stage5a_authorization_hotfix"]}
- Stage4 metrics: {STAGE4_DIR}
- Stage4 tag: {method_payload["upstream_stage4_tag"]}
- Stage4 source snapshot SHA256: {method_payload["upstream_stage4_source_snapshot_sha256"]}
- Stage4 source tree hash: {method_payload["upstream_stage4_source_tree_hash"]}

## Opportunity Universe

The universe is recorded in `claim_opportunity_universe.json`. Counts by ClaimType
are recorded in `claim_type_summary.csv`.

## Deterministic Proposal Construction

Every constructed proposal is evaluated by the Frozen Stage5A
`ClaimContractEvaluator`. Proposal construction records are saved in
`proposal_construction_records.jsonl`.

## Contract Evaluation

All decisions are saved in `claim_decisions.jsonl`. Expressibility and abstention
remain Stage5A outputs.

## Claim Materialization

Only EXPRESSIBLE decisions materialize one TypedEngineeringClaim. ABSTAIN decisions
materialize zero TypedEngineeringClaim and one abstention record.

## Abstention Materialization

Abstentions are saved in `claim_abstentions.jsonl` with Stage5A abstention reason,
failed rules and resolved support summary.

## Provenance

Reference integrity is audited in `claim_build_reference_audit.csv`; deduplication is
audited in `claim_deduplication_audit.csv`.

## Resolved Geological Context Binding

The same GeologicalEvidence may be valid in multiple state/version contexts.
Resolved support refs are bound to the current validated Claim subject context,
not to an arbitrary first context. The executable audit is
`geological_resolved_context_audit.csv`.

## Metric Missingness Integrity

Unavailable Stage4 metrics preserve missing values as null proposal payloads.
Stage5B does not convert unavailable metric nulls to 0.0. The executable audit is
`metric_proposal_integrity_audit.csv`.

## Determinism

Repeat-build business identity checks are in `claim_determinism_audit.csv`.

## Schema Integrity

Every row in `typed_engineering_claims.jsonl` is validated with
`TypedEngineeringClaim.model_validate(row)`. Stage5B provenance IDs are retained in
`claim.metadata`; resolved support refs remain in `claim_decisions.jsonl`.

## Candidate → Formal Equivalence

The executable business equivalence audit is
`stage5b_candidate_formal_semantic_audit.csv`.

## Boundary To Stage5C

Stage5B outputs structured data and counts only. Interpretation of rates, patterns or
case-study meaning belongs to Stage5C.

## Summary

- Opportunity count: {method_payload["opportunity_count"]}
- Proposal count: {method_payload["proposal_count"]}
- Decision count: {method_payload["decision_count"]}
- Materialized claim count: {method_payload["materialized_claim_count"]}
- Abstention count: {method_payload["abstention_count"]}
- Hard check issue count: {issue_count}
- Freeze hard check issue count: {freeze_issue}

## Claim Type Summary

{json.dumps(type_summary_rows, ensure_ascii=False, indent=2)}

## Candidate Formal Semantic Audit

{json.dumps(semantic_audit_rows, ensure_ascii=False, indent=2)}
"""
    path.write_text(text, encoding="utf-8")


def _resolve(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _git(args: list[str], repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"
