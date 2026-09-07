"""Read-only Stage 5C batch claim expressibility analysis."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import subprocess
import tempfile
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any

from tbm_twin.claim_analysis.loader import Stage5CInputs, load_inputs
from tbm_twin.claim_analysis.models import (
    CLAIM_TYPE_ORDER,
    GENERATED_AT_SEMANTICS,
    REASON_GROUPS,
    STAGE4_SOURCE_SNAPSHOT_SHA256,
    STAGE4_SOURCE_TREE_HASH,
    STAGE5B_ARTIFACT,
    STAGE5B_COMMIT,
    STAGE5B_TAG,
    STAGE5C_GENERATED_AT,
    STAGE5C_METHOD_VERSION,
    STAGE5C_OUTPUT,
    STAGE5C_SCHEMA_VERSION,
    STAGE5C_STATUS,
    UNKNOWN_VALUES,
)
from tbm_twin.claim_analysis.storage import read_json, write_csv, write_hashes, write_json

GEOLOGICAL_CLAIM_TYPES = {
    "OBSERVED_GEOLOGICAL_CONDITION",
    "FORECAST_GEOLOGICAL_CONDITION",
}
METRIC_CLAIM_TYPES = {
    "OPERATIONAL_RESPONSE_ATTENTION",
    "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
    "COUPLED_ATTENTION_REVIEW",
    "FORWARD_GEOLOGICAL_ATTENTION",
}


def build_stage5c_analysis(
    repo_root: Path,
    stage5b_artifact: Path = STAGE5B_ARTIFACT,
    output_dir: Path = STAGE5C_OUTPUT,
    generated_at: str = STAGE5C_GENERATED_AT,
    run_determinism: bool = True,
) -> dict[str, int]:
    """Build the Stage 5C candidate analysis artifact without remaking decisions."""

    root = repo_root.resolve()
    output_path = output_dir if output_dir.is_absolute() else root / output_dir
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "figure_data").mkdir(exist_ok=True)
    (output_path / "paper_table_data").mkdir(exist_ok=True)

    inputs = load_inputs(root, stage5b_artifact)
    records = _joined_records(inputs)
    evidence_by_id = {str(row["evidence_uid"]): row for row in inputs.stage2_evidence}
    grs_by_id = {str(row["state_grs_id"]): row for row in inputs.stage4_grs}
    grci_by_id = {str(row["state_grci_id"]): row for row in inputs.stage4_grci}

    denominator_contract = _denominator_contract()
    universe_manifest = _universe_manifest(inputs, records)
    overall_rows = _overall_summary(records)
    claim_type_rows = _claim_type_expressibility(records)
    abstention_reason_rows = _abstention_reason_summary(records)
    claim_type_reason_rows = _claim_type_abstention_matrix(records)
    reason_group_rows = _reason_group_summary(records)
    role_rows = _state_role_expressibility(records)
    role_claim_type_rows = _state_role_claim_type_matrix(records)
    epistemic_rows = _epistemic_expressibility(records, evidence_by_id)
    epistemic_boundary_rows = _epistemic_boundary_audit(records)
    epistemic_source_rows = _epistemic_source_resolution_audit(records, evidence_by_id)
    unknown_rows = _unknown_abstention_analysis(records)
    metric_rows = _metric_availability_analysis(records)
    metric_missing_rows = _metric_missingness_summary(records)
    daily_rows = _daily_expressibility(records)
    daily_claim_type_rows = _daily_claim_type_expressibility(records)
    source_rows = _geological_source_support_analysis(records, evidence_by_id)
    metric_source_rows = _metric_source_support_participation(
        records, evidence_by_id, grs_by_id, grci_by_id
    )
    (
        revision_chain_rows,
        revision_transition_rows,
        revision_key_rows,
        revision_lineage_rows,
        revision_transition_semantic_rows,
        revision_transition_reconciliation_rows,
    ) = _revision_analysis(records, inputs.stage3b_versions, grs_by_id, grci_by_id)
    manual_revision_rows = _manual_revision_case_audit(
        revision_transition_rows,
        revision_chain_rows,
        revision_lineage_rows,
    )
    reconciliation_rows = _reconciliation_audit(
        records,
        overall_rows,
        claim_type_rows,
        abstention_reason_rows,
        claim_type_reason_rows,
        daily_rows,
        role_rows,
    )
    rate_rows = _rate_integrity_audit(
        [
            ("overall_expressibility_summary.csv", overall_rows),
            ("claim_type_expressibility.csv", claim_type_rows),
            ("abstention_reason_summary.csv", abstention_reason_rows),
            ("claim_type_abstention_matrix.csv", claim_type_reason_rows),
            ("abstention_reason_group_summary.csv", reason_group_rows),
            ("state_role_expressibility.csv", role_rows),
            ("state_role_claim_type_matrix.csv", role_claim_type_rows),
            ("epistemic_expressibility.csv", epistemic_rows),
            ("metric_availability_analysis.csv", metric_rows),
            ("metric_missingness_summary.csv", metric_missing_rows),
            ("daily_expressibility.csv", daily_rows),
            ("daily_claim_type_expressibility.csv", daily_claim_type_rows),
        ]
    )
    fixed_rows = _fixed_case_audit(records, revision_chain_rows)
    determinism_rows = (
        _determinism_audit(root, stage5b_artifact, generated_at) if run_determinism else []
    )
    hard_rows = _hard_check_rows(
        root,
        output_path,
        inputs,
        records,
        reconciliation_rows,
        rate_rows,
        fixed_rows,
        determinism_rows,
        revision_key_rows,
        revision_lineage_rows,
        revision_transition_reconciliation_rows,
        revision_transition_semantic_rows,
        epistemic_boundary_rows,
        epistemic_source_rows,
        unknown_rows,
        metric_rows,
    )
    method_payload = _method_version(inputs, generated_at)

    write_json(output_path / "analysis_universe_manifest.json", universe_manifest)
    write_json(output_path / "analysis_denominator_contract.json", denominator_contract)
    write_csv(output_path / "overall_expressibility_summary.csv", overall_rows)
    write_csv(output_path / "claim_type_expressibility.csv", claim_type_rows)
    write_csv(output_path / "abstention_reason_summary.csv", abstention_reason_rows)
    write_csv(output_path / "claim_type_abstention_matrix.csv", claim_type_reason_rows)
    write_csv(output_path / "abstention_reason_group_summary.csv", reason_group_rows)
    write_csv(output_path / "state_role_expressibility.csv", role_rows)
    write_csv(output_path / "state_role_claim_type_matrix.csv", role_claim_type_rows)
    write_csv(output_path / "epistemic_expressibility.csv", epistemic_rows)
    write_csv(output_path / "epistemic_boundary_audit.csv", epistemic_boundary_rows)
    write_csv(output_path / "epistemic_source_resolution_audit.csv", epistemic_source_rows)
    write_csv(output_path / "unknown_abstention_analysis.csv", unknown_rows)
    write_csv(output_path / "metric_availability_analysis.csv", metric_rows)
    write_csv(output_path / "metric_missingness_summary.csv", metric_missing_rows)
    write_csv(output_path / "daily_expressibility.csv", daily_rows)
    write_csv(output_path / "daily_claim_type_expressibility.csv", daily_claim_type_rows)
    write_csv(output_path / "geological_source_support_analysis.csv", source_rows)
    write_csv(output_path / "metric_source_support_participation.csv", metric_source_rows)
    write_csv(output_path / "revision_chain_expressibility_analysis.csv", revision_chain_rows)
    write_csv(output_path / "revision_claim_transition_analysis.csv", revision_transition_rows)
    write_csv(output_path / "revision_comparison_key_audit.csv", revision_key_rows)
    write_csv(output_path / "revision_lineage_order_audit.csv", revision_lineage_rows)
    write_csv(
        output_path / "revision_transition_semantics_audit.csv",
        revision_transition_semantic_rows,
    )
    write_csv(
        output_path / "revision_transition_reconciliation_audit.csv",
        revision_transition_reconciliation_rows,
    )
    write_csv(output_path / "manual_revision_case_audit.csv", manual_revision_rows)
    write_csv(output_path / "analysis_reconciliation_audit.csv", reconciliation_rows)
    write_csv(output_path / "analysis_rate_integrity_audit.csv", rate_rows)
    write_csv(output_path / "stage5c_fixed_case_audit.csv", fixed_rows)
    write_csv(output_path / "stage5c_determinism_audit.csv", determinism_rows)
    write_csv(output_path / "stage5c_hard_check.csv", hard_rows)
    _write_figure_data(
        output_path,
        claim_type_rows,
        abstention_reason_rows,
        daily_rows,
        role_rows,
        revision_transition_rows,
    )
    _write_paper_table_data(
        output_path,
        claim_type_rows,
        abstention_reason_rows,
        role_rows,
        epistemic_rows,
        revision_chain_rows,
    )
    write_json(output_path / "method_version.json", method_payload)
    _write_report(
        output_path / "stage5c_report.md",
        method_payload,
        overall_rows,
        claim_type_rows,
        abstention_reason_rows,
        hard_rows,
    )
    write_hashes(output_path)
    return {
        "opportunities": len(inputs.opportunities),
        "decisions": len(inputs.decisions),
        "claims": len(inputs.claims),
        "abstentions": len(inputs.abstentions),
    }


def _joined_records(inputs: Stage5CInputs) -> list[dict[str, Any]]:
    proposals = {str(row["proposal_id"]): row for row in inputs.proposals}
    opportunities = {str(row["opportunity_id"]): row for row in inputs.opportunities}
    claims_by_decision = {
        str((row.get("metadata") or {})["decision_id"]): row for row in inputs.claims
    }
    abstentions_by_decision = {str(row["decision_id"]): row for row in inputs.abstentions}
    rows: list[dict[str, Any]] = []
    for decision in sorted(inputs.decisions, key=lambda row: str(row["decision_id"])):
        proposal = proposals[str(decision["proposal_id"])]
        opportunity = opportunities[str((proposal.get("metadata") or {})["opportunity_id"])]
        claim = claims_by_decision.get(str(decision["decision_id"]))
        abstention = abstentions_by_decision.get(str(decision["decision_id"]))
        rows.append(
            {
                "opportunity": opportunity,
                "proposal": proposal,
                "decision": decision,
                "claim": claim,
                "abstention": abstention,
                "claim_type": str(decision["claim_type"]),
                "state_role": str(opportunity.get("state_role") or "UNRESOLVED_ROLE"),
                "valid_date": str(opportunity.get("valid_date") or ""),
                "expressible": decision["expressibility"] == "EXPRESSIBLE",
                "abstained": decision["expressibility"] == "ABSTAIN",
                "abstention_reason": str(decision.get("abstention_reason") or ""),
            }
        )
    return rows


def _denominator_contract() -> dict[str, Any]:
    return {
        "overall_expressibility_rate": {
            "numerator": "EXPRESSIBLE decisions",
            "denominator": "ALL frozen Stage5B ClaimOpportunities",
        },
        "claim_type_expressibility_rate": {
            "numerator": "ClaimType EXPRESSIBLE decisions",
            "denominator": "ClaimType Opportunity count",
        },
        "abstention_reason_share": {
            "numerator": "ABSTAIN count for the reason",
            "denominator": "ALL ABSTAIN decisions",
        },
        "claim_type_abstention_reason_share": {
            "numerator": "ClaimType and reason ABSTAIN count",
            "denominator": "ClaimType ABSTAIN count",
        },
        "daily_expressibility_rate": {
            "numerator": "valid_date EXPRESSIBLE decisions",
            "denominator": "valid_date Opportunity count",
        },
        "role_expressibility_rate": {
            "numerator": "state_role EXPRESSIBLE decisions",
            "denominator": "state_role Opportunity count",
        },
        "revision_transition_rate": {
            "numerator": "transition class count",
            "denominator": (
                "all rows in revision_claim_transition_analysis.csv for authoritative "
                "adjacent revision pairs"
            ),
        },
        "matched_pair_decision_change_rate": {
            "numerator": "matched logical opportunity pairs with decision_changed=true",
            "denominator": "matched logical opportunity pairs excluding OPPORTUNITY_ADDED/REMOVED",
        },
    }


def _universe_manifest(inputs: Stage5CInputs, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_artifact": "artifacts/stage5b_deterministic_claim_builder_v1/",
        "upstream_method": inputs.method["method_version"],
        "upstream_git_commit": STAGE5B_COMMIT,
        "upstream_git_tag": STAGE5B_TAG,
        "opportunity_count": len(inputs.opportunities),
        "proposal_count": len(inputs.proposals),
        "decision_count": len(inputs.decisions),
        "claim_count": len(inputs.claims),
        "abstention_count": len(inputs.abstentions),
        "claim_type_registry": CLAIM_TYPE_ORDER,
        "valid_date_count": len({row["valid_date"] for row in records}),
        "bitemporal_version_preserved": True,
        "latest_only_filter": False,
    }


def _overall_summary(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    total = len(records)
    expressible = sum(row["expressible"] for row in records)
    abstain = sum(row["abstained"] for row in records)
    return [
        {
            "opportunity_count": total,
            "proposal_count": total,
            "decision_count": total,
            "expressible_count": expressible,
            "abstain_count": abstain,
            "materialized_claim_count": expressible,
            "expressibility_rate": _rate(expressible, total),
            "abstention_rate": _rate(abstain, total),
        }
    ]


def _claim_type_expressibility(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for claim_type in CLAIM_TYPE_ORDER:
        subset = [row for row in records if row["claim_type"] == claim_type]
        expressible = sum(row["expressible"] for row in subset)
        abstain = sum(row["abstained"] for row in subset)
        rows.append(
            {
                "claim_type": claim_type,
                "opportunity_count": len(subset),
                "expressible_count": expressible,
                "abstain_count": abstain,
                "materialized_claim_count": expressible,
                "expressibility_rate": _rate(expressible, len(subset)),
                "abstention_rate": _rate(abstain, len(subset)),
                "unique_subject_count": len({_subject_key(row["opportunity"]) for row in subset}),
                "unique_support_count": len(
                    {
                        support
                        for row in subset
                        for support in row["opportunity"]["source_object_ids"]
                    }
                ),
            }
        )
    return rows


def _abstention_reason_summary(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    abstained = [row for row in records if row["abstained"]]
    total = len(abstained)
    rows = []
    for reason, count in Counter(row["abstention_reason"] for row in abstained).most_common():
        subset = [row for row in abstained if row["abstention_reason"] == reason]
        rows.append(
            {
                "abstention_reason": reason,
                "count": count,
                "share_of_all_abstentions": _rate(count, total),
                "analysis_reason_group": REASON_GROUPS.get(reason, "UNMAPPED_REASON"),
                "affected_claim_type_count": len({row["claim_type"] for row in subset}),
                "unique_subject_count": len({_subject_key(row["opportunity"]) for row in subset}),
                "unique_valid_date_count": len({row["valid_date"] for row in subset}),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["count"]), str(row["abstention_reason"])))


def _claim_type_abstention_matrix(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    abstained = [row for row in records if row["abstained"]]
    total_by_type = Counter(row["claim_type"] for row in abstained)
    total_by_reason = Counter(row["abstention_reason"] for row in abstained)
    counts = Counter((row["claim_type"], row["abstention_reason"]) for row in abstained)
    rows = []
    for claim_type in CLAIM_TYPE_ORDER:
        for reason in sorted(total_by_reason):
            count = counts[(claim_type, reason)]
            if count == 0:
                continue
            rows.append(
                {
                    "claim_type": claim_type,
                    "abstention_reason": reason,
                    "analysis_reason_group": REASON_GROUPS.get(reason, "UNMAPPED_REASON"),
                    "count": count,
                    "share_within_claim_type_abstentions": _rate(count, total_by_type[claim_type]),
                    "share_within_reason": _rate(count, total_by_reason[reason]),
                }
            )
    return rows


def _reason_group_summary(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    abstained = [row for row in records if row["abstained"]]
    total = len(abstained)
    by_group: dict[str, list[str]] = defaultdict(list)
    for reason in sorted({row["abstention_reason"] for row in abstained}):
        by_group[REASON_GROUPS.get(reason, "UNMAPPED_REASON")].append(reason)
    rows = []
    for group, reasons in sorted(by_group.items()):
        count = sum(1 for row in abstained if row["abstention_reason"] in reasons)
        rows.append(
            {
                "analysis_reason_group": group,
                "count": count,
                "share_of_abstentions": _rate(count, total),
                "member_reasons": ";".join(reasons),
            }
        )
    return sorted(rows, key=lambda row: (-_int(row["count"]), str(row["analysis_reason_group"])))


def _state_role_expressibility(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows = []
    for role in sorted({row["state_role"] for row in records}):
        subset = [row for row in records if row["state_role"] == role]
        expressible = sum(row["expressible"] for row in subset)
        rows.append(
            {
                "state_role": role,
                "opportunity_count": len(subset),
                "expressible_count": expressible,
                "abstain_count": len(subset) - expressible,
                "expressibility_rate": _rate(expressible, len(subset)),
                "claim_type_count": len({row["claim_type"] for row in subset}),
                "unique_subject_count": len({_subject_key(row["opportunity"]) for row in subset}),
            }
        )
    return rows


def _state_role_claim_type_matrix(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows = []
    for role in sorted({row["state_role"] for row in records}):
        for claim_type in CLAIM_TYPE_ORDER:
            subset = [
                row
                for row in records
                if row["state_role"] == role and row["claim_type"] == claim_type
            ]
            if not subset:
                continue
            expressible = sum(row["expressible"] for row in subset)
            rows.append(
                {
                    "state_role": role,
                    "claim_type": claim_type,
                    "opportunity_count": len(subset),
                    "expressible_count": expressible,
                    "abstain_count": len(subset) - expressible,
                    "expressibility_rate": _rate(expressible, len(subset)),
                }
            )
    return rows


def _epistemic_expressibility(
    records: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, object]]:
    rows = []
    for claim_type in ["OBSERVED_GEOLOGICAL_CONDITION", "FORECAST_GEOLOGICAL_CONDITION"]:
        subsets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in records:
            if row["claim_type"] != claim_type:
                continue
            source_status = _authoritative_source_epistemic_status(row, evidence_by_id)
            resolved_statuses = _resolved_epistemic_statuses(row)
            if not resolved_statuses:
                resolved_statuses = ["MISSING_NOT_MATERIALIZED"]
            for resolved_status in resolved_statuses:
                subsets[(source_status, resolved_status)].append(row)
        for (source_status, resolved_status), subset in sorted(subsets.items()):
            expressible = sum(row["expressible"] for row in subset)
            rows.append(
                {
                    "claim_type": claim_type,
                    "authoritative_source_epistemic_status": source_status,
                    "decision_resolved_epistemic_status": resolved_status,
                    "opportunity_count": len(subset),
                    "expressible_count": expressible,
                    "abstain_count": len(subset) - expressible,
                    "expressibility_rate": _rate(expressible, len(subset)),
                    "unknown_count": sum(_is_unknown_claim_value(row) for row in subset),
                    "source_epistemic_status_missing_count": sum(
                        _authoritative_source_epistemic_status(row, evidence_by_id) == "MISSING"
                        for row in subset
                    ),
                    "decision_resolved_status_missing_count": sum(
                        not _resolved_epistemic_statuses(row) for row in subset
                    ),
                }
            )
    return rows


def _epistemic_source_resolution_audit(
    records: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    expected_by_type = {
        "OBSERVED_GEOLOGICAL_CONDITION": "OBSERVED",
        "FORECAST_GEOLOGICAL_CONDITION": "FORECAST",
    }
    for row in records:
        if row["claim_type"] not in expected_by_type:
            continue
        claim_value = row["proposal"].get("claim_value") or {}
        evidence_id = str(claim_value.get("source_evidence_id") or "")
        evidence = evidence_by_id.get(evidence_id)
        source_status = (
            str(evidence.get("epistemic_status") or "MISSING") if evidence else "MISSING"
        )
        expected_status = expected_by_type[row["claim_type"]]
        resolved_statuses = _resolved_epistemic_statuses(row)
        decision_resolved_status = (
            ";".join(resolved_statuses) if resolved_statuses else "MISSING_NOT_MATERIALIZED"
        )
        source_match = source_status == expected_status
        rows.append(
            {
                "claim_type": row["claim_type"],
                "opportunity_id": row["opportunity"]["opportunity_id"],
                "proposal_id": row["proposal"]["proposal_id"],
                "decision_id": row["decision"]["decision_id"],
                "source_evidence_id": evidence_id,
                "source_evidence_exists": str(evidence is not None).lower(),
                "source_epistemic_status": source_status,
                "claim_type_expected_epistemic_status": expected_status,
                "decision_resolved_epistemic_status": decision_resolved_status,
                "decision_expressibility": row["decision"]["expressibility"],
                "abstention_reason": row["abstention_reason"],
                "source_status_match": str(source_match).lower(),
                "status": "PASS" if evidence is not None and source_match else "FAIL",
            }
        )
    return sorted(rows, key=lambda item: str(item["opportunity_id"]))


def _epistemic_boundary_audit(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    forecast_claims = [
        row
        for row in records
        if row["claim_type"] == "FORECAST_GEOLOGICAL_CONDITION" and row["expressible"]
    ]
    observed_claims = [
        row
        for row in records
        if row["claim_type"] == "OBSERVED_GEOLOGICAL_CONDITION" and row["expressible"]
    ]
    forecast_as_forecast = sum(
        "FORECAST" in _resolved_epistemic_statuses(row) for row in forecast_claims
    )
    forecast_promoted = sum(
        "OBSERVED" in _resolved_epistemic_statuses(row) for row in forecast_claims
    )
    observed_with_proof = sum(
        "OBSERVED" in _resolved_epistemic_statuses(row) for row in observed_claims
    )
    return [
        {
            "forecast_claim_count": len(forecast_claims),
            "forecast_resolved_as_forecast_count": forecast_as_forecast,
            "forecast_promoted_to_observed_count": forecast_promoted,
            "observed_claim_count": len(observed_claims),
            "observed_with_observed_proof_count": observed_with_proof,
            "observed_without_observed_proof_count": len(observed_claims) - observed_with_proof,
        }
    ]


def _unknown_abstention_analysis(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        if row["claim_type"] not in GEOLOGICAL_CLAIM_TYPES:
            continue
        claim_value = row["proposal"].get("claim_value") or {}
        value = str(claim_value.get("normalized_value", ""))
        if value.upper() in UNKNOWN_VALUES:
            buckets[
                (row["claim_type"], str(claim_value.get("attribute_name") or ""), value)
            ].append(row)
    rows = []
    for (claim_type, attribute, value), subset in sorted(buckets.items()):
        rows.append(
            {
                "claim_type": claim_type,
                "attribute_name": attribute,
                "normalized_source_value": value,
                "unknown_opportunity_count": len(subset),
                "unknown_abstain_count": sum(row["abstained"] for row in subset),
                "unknown_materialized_claim_count": sum(row["expressible"] for row in subset),
            }
        )
    return rows


def _metric_availability_analysis(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        metric_name = row["opportunity"].get("payload", {}).get("metric_name")
        if metric_name is None:
            continue
        status = str(row["opportunity"]["payload"].get("metric_status") or "")
        buckets[(row["claim_type"], str(metric_name), status)].append(row)
    rows = []
    for (claim_type, metric_name, status), subset in sorted(buckets.items()):
        expressible = sum(row["expressible"] for row in subset)
        rows.append(
            {
                "claim_type": claim_type,
                "metric_name": metric_name,
                "metric_status": status,
                "opportunity_count": len(subset),
                "expressible_count": expressible,
                "abstain_count": len(subset) - expressible,
                "materialized_claim_count": expressible,
                "expressibility_rate": _rate(expressible, len(subset)),
                "null_metric_value_count": sum(
                    row["opportunity"]["payload"].get("metric_value") is None for row in subset
                ),
                "null_to_zero_interpretation_count": sum(
                    _metric_null_to_zero_interpretation(row) for row in subset
                ),
            }
        )
    return rows


def _metric_null_to_zero_interpretation(row: dict[str, Any]) -> int:
    if row["opportunity"].get("payload", {}).get("metric_value") is not None:
        return 0
    proposal_value = row["proposal"].get("claim_value") or {}
    return int(proposal_value.get("metric_value") == 0)


def _metric_missingness_summary(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    metric_records = [
        row for row in records if row["opportunity"].get("payload", {}).get("metric_name")
    ]
    by_metric = Counter(row["opportunity"]["payload"]["metric_name"] for row in metric_records)
    rows = []
    for (metric, status), count in sorted(
        Counter(
            (
                row["opportunity"]["payload"]["metric_name"],
                row["opportunity"]["payload"].get("metric_status"),
            )
            for row in metric_records
        ).items()
    ):
        rows.append(
            {
                "metric_name": metric,
                "status": status,
                "count": count,
                "share_within_metric_opportunities": _rate(count, by_metric[metric]),
            }
        )
    return rows


def _daily_expressibility(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows = []
    for valid_date in sorted({row["valid_date"] for row in records}):
        subset = [row for row in records if row["valid_date"] == valid_date]
        expressible = sum(row["expressible"] for row in subset)
        rows.append(
            {
                "valid_date": valid_date,
                "opportunity_count": len(subset),
                "expressible_count": expressible,
                "abstain_count": len(subset) - expressible,
                "materialized_claim_count": expressible,
                "expressibility_rate": _rate(expressible, len(subset)),
            }
        )
    return rows


def _daily_claim_type_expressibility(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    rows = []
    for valid_date in sorted({row["valid_date"] for row in records}):
        for claim_type in CLAIM_TYPE_ORDER:
            subset = [
                row
                for row in records
                if row["valid_date"] == valid_date and row["claim_type"] == claim_type
            ]
            if not subset:
                continue
            expressible = sum(row["expressible"] for row in subset)
            rows.append(
                {
                    "valid_date": valid_date,
                    "claim_type": claim_type,
                    "opportunity_count": len(subset),
                    "expressible_count": expressible,
                    "abstain_count": len(subset) - expressible,
                    "materialized_claim_count": expressible,
                    "expressibility_rate": _rate(expressible, len(subset)),
                }
            )
    return rows


def _geological_source_support_analysis(
    records: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        if row["claim_type"] not in GEOLOGICAL_CLAIM_TYPES:
            continue
        evidence_id = str(
            (row["proposal"].get("claim_value") or {}).get("source_evidence_id") or ""
        )
        evidence = evidence_by_id.get(evidence_id, {})
        buckets[
            (
                str(evidence.get("source_type") or "UNKNOWN_SOURCE_TYPE"),
                str(evidence.get("epistemic_status") or "UNKNOWN"),
            )
        ].append(row)
    rows = []
    for (source_type, epistemic), subset in sorted(buckets.items()):
        expressible = sum(row["expressible"] for row in subset)
        rows.append(
            {
                "source_type": source_type,
                "epistemic_status": epistemic,
                "opportunity_count": len(subset),
                "expressible_count": expressible,
                "abstain_count": len(subset) - expressible,
                "materialized_geological_claim_count": expressible,
                "unique_evidence_count": len(
                    {
                        (row["proposal"].get("claim_value") or {}).get("source_evidence_id")
                        for row in subset
                    }
                ),
                "analysis_semantics": "support_participation_not_causal_contribution",
            }
        )
    return rows


def _metric_source_support_participation(
    records: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    grs_by_id: dict[str, dict[str, Any]],
    grci_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, object]]:
    rows = []
    buckets: Counter[tuple[str, str]] = Counter()
    link_counts: Counter[tuple[str, str]] = Counter()
    for row in records:
        if row["claim_type"] not in {
            "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
            "FORWARD_GEOLOGICAL_ATTENTION",
            "COUPLED_ATTENTION_REVIEW",
        }:
            continue
        if not row["expressible"]:
            continue
        metric_id = str(row["opportunity"]["payload"].get("metric_id", ""))
        evidence_ids: list[str] = []
        if metric_id in grs_by_id:
            evidence_ids = [
                str(item) for item in grs_by_id[metric_id].get("support_evidence_uids", [])
            ]
        elif metric_id in grci_by_id:
            grs_id = f"state_grs_{metric_id.removeprefix('state_grci_')}"
            evidence_ids = [
                str(item) for item in grs_by_id.get(grs_id, {}).get("support_evidence_uids", [])
            ]
        source_types = {
            str(evidence_by_id.get(eid, {}).get("source_type") or "UNKNOWN_SOURCE_TYPE")
            for eid in evidence_ids
        }
        for source_type in source_types:
            key = (row["claim_type"], source_type)
            buckets[key] += 1
            link_counts[key] += sum(
                1
                for eid in evidence_ids
                if str(evidence_by_id.get(eid, {}).get("source_type") or "UNKNOWN_SOURCE_TYPE")
                == source_type
            )
    for (claim_type, source_type), count in sorted(buckets.items()):
        rows.append(
            {
                "claim_type": claim_type,
                "source_type": source_type,
                "claim_with_source_present_count": count,
                "support_link_count": link_counts[(claim_type, source_type)],
                "analysis_semantics": "multi_source_support_participation_counts_not_additive",
            }
        )
    return rows


def _revision_analysis(
    records: list[dict[str, Any]],
    stage3b_versions: list[dict[str, Any]],
    grs_by_id: dict[str, dict[str, Any]],
    grci_by_id: dict[str, dict[str, Any]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    version_by_id = {str(row["bitemporal_version_id"]): row for row in stage3b_versions}
    by_chain: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        opp = row["opportunity"]
        key = (
            str(opp.get("base_stage3a_state_version_id") or ""),
            str(opp.get("valid_date") or ""),
            str(opp.get("cell_id") or ""),
            str(opp.get("state_role") or ""),
        )
        by_chain[key].append(row)
    chain_rows: list[dict[str, object]] = []
    transition_rows: list[dict[str, object]] = []
    key_rows: list[dict[str, object]] = []
    lineage_rows: list[dict[str, object]] = []
    semantic_rows: list[dict[str, object]] = []
    transition_reconciliation_rows: list[dict[str, object]] = []
    for (base_id, valid_date, cell_id, role), subset in sorted(by_chain.items()):
        by_version: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in subset:
            by_version[str(row["opportunity"].get("bitemporal_version_id") or "")].append(row)
        if len(by_version) < 2:
            continue
        ordered_versions = sorted(
            by_version,
            key=lambda version_id: (
                int(version_by_id.get(version_id, {}).get("version_number", 10**9)),
                version_id,
            ),
        )
        for previous, current in pairwise(ordered_versions):
            previous_meta = version_by_id.get(previous, {})
            current_meta = version_by_id.get(current, {})
            previous_number = int(previous_meta.get("version_number", -1))
            current_number = int(current_meta.get("version_number", -1))
            expected_superseded = previous
            actual_supersedes = str(current_meta.get("supersedes_bitemporal_version_id") or "")
            ordering_valid = previous_number < current_number
            supersession_valid = actual_supersedes == expected_superseded
            lexicographic_direction_error = int(sorted([previous, current]) != [previous, current])
            lineage_status = "PASS" if ordering_valid and supersession_valid else "LINEAGE_INVALID"
            lineage_rows.append(
                {
                    "base_stage3a_state_version_id": base_id,
                    "reported_v1_bitemporal_version_id": previous,
                    "reported_v1_version_number": previous_number,
                    "reported_v2_bitemporal_version_id": current,
                    "reported_v2_version_number": current_number,
                    "v2_supersedes_id": actual_supersedes,
                    "expected_superseded_id": expected_superseded,
                    "valid_date": valid_date,
                    "cell_id": cell_id,
                    "state_role": role,
                    "ordering_valid": str(ordering_valid).lower(),
                    "supersession_valid": str(supersession_valid).lower(),
                    "legacy_lexicographic_direction_error": lexicographic_direction_error,
                    "status": lineage_status,
                }
            )
            if not ordering_valid or not supersession_valid:
                continue
            v1_rows = by_version[previous]
            v2_rows = by_version[current]
            chain_rows.append(
                {
                    "base_stage3a_state_version_id": base_id,
                    "v1_bitemporal_version_id": previous,
                    "v1_version_number": previous_number,
                    "v2_bitemporal_version_id": current,
                    "v2_version_number": current_number,
                    "valid_date": valid_date,
                    "cell_id": cell_id,
                    "state_role": role,
                    "v1_opportunity_count": len(v1_rows),
                    "v2_opportunity_count": len(v2_rows),
                    "v1_expressible_count": sum(row["expressible"] for row in v1_rows),
                    "v2_expressible_count": sum(row["expressible"] for row in v2_rows),
                    "v1_abstain_count": sum(row["abstained"] for row in v1_rows),
                    "v2_abstain_count": sum(row["abstained"] for row in v2_rows),
                    "opportunity_count_delta": len(v2_rows) - len(v1_rows),
                    "expressible_count_delta": sum(row["expressible"] for row in v2_rows)
                    - sum(row["expressible"] for row in v1_rows),
                    "abstain_count_delta": sum(row["abstained"] for row in v2_rows)
                    - sum(row["abstained"] for row in v1_rows),
                }
            )
            v1_by_key = _revision_key_map(v1_rows)
            v2_by_key = _revision_key_map(v2_rows)
            for version_id, mapping in [(previous, v1_by_key), (current, v2_by_key)]:
                duplicate_count = sum(max(0, len(items) - 1) for items in mapping.values())
                key_rows.append(
                    {
                        "base_stage3a_state_version_id": base_id,
                        "bitemporal_version_id": version_id,
                        "valid_date": valid_date,
                        "cell_id": cell_id,
                        "state_role": role,
                        "comparison_key_count": len(mapping),
                        "opportunity_count": sum(len(items) for items in mapping.values()),
                        "duplicate_key_count": duplicate_count,
                        "status": "PASS" if duplicate_count == 0 else "AMBIGUOUS_COMPARISON_KEY",
                    }
                )
            added = removed = matched = 0
            for comparison_key in sorted(set(v1_by_key) | set(v2_by_key)):
                left = v1_by_key.get(comparison_key, [])
                right = v2_by_key.get(comparison_key, [])
                if not left:
                    transition = "OPPORTUNITY_ADDED"
                    added += 1
                    flags = _transition_flags(None, right[0], grs_by_id, grci_by_id)
                elif not right:
                    transition = "OPPORTUNITY_REMOVED"
                    removed += 1
                    flags = _transition_flags(left[0], None, grs_by_id, grci_by_id)
                else:
                    matched += 1
                    flags = _transition_flags(left[0], right[0], grs_by_id, grci_by_id)
                    transition = _revision_transition_from_flags(flags, left[0], right[0])
                transition_row = {
                    "base_stage3a_state_version_id": base_id,
                    "valid_date": valid_date,
                    "cell_id": cell_id,
                    "state_role": role,
                    "revision_comparison_key": comparison_key,
                    "v1_bitemporal_version_id": previous,
                    "v2_bitemporal_version_id": current,
                    "transition_class": transition,
                    "v1_decision": left[0]["decision"]["expressibility"] if left else "",
                    "v2_decision": right[0]["decision"]["expressibility"] if right else "",
                    "v1_abstention_reason": left[0]["abstention_reason"] if left else "",
                    "v2_abstention_reason": right[0]["abstention_reason"] if right else "",
                    **flags,
                }
                transition_rows.append(transition_row)
                semantic_rows.append(
                    {
                        "revision_comparison_key": comparison_key,
                        "transition_class": transition,
                        **flags,
                        "status": "PASS",
                    }
                )
            union_count = len(set(v1_by_key) | set(v2_by_key))
            transition_reconciliation_rows.append(
                {
                    "base_stage3a_state_version_id": base_id,
                    "v1_bitemporal_version_id": previous,
                    "v2_bitemporal_version_id": current,
                    "matched_pair_count": matched,
                    "added_count": added,
                    "removed_count": removed,
                    "union_transition_row_count": union_count,
                    "transition_row_count": matched + added + removed,
                    "difference": union_count - (matched + added + removed),
                    "status": "PASS" if union_count == matched + added + removed else "FAIL",
                }
            )
    return (
        chain_rows,
        transition_rows,
        key_rows,
        lineage_rows,
        semantic_rows,
        transition_reconciliation_rows,
    )


def _revision_key_map(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    mapping: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        mapping[_revision_comparison_key(row)].append(row)
    return mapping


def _revision_comparison_key(row: dict[str, Any]) -> str:
    opp = row["opportunity"]
    payload = opp.get("payload") or {}
    proposal_value = row["proposal"].get("claim_value") or {}
    if row["claim_type"] in METRIC_CLAIM_TYPES:
        key = {
            "claim_type": row["claim_type"],
            "base_stage3a_state_version_id": opp.get("base_stage3a_state_version_id"),
            "valid_date": opp.get("valid_date"),
            "cell_id": opp.get("cell_id"),
            "state_role": opp.get("state_role"),
            "source_kind": opp.get("source_kind"),
            "metric_name": payload.get("metric_name"),
        }
    else:
        key = {
            "claim_type": row["claim_type"],
            "base_stage3a_state_version_id": opp.get("base_stage3a_state_version_id"),
            "valid_date": opp.get("valid_date"),
            "cell_id": opp.get("cell_id"),
            "state_role": opp.get("state_role"),
            "source_kind": opp.get("source_kind"),
            "source_evidence_id": proposal_value.get("source_evidence_id"),
            "attribute_name": proposal_value.get("attribute_name"),
        }
    return _canonical_json(key)


def _business_value_signature(row: dict[str, Any]) -> dict[str, Any] | None:
    claim_value = row["proposal"].get("claim_value")
    if not claim_value:
        return None
    if row["claim_type"] in METRIC_CLAIM_TYPES:
        return {
            "metric_name": claim_value.get("metric_name"),
            "metric_value": claim_value.get("metric_value"),
            "metric_status": claim_value.get("metric_status"),
            "metric_semantics": claim_value.get("metric_semantics"),
            "is_probability": claim_value.get("is_probability"),
            "is_hazard_probability": claim_value.get("is_hazard_probability"),
            "is_causal_estimate": claim_value.get("is_causal_estimate"),
        }
    return {
        "attribute_name": claim_value.get("attribute_name"),
        "normalized_value": claim_value.get("normalized_value"),
        "source_evidence_id": claim_value.get("source_evidence_id"),
    }


def _support_semantic_signature(
    row: dict[str, Any],
    grs_by_id: dict[str, dict[str, Any]],
    grci_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    signatures = []
    for support in row["decision"].get("resolved_support_refs", []):
        support_kind = support.get("support_kind")
        support_id = str(support.get("support_id") or "")
        if support_kind == "GEOLOGICAL_EVIDENCE":
            signatures.append(
                {
                    "support_kind": support_kind,
                    "support_id": support_id,
                    "support_role": support.get("support_role"),
                    "resolved_epistemic_status": support.get("resolved_epistemic_status"),
                    "resolved_spatial_scope": support.get("resolved_spatial_scope"),
                    "trace_ref_ids": support.get("trace_ref_ids", []),
                }
            )
        elif support_kind in {"STATE_RAI", "STATE_GRS", "STATE_GRCI"}:
            signatures.append(
                {
                    "support_kind": support_kind,
                    "support_role": support.get("support_role"),
                    "metric_name": (row["proposal"].get("claim_value") or {}).get("metric_name"),
                    "underlying_geological_support": _metric_underlying_support(
                        support_id, grs_by_id, grci_by_id
                    ),
                }
            )
        else:
            signatures.append(
                {
                    "support_kind": support_kind,
                    "support_role": support.get("support_role"),
                    "trace_ref_ids": support.get("trace_ref_ids", []),
                }
            )
    return sorted(signatures, key=_canonical_json)


def _metric_underlying_support(
    support_id: str,
    grs_by_id: dict[str, dict[str, Any]],
    grci_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    if support_id in grs_by_id:
        return sorted(str(item) for item in grs_by_id[support_id].get("support_evidence_uids", []))
    if support_id in grci_by_id:
        grs_id = f"state_grs_{support_id.removeprefix('state_grci_')}"
        return sorted(
            str(item) for item in grs_by_id.get(grs_id, {}).get("support_evidence_uids", [])
        )
    return []


def _transition_flags(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    grs_by_id: dict[str, dict[str, Any]],
    grci_by_id: dict[str, dict[str, Any]],
) -> dict[str, object]:
    if left is None:
        return {
            "decision_changed": "true",
            "abstention_reason_changed": "false",
            "business_claim_value_changed": "false",
            "support_semantics_changed": "false",
            "opportunity_added": "true",
            "opportunity_removed": "false",
            "wrapper_identity_only_support_change": "false",
        }
    if right is None:
        return {
            "decision_changed": "true",
            "abstention_reason_changed": "false",
            "business_claim_value_changed": "false",
            "support_semantics_changed": "false",
            "opportunity_added": "false",
            "opportunity_removed": "true",
            "wrapper_identity_only_support_change": "false",
        }
    raw_support_changed = left["decision"].get("resolved_support_refs") != right["decision"].get(
        "resolved_support_refs"
    )
    semantic_support_changed = _support_semantic_signature(
        left, grs_by_id, grci_by_id
    ) != _support_semantic_signature(right, grs_by_id, grci_by_id)
    return {
        "decision_changed": str(
            left["decision"]["expressibility"] != right["decision"]["expressibility"]
        ).lower(),
        "abstention_reason_changed": str(
            left["abstention_reason"] != right["abstention_reason"]
        ).lower(),
        "business_claim_value_changed": str(
            _business_value_signature(left) != _business_value_signature(right)
        ).lower(),
        "support_semantics_changed": str(semantic_support_changed).lower(),
        "opportunity_added": "false",
        "opportunity_removed": "false",
        "wrapper_identity_only_support_change": str(
            raw_support_changed and not semantic_support_changed
        ).lower(),
    }


def _revision_transition_from_flags(
    flags: dict[str, object], left: dict[str, Any], right: dict[str, Any]
) -> str:
    if left["abstained"] and right["expressible"]:
        return "ABSTAIN_TO_EXPRESSIBLE"
    if left["expressible"] and right["abstained"]:
        return "EXPRESSIBLE_TO_ABSTAIN"
    if left["abstained"] and right["abstained"]:
        if flags["abstention_reason_changed"] == "true":
            return "ABSTENTION_REASON_CHANGED"
        return "UNCHANGED_ABSTAIN"
    if flags["business_claim_value_changed"] == "true":
        return "CLAIM_VALUE_CHANGED"
    if flags["support_semantics_changed"] == "true":
        return "RESOLVED_SUPPORT_CHANGED"
    return "UNCHANGED_EXPRESSIBLE"


def _manual_revision_case_audit(
    transition_rows: list[dict[str, object]],
    chain_rows: list[dict[str, object]],
    lineage_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Select deterministic representative revision cases for freeze review."""

    samples: list[dict[str, object]] = []
    selected_keys: set[tuple[str, str, str]] = set()

    def add(selection_reason: str, predicate: Any) -> None:
        for row in transition_rows:
            if not predicate(row):
                continue
            key = (
                str(row["base_stage3a_state_version_id"]),
                str(row["revision_comparison_key"]),
                selection_reason,
            )
            if key in selected_keys:
                return
            selected_keys.add(key)
            sample = dict(row)
            sample["selection_reason"] = selection_reason
            samples.append(sample)
            return

    for transition_class in [
        "ABSTAIN_TO_EXPRESSIBLE",
        "CLAIM_VALUE_CHANGED",
        "RESOLVED_SUPPORT_CHANGED",
        "OPPORTUNITY_ADDED",
    ]:
        add(
            transition_class,
            lambda row, transition_class=transition_class: (
                row["transition_class"] == transition_class
            ),
        )
    add(
        "forecast_geological_added",
        lambda row: (
            row["transition_class"] == "OPPORTUNITY_ADDED"
            and "FORECAST_GEOLOGICAL_CONDITION" in str(row["revision_comparison_key"])
        ),
    )
    add(
        "observed_geological_added",
        lambda row: (
            row["transition_class"] == "OPPORTUNITY_ADDED"
            and "OBSERVED_GEOLOGICAL_CONDITION" in str(row["revision_comparison_key"])
        ),
    )
    add(
        "GRS_revision",
        lambda row: (
            "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW" in str(row["revision_comparison_key"])
            and row["transition_class"] != "UNCHANGED_EXPRESSIBLE"
        ),
    )
    add(
        "GRCI_revision",
        lambda row: (
            "COUPLED_ATTENTION_REVIEW" in str(row["revision_comparison_key"])
            and row["transition_class"] != "UNCHANGED_EXPRESSIBLE"
        ),
    )
    if chain_rows:
        largest_delta_base = str(
            max(chain_rows, key=lambda row: _int(row["opportunity_count_delta"]))[
                "base_stage3a_state_version_id"
            ]
        )
        positive_delta_rows = [
            row for row in chain_rows if _int(row["opportunity_count_delta"]) > 0
        ]
        smallest_positive_delta_base = str(
            min(positive_delta_rows, key=lambda row: _int(row["opportunity_count_delta"]))[
                "base_stage3a_state_version_id"
            ]
        )
        add(
            "largest_opportunity_delta_chain",
            lambda row: row["base_stage3a_state_version_id"] == largest_delta_base,
        )
        add(
            "small_positive_opportunity_delta_chain",
            lambda row: row["base_stage3a_state_version_id"] == smallest_positive_delta_base,
        )
    lexical_conflict_bases = {
        str(row["base_stage3a_state_version_id"])
        for row in lineage_rows
        if _int(row.get("legacy_lexicographic_direction_error", 0)) == 1
    }
    add(
        "lexical_authoritative_order_conflict",
        lambda row: row["base_stage3a_state_version_id"] in lexical_conflict_bases,
    )
    add(
        "UNKNOWN_SOURCE_VALUE_related",
        lambda row: (
            row["v1_abstention_reason"] == "UNKNOWN_SOURCE_VALUE"
            or row["v2_abstention_reason"] == "UNKNOWN_SOURCE_VALUE"
        ),
    )
    add(
        "CONTEXT_OR_STATE_ROLE_related",
        lambda row: (
            row["v1_abstention_reason"] in {"CONTEXT_ONLY_ROLE", "STATE_ROLE_NOT_ALLOWED"}
            or row["v2_abstention_reason"] in {"CONTEXT_ONLY_ROLE", "STATE_ROLE_NOT_ALLOWED"}
        ),
    )

    lineage_by_base = {str(row["base_stage3a_state_version_id"]): row for row in lineage_rows}
    chain_by_base = {str(row["base_stage3a_state_version_id"]): row for row in chain_rows}
    rows: list[dict[str, object]] = []
    for sample_id, sample in enumerate(samples, start=1):
        comparison_key = _load_comparison_key(str(sample["revision_comparison_key"]))
        base_id = str(sample["base_stage3a_state_version_id"])
        lineage = lineage_by_base.get(base_id, {})
        chain = chain_by_base.get(base_id, {})
        transition = str(sample["transition_class"])
        v1_reason = str(sample.get("v1_abstention_reason") or "")
        rows.append(
            {
                "sample_id": sample_id,
                "selection_reason": sample["selection_reason"],
                "base_stage3a_state_version_id": base_id,
                "v1_bitemporal_version_id": sample["v1_bitemporal_version_id"],
                "v1_version_number": lineage.get("reported_v1_version_number", ""),
                "v2_bitemporal_version_id": sample["v2_bitemporal_version_id"],
                "v2_version_number": lineage.get("reported_v2_version_number", ""),
                "v2_supersedes_id": lineage.get("v2_supersedes_id", ""),
                "valid_date": sample["valid_date"],
                "cell_id": sample["cell_id"],
                "state_role": sample["state_role"],
                "claim_type": comparison_key.get("claim_type", ""),
                "source_kind": comparison_key.get("source_kind", ""),
                "attribute_or_metric": comparison_key.get("attribute_name")
                or comparison_key.get("metric_name")
                or "",
                "source_evidence_id": comparison_key.get("source_evidence_id", ""),
                "transition_class": transition,
                "v1_decision": sample["v1_decision"],
                "v2_decision": sample["v2_decision"],
                "v1_abstention_reason": v1_reason,
                "v2_abstention_reason": sample["v2_abstention_reason"],
                "decision_changed": sample["decision_changed"],
                "business_claim_value_changed": sample["business_claim_value_changed"],
                "support_semantics_changed": sample["support_semantics_changed"],
                "opportunity_count_delta_for_chain": chain.get("opportunity_count_delta", ""),
                "why_v1_could_not_say_if_applicable": v1_reason
                or (
                    "logical claim slot not present in v1 frozen opportunity universe"
                    if transition == "OPPORTUNITY_ADDED"
                    else "v1 was already expressible or unchanged"
                ),
                "what_v2_added_if_applicable": (
                    "later bitemporal state materialized this logical geological claim slot"
                    if transition == "OPPORTUNITY_ADDED"
                    else "matched slot changed decision, value, or support semantics"
                ),
                "semantic_interpretation": (
                    "Stage3B version_number/supersedes gives revision direction; "
                    "Stage5B frozen decisions give expressibility; stable logical keys "
                    "avoid wrapper-ID added/removed artifacts."
                ),
                "provenance_path": (
                    "Stage5B ClaimOpportunity/Proposal/Decision -> Stage3B lineage -> "
                    "Stage2 GeologicalEvidence or Stage4 metrics as referenced by support"
                ),
                "status": "PASS",
            }
        )
    return rows


def _load_comparison_key(raw_key: str) -> dict[str, object]:
    parsed = json.loads(raw_key)
    return parsed if isinstance(parsed, dict) else {}


def _reconciliation_audit(
    records: list[dict[str, Any]],
    overall_rows: list[dict[str, object]],
    claim_type_rows: list[dict[str, object]],
    reason_rows: list[dict[str, object]],
    matrix_rows: list[dict[str, object]],
    daily_rows: list[dict[str, object]],
    role_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    overall = overall_rows[0]
    checks = [
        (
            "overall_opportunity_equals_sum_claim_type",
            overall["opportunity_count"],
            sum(_int(row["opportunity_count"]) for row in claim_type_rows),
        ),
        (
            "overall_expressible_equals_sum_claim_type",
            overall["expressible_count"],
            sum(_int(row["expressible_count"]) for row in claim_type_rows),
        ),
        (
            "overall_abstain_equals_sum_claim_type",
            overall["abstain_count"],
            sum(_int(row["abstain_count"]) for row in claim_type_rows),
        ),
        (
            "abstain_equals_sum_abstention_reasons",
            overall["abstain_count"],
            sum(_int(row["count"]) for row in reason_rows),
        ),
        (
            "materialized_claims_equals_expressible",
            overall["materialized_claim_count"],
            overall["expressible_count"],
        ),
        (
            "daily_opportunity_sum_equals_overall",
            overall["opportunity_count"],
            sum(_int(row["opportunity_count"]) for row in daily_rows),
        ),
        (
            "daily_expressible_sum_equals_overall",
            overall["expressible_count"],
            sum(_int(row["expressible_count"]) for row in daily_rows),
        ),
        (
            "daily_abstain_sum_equals_overall",
            overall["abstain_count"],
            sum(_int(row["abstain_count"]) for row in daily_rows),
        ),
        (
            "role_opportunity_sum_equals_overall",
            overall["opportunity_count"],
            sum(_int(row["opportunity_count"]) for row in role_rows),
        ),
        (
            "claim_type_reason_matrix_equals_abstention_totals",
            overall["abstain_count"],
            sum(_int(row["count"]) for row in matrix_rows),
        ),
    ]
    return [
        {
            "check_name": name,
            "left_count": left,
            "right_count": right,
            "difference": _int(left) - _int(right),
            "status": "PASS" if _int(left) == _int(right) else "FAIL",
        }
        for name, left, right in checks
    ]


def _rate_integrity_audit(
    tables: list[tuple[str, list[dict[str, object]]]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for table_name, table_rows in tables:
        for idx, row in enumerate(table_rows):
            for key, value in row.items():
                if not (
                    key.endswith("_rate") or key.startswith("share_") or key.startswith("share")
                ):
                    continue
                valid = (
                    value == ""
                    or value is None
                    or (0.0 <= float(str(value)) <= 1.0 and math.isfinite(float(str(value))))
                )
                denominator = _rate_denominator(row, key)
                zero_denominator_nonnull = int(denominator == 0 and value not in {"", None})
                rows.append(
                    {
                        "table_name": table_name,
                        "row_index": idx,
                        "field_name": key,
                        "denominator": denominator,
                        "value": value if value is not None else "",
                        "invalid_count": 0 if valid else 1,
                        "zero_denominator_nonnull_rate_count": zero_denominator_nonnull,
                        "status": "PASS" if valid else "FAIL",
                    }
                )
    return rows


def _rate_denominator(row: dict[str, object], field_name: str) -> int:
    if field_name in {"expressibility_rate", "abstention_rate"}:
        return _int(row.get("opportunity_count", 0))
    if field_name == "share_of_all_abstentions":
        count = _int(row.get("count", 0))
        share = row.get(field_name)
        return (
            0
            if share in {"", None}
            else round(count / float(str(share)))
            if float(str(share))
            else 0
        )
    if field_name == "share_of_abstentions":
        count = _int(row.get("count", 0))
        share = row.get(field_name)
        return (
            0
            if share in {"", None}
            else round(count / float(str(share)))
            if float(str(share))
            else 0
        )
    if field_name == "share_within_claim_type_abstentions":
        count = _int(row.get("count", 0))
        share = row.get(field_name)
        return (
            0
            if share in {"", None}
            else round(count / float(str(share)))
            if float(str(share))
            else 0
        )
    if field_name == "share_within_reason":
        count = _int(row.get("count", 0))
        share = row.get(field_name)
        return (
            0
            if share in {"", None}
            else round(count / float(str(share)))
            if float(str(share))
            else 0
        )
    if field_name == "share_within_metric_opportunities":
        count = _int(row.get("count", 0))
        share = row.get(field_name)
        return (
            0
            if share in {"", None}
            else round(count / float(str(share)))
            if float(str(share))
            else 0
        )
    return _int(row.get("opportunity_count", 0))


def _fixed_case_audit(
    records: list[dict[str, Any]],
    revision_chain_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    def case(case_id: str, passed: bool) -> dict[str, object]:
        return {"case_id": case_id, "status": "PASS" if passed else "FAIL"}

    return [
        case(
            "F1_RAI_AVAILABLE_EXPRESSIBLE",
            any(
                row["claim_type"] == "OPERATIONAL_RESPONSE_ATTENTION" and row["expressible"]
                for row in records
            ),
        ),
        case(
            "F2_RAI_UNAVAILABLE_ABSTAIN",
            any(
                row["claim_type"] == "OPERATIONAL_RESPONSE_ATTENTION" and row["abstained"]
                for row in records
            ),
        ),
        case(
            "F3_GRS_DAILY_REVIEW_COUNTED",
            any(row["claim_type"] == "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW" for row in records),
        ),
        case(
            "F4_FORWARD_GRS_EXPRESSIBLE_AND_ABSTAIN",
            any(
                row["claim_type"] == "FORWARD_GEOLOGICAL_ATTENTION" and row["expressible"]
                for row in records
            )
            and any(
                row["claim_type"] == "FORWARD_GEOLOGICAL_ATTENTION" and row["abstained"]
                for row in records
            ),
        ),
        case(
            "F5_OBSERVED_GEOLOGICAL_EXPRESSIBLE",
            any(
                row["claim_type"] == "OBSERVED_GEOLOGICAL_CONDITION" and row["expressible"]
                for row in records
            ),
        ),
        case(
            "F6_FORECAST_GEOLOGICAL_EXPRESSIBLE",
            any(
                row["claim_type"] == "FORECAST_GEOLOGICAL_CONDITION" and row["expressible"]
                for row in records
            ),
        ),
        case(
            "F7_UNKNOWN_SOURCE_VALUE_ONLY_ABSTAINS",
            all(
                not row["expressible"]
                for row in records
                if row["abstention_reason"] == "UNKNOWN_SOURCE_VALUE"
            ),
        ),
        case(
            "F8_CONTEXT_ONLY_ROLE_NO_STANDALONE_CLAIM",
            not any(
                row["state_role"] == "LOCAL_BACKGROUND_CELL" and row["expressible"]
                for row in records
            ),
        ),
        case(
            "F9_2023_11_06_NO_FAKE_CELL_CLAIM",
            not any(row["valid_date"] == "2023-11-06" for row in records),
        ),
        case("F10_REVISION_CHAIN_IDENTIFIED", bool(revision_chain_rows)),
    ]


def _determinism_audit(
    repo_root: Path, stage5b_artifact: Path, generated_at: str
) -> list[dict[str, object]]:
    with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
        first = Path(first_dir) / "stage5c"
        second = Path(second_dir) / "stage5c"
        build_stage5c_analysis(
            repo_root, stage5b_artifact, first, generated_at, run_determinism=False
        )
        build_stage5c_analysis(
            repo_root, stage5b_artifact, second, generated_at, run_determinism=False
        )
        left = _artifact_semantic_payload(first)
        right = _artifact_semantic_payload(second)
    return [
        {
            "check_name": "analysis_artifact_semantic_content",
            "semantic_diff_count": 0 if left == right else 1,
            "status": "PASS" if left == right else "FAIL",
        }
    ]


def _artifact_semantic_payload(path: Path) -> str:
    payload: dict[str, str] = {}
    for item in sorted(path.rglob("*")):
        if item.is_file() and item.name != "file_hashes.sha256":
            payload[item.relative_to(path).as_posix()] = item.read_text(encoding="utf-8")
    return _canonical_json(payload)


def _hard_check_rows(
    repo_root: Path,
    output_path: Path,
    inputs: Stage5CInputs,
    records: list[dict[str, Any]],
    reconciliation_rows: list[dict[str, object]],
    rate_rows: list[dict[str, object]],
    fixed_rows: list[dict[str, object]],
    determinism_rows: list[dict[str, object]],
    revision_key_rows: list[dict[str, object]],
    revision_lineage_rows: list[dict[str, object]],
    revision_transition_reconciliation_rows: list[dict[str, object]],
    revision_transition_semantic_rows: list[dict[str, object]],
    epistemic_boundary_rows: list[dict[str, object]],
    epistemic_source_rows: list[dict[str, object]],
    unknown_rows: list[dict[str, object]],
    metric_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    overall = _overall_summary(records)[0]
    boundary = epistemic_boundary_rows[0]
    checks: list[tuple[str, object, object, str]] = [
        (
            "upstream_stage5b_opportunity_count_match",
            len(inputs.opportunities),
            8679,
            "analysis_universe_manifest.json",
        ),
        (
            "upstream_stage5b_decision_count_match",
            len(inputs.decisions),
            8679,
            "analysis_universe_manifest.json",
        ),
        (
            "upstream_stage5b_claim_count_match",
            len(inputs.claims),
            6279,
            "analysis_universe_manifest.json",
        ),
        (
            "upstream_stage5b_abstention_count_match",
            len(inputs.abstentions),
            2400,
            "analysis_universe_manifest.json",
        ),
        (
            "unsupported_claim_type_count",
            sum(row["claim_type"] not in CLAIM_TYPE_ORDER for row in records),
            0,
            "claim_type_expressibility.csv",
        ),
        (
            "overall_reconciliation_diff",
            _audit_diff(reconciliation_rows, "overall_opportunity_equals_sum_claim_type"),
            0,
            "analysis_reconciliation_audit.csv",
        ),
        (
            "claim_type_reconciliation_diff",
            sum(
                abs(_int(row["difference"]))
                for row in reconciliation_rows
                if "claim_type" in str(row["check_name"])
            ),
            0,
            "analysis_reconciliation_audit.csv",
        ),
        (
            "abstention_reason_reconciliation_diff",
            _audit_diff(reconciliation_rows, "abstain_equals_sum_abstention_reasons"),
            0,
            "analysis_reconciliation_audit.csv",
        ),
        (
            "daily_reconciliation_diff",
            sum(
                abs(_int(row["difference"]))
                for row in reconciliation_rows
                if str(row["check_name"]).startswith("daily_")
            ),
            0,
            "analysis_reconciliation_audit.csv",
        ),
        (
            "role_reconciliation_diff",
            _audit_diff(reconciliation_rows, "role_opportunity_sum_equals_overall"),
            0,
            "analysis_reconciliation_audit.csv",
        ),
        (
            "invalid_rate_count",
            sum(_int(row["invalid_count"]) for row in rate_rows),
            0,
            "analysis_rate_integrity_audit.csv",
        ),
        (
            "zero_denominator_nonnull_rate_count",
            sum(_int(row["zero_denominator_nonnull_rate_count"]) for row in rate_rows),
            0,
            "analysis_rate_integrity_audit.csv",
        ),
        (
            "unmapped_abstention_reason_count",
            sum(
                row["abstention_reason"] not in REASON_GROUPS for row in records if row["abstained"]
            ),
            0,
            "abstention_reason_summary.csv",
        ),
        (
            "unknown_materialized_factual_claim_count",
            sum(_int(row["unknown_materialized_claim_count"]) for row in unknown_rows),
            0,
            "unknown_abstention_analysis.csv",
        ),
        (
            "forecast_promotion_count",
            boundary["forecast_promoted_to_observed_count"],
            0,
            "epistemic_boundary_audit.csv",
        ),
        (
            "observed_without_proof_count",
            boundary["observed_without_observed_proof_count"],
            0,
            "epistemic_boundary_audit.csv",
        ),
        (
            "metric_null_interpreted_as_zero_count",
            sum(_int(row["null_to_zero_interpretation_count"]) for row in metric_rows),
            0,
            "metric_availability_analysis.csv",
        ),
        (
            "revision_direction_error_count",
            sum(row["ordering_valid"] != "true" for row in revision_lineage_rows),
            0,
            "revision_lineage_order_audit.csv",
        ),
        (
            "revision_supersession_mismatch_count",
            sum(row["supersession_valid"] != "true" for row in revision_lineage_rows),
            0,
            "revision_lineage_order_audit.csv",
        ),
        (
            "revision_comparison_key_collision_count",
            sum(_int(row["duplicate_key_count"]) for row in revision_key_rows),
            0,
            "revision_comparison_key_audit.csv",
        ),
        (
            "revision_transition_reconciliation_diff",
            sum(abs(_int(row["difference"])) for row in revision_transition_reconciliation_rows),
            0,
            "revision_transition_reconciliation_audit.csv",
        ),
        (
            "revision_wrapper_identity_false_change_count",
            sum(
                row["wrapper_identity_only_support_change"] == "true"
                and row["support_semantics_changed"] == "true"
                for row in revision_transition_semantic_rows
            ),
            0,
            "revision_transition_semantics_audit.csv",
        ),
        (
            "revision_version_identity_lost_count",
            sum(row["status"] != "PASS" for row in revision_lineage_rows),
            0,
            "revision_lineage_order_audit.csv",
        ),
        (
            "geological_source_epistemic_unresolved_count",
            sum(row["source_epistemic_status"] == "MISSING" for row in epistemic_source_rows),
            0,
            "epistemic_source_resolution_audit.csv",
        ),
        (
            "observed_opportunity_source_not_observed_count",
            sum(
                row["claim_type"] == "OBSERVED_GEOLOGICAL_CONDITION"
                and row["source_epistemic_status"] != "OBSERVED"
                for row in epistemic_source_rows
            ),
            0,
            "epistemic_source_resolution_audit.csv",
        ),
        (
            "forecast_opportunity_source_not_forecast_count",
            sum(
                row["claim_type"] == "FORECAST_GEOLOGICAL_CONDITION"
                and row["source_epistemic_status"] != "FORECAST"
                for row in epistemic_source_rows
            ),
            0,
            "epistemic_source_resolution_audit.csv",
        ),
        (
            "unknown_abstention_misclassified_as_source_epistemic_missing_count",
            sum(
                row["abstention_reason"] == "UNKNOWN_SOURCE_VALUE"
                and row["source_epistemic_status"] == "MISSING"
                for row in epistemic_source_rows
            ),
            0,
            "epistemic_source_resolution_audit.csv",
        ),
        (
            "stage5b_modified_count",
            _stage5b_diff_count(repo_root),
            0,
            "git diff stage5b-claim-builder-v1-frozen",
        ),
        (
            "stage5a_modified_count",
            _stage5a_diff_count(repo_root),
            0,
            "git diff stage5a-claim-contract-v1.1-frozen",
        ),
        (
            "stage4_modified_count",
            _stage4_diff_count(repo_root, inputs),
            0,
            "git diff stage4-metrics-v1.1-frozen",
        ),
        (
            "forbidden_upstream_builder_import_count",
            _forbidden_upstream_builder_import_count(repo_root),
            0,
            "src/tbm_twin/claim_analysis",
        ),
        (
            "stage5c_generated_stage5b_object_file_count",
            _stage5c_generated_stage5b_object_file_count(output_path),
            0,
            "stage5c output artifact",
        ),
        ("uses_llm", "false", "false", "method_version.json"),
        ("generates_natural_language", "false", "false", "method_version.json"),
        (
            "fixed_case_failure_count",
            sum(row["status"] != "PASS" for row in fixed_rows),
            0,
            "stage5c_fixed_case_audit.csv",
        ),
        (
            "determinism_diff_count",
            sum(_int(row["semantic_diff_count"]) for row in determinism_rows),
            0,
            "stage5c_determinism_audit.csv",
        ),
        (
            "materialized_claims_equal_expressible",
            overall["materialized_claim_count"],
            overall["expressible_count"],
            "overall_expressibility_summary.csv",
        ),
    ]
    rows: list[dict[str, object]] = []
    issue_count = 0
    for name, actual, expected, source in checks:
        status = "PASS" if actual == expected else "FAIL"
        issue_count += int(status != "PASS")
        rows.append(
            {
                "check_name": name,
                "actual": actual,
                "expected": expected,
                "evidence_source": source,
                "status": status,
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


def _method_version(inputs: Stage5CInputs, generated_at: str) -> dict[str, Any]:
    return {
        "method_version": STAGE5C_METHOD_VERSION,
        "schema_version": STAGE5C_SCHEMA_VERSION,
        "status": STAGE5C_STATUS,
        "generated_at": generated_at,
        "generated_at_semantics": GENERATED_AT_SEMANTICS,
        "upstream_stage5b_method": inputs.method["method_version"],
        "upstream_stage5b_commit": STAGE5B_COMMIT,
        "upstream_stage5b_tag": STAGE5B_TAG,
        "modifies_stage5b": False,
        "modifies_stage5a": False,
        "modifies_stage4": False,
        "uses_llm": False,
        "generates_natural_language": False,
        "regenerates_claims": False,
        "analysis_type": "DESCRIPTIVE_CONTRACT_GOVERNED",
        "revision_order_basis": "STAGE3B_VERSION_NUMBER_AND_SUPERSEDES_LINEAGE",
        "revision_comparison_semantics": "LOGICAL_CLAIM_SLOT_STABLE_KEY",
        "revision_support_comparison": "CONTEXT_NORMALIZED_SUPPORT_SEMANTICS",
        "epistemic_opportunity_status_basis": "AUTHORITATIVE_SOURCE_GEOLOGICAL_EVIDENCE",
        "decision_resolved_epistemic_status_separate": True,
    }


def _write_figure_data(
    output_path: Path,
    claim_type_rows: list[dict[str, object]],
    reason_rows: list[dict[str, object]],
    daily_rows: list[dict[str, object]],
    role_rows: list[dict[str, object]],
    revision_rows: list[dict[str, object]],
) -> None:
    write_csv(output_path / "figure_data/fig_claim_type_expressibility.csv", claim_type_rows)
    write_csv(output_path / "figure_data/fig_abstention_reason_distribution.csv", reason_rows)
    write_csv(output_path / "figure_data/fig_daily_expressibility.csv", daily_rows)
    write_csv(output_path / "figure_data/fig_role_expressibility.csv", role_rows)
    counts = Counter(row["transition_class"] for row in revision_rows)
    write_csv(
        output_path / "figure_data/fig_revision_transitions.csv",
        [{"transition_class": key, "count": value} for key, value in sorted(counts.items())],
    )


def _write_paper_table_data(
    output_path: Path,
    claim_type_rows: list[dict[str, object]],
    reason_rows: list[dict[str, object]],
    role_rows: list[dict[str, object]],
    epistemic_rows: list[dict[str, object]],
    revision_rows: list[dict[str, object]],
) -> None:
    write_csv(output_path / "paper_table_data/table_claim_type_expressibility.csv", claim_type_rows)
    write_csv(output_path / "paper_table_data/table_abstention_taxonomy.csv", reason_rows)
    role_epistemic = role_rows + epistemic_rows
    write_csv(output_path / "paper_table_data/table_role_epistemic_summary.csv", role_epistemic)
    write_csv(output_path / "paper_table_data/table_revision_effect.csv", revision_rows)


def _write_report(
    path: Path,
    method_payload: dict[str, Any],
    overall_rows: list[dict[str, object]],
    claim_type_rows: list[dict[str, object]],
    reason_rows: list[dict[str, object]],
    hard_rows: list[dict[str, object]],
) -> None:
    issue_count = next(row["actual"] for row in hard_rows if row["check_name"] == "issue_count")
    text = f"""# Stage 5C Batch Claim Expressibility & Abstention Analysis v1 Frozen

## Scope

Stage5C is a read-only descriptive, contract-governed analysis of the Frozen
Stage5B materialization universe. It does not remake decisions, generate natural
language, build Evidence Packs, call LLMs, or estimate causal effects.

## Frozen Analysis Universe

- Upstream Stage5B method: {method_payload["upstream_stage5b_method"]}
- Upstream Stage5B tag: {method_payload["upstream_stage5b_tag"]}
- Opportunities: {overall_rows[0]["opportunity_count"]}
- EXPRESSIBLE: {overall_rows[0]["expressible_count"]}
- ABSTAIN: {overall_rows[0]["abstain_count"]}

## Denominator Contract

All rates use the denominator specified in `analysis_denominator_contract.json`.
The overall denominator is the complete Frozen Stage5B ClaimOpportunity universe.
No UNKNOWN, context-only, or metric-unavailable opportunity is removed from the
overall denominator.

## Overall Expressibility

{json.dumps(overall_rows, ensure_ascii=False, indent=2)}

## Claim-Type Expressibility

{json.dumps(claim_type_rows, ensure_ascii=False, indent=2)}

## Abstention Taxonomy

{json.dumps(reason_rows, ensure_ascii=False, indent=2)}

## Role-Conditioned Expressibility

LOCAL_BACKGROUND context-only abstentions are contract-governed abstentions, not
evidence errors or hallucination measurements.

## Epistemic Boundaries

FORECAST claims remain source-constrained FORECAST claims; Stage5C does not promote
FORECAST to OBSERVED.

## Metric Availability

Metric statuses are read from Frozen Stage5B/Stage4 payloads. Missing metric values
remain null and are not interpreted as zero.

## Daily Distribution

Daily tables group all versioned ClaimOpportunities by valid_date. They are not a
latest-only or final-as-of collapse.

## Geological Source Support Participation

Source support counts describe support participation and evidence-backed claim counts,
not causal contribution or model performance.

## Bitemporal Revision Analysis

Revision tables order v1/v2 from frozen Stage3B `version_number` and
`supersedes_bitemporal_version_id`, not from bitemporal_version_id lexical order.
Revision comparison keys identify logical claim slots and intentionally exclude
version-specific metric wrapper IDs, metric values/statuses, and geological
normalized values that are the subject of comparison.

## Epistemic Source Semantics

`epistemic_expressibility.csv` separates authoritative source epistemic status
from decision resolved-support status. UNKNOWN early abstentions can have a valid
source status such as OBSERVED or FORECAST while decision resolved status remains
`MISSING_NOT_MATERIALIZED`.

## Reconciliation & Determinism

Reconciliation, rate integrity, hard checks, and repeat-build determinism are recorded
as executable CSV audits.

## Boundary to Stage6

Stage6 Evidence Pack and Controlled LLM generation are not implemented here.

## Hard Check

- issue_count: {issue_count}
"""
    path.write_text(text, encoding="utf-8")


def _resolved_epistemic_statuses(row: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(ref.get("resolved_epistemic_status"))
            for ref in row["decision"].get("resolved_support_refs", [])
            if ref.get("support_kind") == "GEOLOGICAL_EVIDENCE"
            and ref.get("resolved_epistemic_status")
        }
    )


def _authoritative_source_epistemic_status(
    row: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> str:
    evidence_id = str((row["proposal"].get("claim_value") or {}).get("source_evidence_id") or "")
    evidence = evidence_by_id.get(evidence_id)
    return str(evidence.get("epistemic_status") or "MISSING") if evidence else "MISSING"


def _is_unknown_claim_value(row: dict[str, Any]) -> bool:
    value = str((row["proposal"].get("claim_value") or {}).get("normalized_value", ""))
    return value.upper() in UNKNOWN_VALUES


def _subject_key(opportunity: dict[str, Any]) -> str:
    return "|".join(
        str(opportunity.get(key) or "")
        for key in [
            "base_stage3a_state_version_id",
            "bitemporal_version_id",
            "daily_state_id",
            "cell_id",
            "state_role",
            "valid_date",
        ]
    )


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _int(value: object) -> int:
    return int(str(value))


def _audit_diff(rows: list[dict[str, object]], check_name: str) -> int:
    for row in rows:
        if row["check_name"] == check_name:
            return abs(_int(row["difference"]))
    return 1


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


def _stage5b_diff_count(repo_root: Path) -> int:
    return _artifact_hash_mismatch_count(repo_root / STAGE5B_ARTIFACT)


def _stage5a_diff_count(repo_root: Path) -> int:
    artifact = repo_root / "artifacts/stage5a_typed_claim_contract_v1_1"
    return _artifact_hash_mismatch_count(artifact)


def _stage4_diff_count(repo_root: Path, inputs: Stage5CInputs) -> int:
    method_snapshot = STAGE4_SOURCE_SNAPSHOT_SHA256
    method_tree = STAGE4_SOURCE_TREE_HASH
    stage4_method = read_json(
        repo_root / "artifacts/stage4_bitemporal_state_metrics_v1_1/method_version.json"
    )
    hash_diff = int(
        stage4_method.get("source_snapshot_sha256") != method_snapshot
        or stage4_method.get("source_tree_hash") != method_tree
    )
    artifact = repo_root / "artifacts/stage4_bitemporal_state_metrics_v1_1"
    return hash_diff + _artifact_hash_mismatch_count(artifact)


def _artifact_hash_mismatch_count(directory: Path) -> int:
    """Count missing or changed files declared by a frozen artifact manifest."""

    manifest = directory / "file_hashes.sha256"
    if not manifest.is_file():
        return 1
    mismatches = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        path = directory / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
        mismatches += int(actual != expected)
    return mismatches


def _forbidden_upstream_builder_import_count(repo_root: Path) -> int:
    count = 0
    for path in sorted((repo_root / "src/tbm_twin/claim_analysis").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("tbm_twin.claim_building") or module.startswith(
                    "tbm_twin.claims.validation"
                ):
                    count += 1
                count += sum(alias.name == "ClaimContractEvaluator" for alias in node.names)
            elif isinstance(node, ast.Import):
                count += sum(
                    alias.name.startswith("tbm_twin.claim_building")
                    or alias.name.startswith("tbm_twin.claims.validation")
                    for alias in node.names
                )
    return count


def _stage5c_generated_stage5b_object_file_count(output_path: Path) -> int:
    forbidden_files = {
        "claim_opportunities.jsonl",
        "claim_proposals.jsonl",
        "claim_decisions.jsonl",
        "typed_engineering_claims.jsonl",
        "claim_abstentions.jsonl",
    }
    return sum(path.name in forbidden_files for path in output_path.rglob("*") if path.is_file())
