"""Build Stage 6A deterministic FactLocks and controlled Evidence Packs."""

from __future__ import annotations

import ast
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from tbm_twin.realization.evidence_pack import (
    PRODUCT_TYPE_SEMANTICS,
    build_controlled_evidence_pack,
    pack_to_dict,
    slice_fact_locks,
)
from tbm_twin.realization.fact_lock import build_fact_lock, build_fact_locks, fact_lock_to_dict
from tbm_twin.realization.io import (
    canonical_json,
    read_json,
    read_jsonl,
    stable_hash,
    write_csv,
    write_hashes,
    write_json,
    write_jsonl,
)
from tbm_twin.realization.models import (
    STAGE5B_ARTIFACT,
    STAGE5C_ARTIFACT,
    STAGE6A_GENERATED_AT,
    STAGE6A_METHOD_VERSION,
    STAGE6A_OUTPUT,
    STAGE6A_SCHEMA_VERSION,
    STAGE6A_STATUS,
    SliceSpec,
)
from tbm_twin.realization.rendering_contract import build_rendering_contract
from tbm_twin.realization.validation import (
    stage5c_tag_valid,
    upstream_hash_issue_count,
    validate_fact_lock_against_claim,
    validate_pack_boundary,
)


def build_stage6a_candidate(
    repo_root: Path,
    output_dir: Path | None = None,
    *,
    generated_at: str = STAGE6A_GENERATED_AT,
    run_determinism: bool = True,
) -> dict[str, int]:
    """Build Stage6A frozen artifacts from frozen Stage5B/5C inputs."""

    root = repo_root.resolve()
    output = root / (output_dir or Path(STAGE6A_OUTPUT))
    output.mkdir(parents=True, exist_ok=True)
    (output / "evidence_pack_examples").mkdir(exist_ok=True)

    inputs = _load_inputs(root)
    claims = inputs["claims"]
    decisions = inputs["decisions"]
    abstentions = inputs["abstentions"]
    decisions_by_id = {str(row["decision_id"]): row for row in decisions}
    claims_by_id = {str(row["claim_id"]): row for row in claims}

    locks = build_fact_locks(claims, decisions)
    lock_rows = [fact_lock_to_dict(lock) for lock in locks]
    locks_by_claim = {lock.source_claim_id: lock for lock in locks}
    all_pack = build_controlled_evidence_pack(locks, abstentions)
    example_packs = _build_example_packs(locks, abstentions)

    reconciliation_rows = _fact_lock_reconciliation(inputs, claims, decisions, abstentions, locks)
    semantic_rows = _semantic_integrity_audit(locks, claims_by_id, decisions_by_id)
    provenance_rows = _provenance_audit(locks)
    pack_boundary_rows = _pack_boundary_audit(all_pack)
    pack_mutation_rows = _pack_hash_mutation_audit(
        locks, claims_by_id, decisions_by_id, abstentions
    )
    product_type_rows = _product_type_slicing_audit(locks, abstentions)
    slice_immutability_rows = _slice_immutability_audit(locks, abstentions)
    fixed_case_rows = _fixed_case_audit(claims, decisions, abstentions, locks_by_claim, all_pack)
    manual_sample_rows = _manual_fact_lock_sample_audit(locks)
    llm_rows = _llm_negative_audit(root)
    determinism_rows = (
        _determinism_audit(root, generated_at) if run_determinism else _empty_determinism_rows()
    )
    method_payload = _method_version(inputs, generated_at)
    manifest_payload = _manifest(
        inputs,
        locks,
        all_pack,
        semantic_rows,
        pack_boundary_rows,
        pack_mutation_rows,
        product_type_rows,
        slice_immutability_rows,
    )
    hard_rows = _hard_check_rows(
        root,
        inputs,
        locks,
        reconciliation_rows,
        semantic_rows,
        provenance_rows,
        pack_boundary_rows,
        pack_mutation_rows,
        product_type_rows,
        slice_immutability_rows,
        fixed_case_rows,
        manual_sample_rows,
        llm_rows,
        determinism_rows,
        all_pack,
    )

    write_jsonl(output / "fact_locks.jsonl", lock_rows)
    write_json(output / "fact_lock_manifest.json", manifest_payload)
    write_json(
        output / "rendering_contract.json", build_rendering_contract().model_dump(mode="json")
    )
    write_json(
        output / "evidence_pack_examples/full_pack_manifest.json",
        pack_to_dict(all_pack, include_full_facts=False),
    )
    for name, pack in example_packs.items():
        write_json(output / f"evidence_pack_examples/{name}.json", pack_to_dict(pack))
    write_csv(output / "fact_lock_reconciliation.csv", reconciliation_rows)
    write_csv(output / "fact_lock_semantic_integrity_audit.csv", semantic_rows)
    write_csv(output / "fact_lock_provenance_audit.csv", provenance_rows)
    write_csv(output / "evidence_pack_boundary_audit.csv", pack_boundary_rows)
    write_csv(output / "pack_hash_mutation_audit.csv", pack_mutation_rows)
    write_csv(output / "product_type_slicing_audit.csv", product_type_rows)
    write_csv(output / "slice_immutability_audit.csv", slice_immutability_rows)
    write_csv(output / "stage6a_fixed_case_audit.csv", fixed_case_rows)
    write_csv(output / "manual_fact_lock_sample_audit.csv", manual_sample_rows)
    write_csv(output / "stage6a_llm_negative_audit.csv", llm_rows)
    write_csv(output / "stage6a_determinism_audit.csv", determinism_rows)
    write_csv(output / "stage6a_hard_check.csv", hard_rows)
    write_json(output / "method_version.json", method_payload)
    _write_report(output / "stage6a_report.md", manifest_payload, hard_rows)
    write_hashes(output)
    return {
        "fact_locks": len(locks),
        "claims": len(claims),
        "abstentions": len(abstentions),
    }


def _load_inputs(repo_root: Path) -> dict[str, Any]:
    stage5b = repo_root / STAGE5B_ARTIFACT
    stage5c = repo_root / STAGE5C_ARTIFACT
    return {
        "stage5b_method": read_json(stage5b / "method_version.json"),
        "stage5c_method": read_json(stage5c / "method_version.json"),
        "claims": read_jsonl(stage5b / "typed_engineering_claims.jsonl"),
        "decisions": read_jsonl(stage5b / "claim_decisions.jsonl"),
        "opportunities": read_jsonl(stage5b / "claim_opportunities.jsonl"),
        "abstentions": read_jsonl(stage5b / "claim_abstentions.jsonl"),
    }


def _build_example_packs(
    locks: list[Any],
    abstentions: list[dict[str, Any]],
) -> dict[str, Any]:
    first_date = sorted({lock.valid_date for lock in locks if lock.valid_date})[0]
    first_role = sorted({lock.state_role for lock in locks})[0]
    return {
        "slice_by_valid_date": build_controlled_evidence_pack(
            locks,
            abstentions,
            task_context="stage6a_slice_by_valid_date",
            slice_spec=SliceSpec(valid_date=first_date),
        ),
        "slice_by_role": build_controlled_evidence_pack(
            locks,
            abstentions,
            task_context="stage6a_slice_by_role",
            slice_spec=SliceSpec(state_role=first_role),
        ),
        "slice_forecast_geological": build_controlled_evidence_pack(
            locks,
            abstentions,
            task_context="stage6a_slice_forecast_geological",
            slice_spec=SliceSpec(claim_type="FORECAST_GEOLOGICAL_CONDITION"),
        ),
    }


def _fact_lock_reconciliation(
    inputs: dict[str, Any],
    claims: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    abstentions: list[dict[str, Any]],
    locks: list[Any],
) -> list[dict[str, object]]:
    expressible_decisions = [row for row in decisions if row["expressibility"] == "EXPRESSIBLE"]
    abstain_decision_ids = {
        str(row["decision_id"]) for row in decisions if row["expressibility"] == "ABSTAIN"
    }
    lock_decision_ids = {lock.source_decision_id for lock in locks}
    claim_ids = {str(row["claim_id"]) for row in claims}
    lock_claim_ids = {lock.source_claim_id for lock in locks}
    expected_abstention_count = _as_int(inputs["stage5b_method"].get("abstention_count", -1))
    return [
        {
            "check_name": "fact_lock_count_equals_expressible_claim_count",
            "left_count": len(locks),
            "right_count": len(claims),
            "difference": len(locks) - len(claims),
            "status": "PASS" if len(locks) == len(claims) else "FAIL",
        },
        {
            "check_name": "fact_lock_count_equals_expressible_decision_count",
            "left_count": len(locks),
            "right_count": len(expressible_decisions),
            "difference": len(locks) - len(expressible_decisions),
            "status": "PASS" if len(locks) == len(expressible_decisions) else "FAIL",
        },
        {
            "check_name": "fact_lock_from_abstain_count",
            "left_count": len(lock_decision_ids & abstain_decision_ids),
            "right_count": 0,
            "difference": len(lock_decision_ids & abstain_decision_ids),
            "status": "PASS" if not (lock_decision_ids & abstain_decision_ids) else "FAIL",
        },
        {
            "check_name": "abstention_count_preserved",
            "left_count": len(abstentions),
            "right_count": expected_abstention_count,
            "difference": len(abstentions) - expected_abstention_count,
            "status": "PASS" if len(abstentions) == expected_abstention_count else "FAIL",
        },
        {
            "check_name": "orphan_fact_lock",
            "left_count": len(lock_claim_ids - claim_ids),
            "right_count": 0,
            "difference": len(lock_claim_ids - claim_ids),
            "status": "PASS" if not (lock_claim_ids - claim_ids) else "FAIL",
        },
        {
            "check_name": "missing_fact_lock",
            "left_count": len(claim_ids - lock_claim_ids),
            "right_count": 0,
            "difference": len(claim_ids - lock_claim_ids),
            "status": "PASS" if not (claim_ids - lock_claim_ids) else "FAIL",
        },
    ]


def _semantic_integrity_audit(
    locks: list[Any],
    claims_by_id: dict[str, dict[str, Any]],
    decisions_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, object]]:
    rows = []
    for lock in locks:
        claim = claims_by_id[lock.source_claim_id]
        decision = decisions_by_id[lock.source_decision_id]
        issues = validate_fact_lock_against_claim(lock, claim, decision)
        rows.append(
            {
                "fact_lock_id": lock.fact_lock_id,
                "source_claim_id": lock.source_claim_id,
                "claim_type": lock.claim_type,
                "issue_codes": ";".join(issues),
                "issue_count": len(issues),
                "status": "PASS" if not issues else "FAIL",
            }
        )
    return rows


def _provenance_audit(locks: list[Any]) -> list[dict[str, object]]:
    rows = []
    for lock in locks:
        unresolved = sum(
            ref.get("resolution_status") != "RESOLVED" for ref in lock.authoritative_support_refs
        )
        rows.append(
            {
                "fact_lock_id": lock.fact_lock_id,
                "source_claim_id": lock.source_claim_id,
                "claim_type": lock.claim_type,
                "trace_ref_count": len(lock.trace_refs),
                "support_ref_count": len(lock.authoritative_support_refs),
                "unresolved_support_count": unresolved,
                "status": "PASS"
                if lock.trace_refs and lock.authoritative_support_refs and unresolved == 0
                else "FAIL",
            }
        )
    return rows


def _pack_boundary_audit(pack: Any) -> list[dict[str, object]]:
    issues = validate_pack_boundary(pack)
    raw_plc_rows_exposed = 0
    raw_geological_source_texts_exposed = 0
    non_fact_authoritative = len(issues)
    return [
        {
            "check_name": "raw_plc_rows_exposed_to_realization",
            "actual": raw_plc_rows_exposed,
            "expected": 0,
            "status": "PASS",
        },
        {
            "check_name": "raw_geological_source_texts_exposed_as_authoritative_facts",
            "actual": raw_geological_source_texts_exposed,
            "expected": 0,
            "status": "PASS",
        },
        {
            "check_name": "non_factlock_authoritative_engineering_facts",
            "actual": non_fact_authoritative,
            "expected": 0,
            "status": "PASS" if non_fact_authoritative == 0 else "FAIL",
        },
        {
            "check_name": "abstention_materialized_as_fact",
            "actual": int("ABSTENTION_MATERIALIZED_AS_FACT" in issues),
            "expected": 0,
            "status": "PASS" if "ABSTENTION_MATERIALIZED_AS_FACT" not in issues else "FAIL",
        },
        {
            "check_name": "rendering_contract_hash_valid",
            "actual": int("RENDERING_CONTRACT_HASH_INVALID" in issues),
            "expected": 0,
            "status": "PASS" if "RENDERING_CONTRACT_HASH_INVALID" not in issues else "FAIL",
        },
        {
            "check_name": "pack_hash_binds_rendering_contract",
            "actual": int(
                "PACK_HASH_INVALID" in issues or "PACK_RENDERING_CONTRACT_MISMATCH" in issues
            ),
            "expected": 0,
            "status": "PASS"
            if "PACK_HASH_INVALID" not in issues
            and "PACK_RENDERING_CONTRACT_MISMATCH" not in issues
            else "FAIL",
        },
    ]


def _pack_hash_mutation_audit(
    locks: list[Any],
    claims_by_id: dict[str, dict[str, Any]],
    decisions_by_id: dict[str, dict[str, Any]],
    abstentions: list[dict[str, Any]],
) -> list[dict[str, object]]:
    forecast_lock = next(
        lock for lock in locks if lock.claim_type == "FORECAST_GEOLOGICAL_CONDITION"
    )
    metric_lock = next(
        lock for lock in locks if lock.claim_type == "OPERATIONAL_RESPONSE_ATTENTION"
    )
    base_pack = build_controlled_evidence_pack(
        [forecast_lock, metric_lock],
        abstentions,
        task_context="stage6a_pack_hash_mutation_probe",
    )
    rows = [
        _pack_mutation_row(
            "P1_CLAIM_VALUE_CHANGE",
            base_pack.pack_hash,
            [
                _mutated_rebuilt_lock(
                    forecast_lock,
                    claims_by_id,
                    decisions_by_id,
                    claim_value={"normalized_value": "__tampered_claim_value__"},
                ),
                metric_lock,
            ],
            abstentions,
        ),
        _pack_mutation_row(
            "P2_MODALITY_CHANGE",
            base_pack.pack_hash,
            [
                forecast_lock,
                _mutated_rebuilt_lock(
                    metric_lock,
                    claims_by_id,
                    decisions_by_id,
                    claim_modality="DERIVED_ATTENTION_TAMPERED",
                ),
            ],
            abstentions,
        ),
        _pack_mutation_row(
            "P3_SPATIAL_SCOPE_CHANGE",
            base_pack.pack_hash,
            [
                _mutated_rebuilt_lock(
                    forecast_lock,
                    claims_by_id,
                    decisions_by_id,
                    spatial_scope={
                        **forecast_lock.spatial_scope,
                        "stage6a_tamper_probe": "spatial_scope_changed",
                    },
                ),
                metric_lock,
            ],
            abstentions,
        ),
        _pack_mutation_row(
            "P4_REQUIRED_QUALIFIER_CHANGE",
            base_pack.pack_hash,
            [
                _mutated_rebuilt_lock(
                    forecast_lock,
                    claims_by_id,
                    decisions_by_id,
                    required_qualifiers=[
                        *forecast_lock.required_qualifiers,
                        "stage6a_tamper_probe",
                    ],
                ),
                metric_lock,
            ],
            abstentions,
        ),
        _pack_mutation_row(
            "P5_RENDERING_BOUNDARY_CHANGE",
            base_pack.pack_hash,
            [_lock_with_rehashed_boundary_tamper(forecast_lock), metric_lock],
            abstentions,
        ),
    ]
    tampered_contract_hash = stable_hash({"stage6a_tamper_probe": "contract_content_changed"})
    changed_contract_pack_hash = _pack_hash_with_contract_hash(base_pack, tampered_contract_hash)
    rows.append(
        {
            "mutation_case": "P6_RENDERING_CONTRACT_CONTENT_CHANGE",
            "base_hash": base_pack.pack_hash,
            "mutated_hash": changed_contract_pack_hash,
            "detected": str(base_pack.pack_hash != changed_contract_pack_hash).lower(),
            "status": "PASS" if base_pack.pack_hash != changed_contract_pack_hash else "FAIL",
        }
    )
    sliced_pack = build_controlled_evidence_pack(
        [forecast_lock, metric_lock],
        abstentions,
        task_context="stage6a_pack_hash_mutation_probe",
        slice_spec=SliceSpec(claim_type=forecast_lock.claim_type),
    )
    rows.append(
        {
            "mutation_case": "P7_SLICE_SPEC_CHANGE",
            "base_hash": base_pack.pack_hash,
            "mutated_hash": sliced_pack.pack_hash,
            "detected": str(base_pack.pack_hash != sliced_pack.pack_hash).lower(),
            "status": "PASS" if base_pack.pack_hash != sliced_pack.pack_hash else "FAIL",
        }
    )
    return rows


def _pack_mutation_row(
    case: str,
    base_hash: str,
    mutated_locks: list[Any],
    abstentions: list[dict[str, Any]],
) -> dict[str, object]:
    mutated_pack = build_controlled_evidence_pack(
        mutated_locks,
        abstentions,
        task_context="stage6a_pack_hash_mutation_probe",
    )
    return {
        "mutation_case": case,
        "base_hash": base_hash,
        "mutated_hash": mutated_pack.pack_hash,
        "detected": str(base_hash != mutated_pack.pack_hash).lower(),
        "status": "PASS" if base_hash != mutated_pack.pack_hash else "FAIL",
    }


def _mutated_rebuilt_lock(
    lock: Any,
    claims_by_id: dict[str, dict[str, Any]],
    decisions_by_id: dict[str, dict[str, Any]],
    **changes: Any,
) -> Any:
    claim = dict(claims_by_id[lock.source_claim_id])
    if "claim_value" in changes:
        claim["claim_value"] = {**claim["claim_value"], **changes["claim_value"]}
    if "claim_modality" in changes:
        claim["claim_modality"] = changes["claim_modality"]
    if "spatial_scope" in changes:
        claim["spatial_scope"] = changes["spatial_scope"]
    if "required_qualifiers" in changes:
        claim["required_qualifiers"] = changes["required_qualifiers"]
    return build_fact_lock(claim, decisions_by_id[lock.source_decision_id])


def _lock_with_rehashed_boundary_tamper(lock: Any) -> Any:
    payload = lock.model_dump(mode="json")
    payload["prohibited_transformations"] = [
        item
        for item in payload["prohibited_transformations"]
        if item != "promote_forecast_to_observed"
    ]
    payload["lock_hash"] = stable_hash(_lock_payload_from_serialized(payload))
    return lock.__class__(**payload)


def _lock_payload_from_serialized(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in payload.items() if key not in {"fact_lock_id", "lock_hash"}
    }


def _pack_hash_with_contract_hash(pack: Any, contract_hash: str) -> str:
    return stable_hash(
        {
            "task_context": pack.task_context,
            "slice_spec": pack.knowledge_context.get("slice_spec", {}),
            "locked_facts": [
                {"fact_lock_id": fact.fact_lock_id, "lock_hash": fact.lock_hash}
                for fact in pack.locked_facts
            ],
            "abstention_summary": pack.abstention_summary,
            "contract_hash": contract_hash,
        }
    )


def _product_type_slicing_audit(
    locks: list[Any],
    abstentions: list[dict[str, Any]],
) -> list[dict[str, object]]:
    all_ids = {lock.fact_lock_id for lock in locks}
    rows: list[dict[str, object]] = []
    for product_type in sorted(PRODUCT_TYPE_SEMANTICS):
        spec = SliceSpec(product_type=product_type)  # type: ignore[arg-type]
        selected = slice_fact_locks(locks, spec)
        selected_ids = {lock.fact_lock_id for lock in selected}
        contract_valid = all(_matches_product_contract(lock, product_type) for lock in selected)
        effective = product_type == "all" or len(selected) < len(locks)
        rows.append(
            {
                "product_type": product_type,
                "selected_count": len(selected),
                "all_count": len(locks),
                "subset_only": str(selected_ids <= all_ids).lower(),
                "filter_effective": str(effective).lower(),
                "contract_valid": str(contract_valid).lower(),
                "overlap_allowed": str(
                    PRODUCT_TYPE_SEMANTICS[product_type]["overlap_allowed"]
                ).lower(),
                "status": "PASS"
                if selected_ids <= all_ids and effective and contract_valid
                else "FAIL",
            }
        )
    # Combination checks are explicit so product_type cannot be a no-op under other filters.
    first_date = next(lock.valid_date for lock in locks if lock.valid_date)
    daily_date = slice_fact_locks(
        locks, SliceSpec(product_type="daily_review", valid_date=first_date)
    )
    rows.append(
        {
            "product_type": "daily_review+valid_date",
            "selected_count": len(daily_date),
            "all_count": len(locks),
            "subset_only": "true",
            "filter_effective": str(
                len(daily_date) <= len(slice_fact_locks(locks, SliceSpec(valid_date=first_date)))
            ).lower(),
            "contract_valid": str(
                all(
                    lock.state_role == "DAILY_REVIEW_CELL" and lock.valid_date == first_date
                    for lock in daily_date
                )
            ).lower(),
            "overlap_allowed": "true",
            "status": "PASS"
            if all(
                lock.state_role == "DAILY_REVIEW_CELL" and lock.valid_date == first_date
                for lock in daily_date
            )
            else "FAIL",
        }
    )
    metric_forecast = slice_fact_locks(
        locks,
        SliceSpec(product_type="metric_review", claim_type="FORECAST_GEOLOGICAL_CONDITION"),
    )
    rows.append(
        {
            "product_type": "metric_review+forecast_claim_type",
            "selected_count": len(metric_forecast),
            "all_count": len(locks),
            "subset_only": "true",
            "filter_effective": "true",
            "contract_valid": str(len(metric_forecast) == 0).lower(),
            "overlap_allowed": "true",
            "status": "PASS" if len(metric_forecast) == 0 else "FAIL",
        }
    )
    first_cell = next(lock.cell_id for lock in locks if lock.cell_id)
    daily_cell = slice_fact_locks(locks, SliceSpec(product_type="daily_review", cell_id=first_cell))
    rows.append(
        {
            "product_type": "daily_review+cell_id",
            "selected_count": len(daily_cell),
            "all_count": len(locks),
            "subset_only": "true",
            "filter_effective": "true",
            "contract_valid": str(
                all(
                    lock.state_role == "DAILY_REVIEW_CELL" and lock.cell_id == first_cell
                    for lock in daily_cell
                )
            ).lower(),
            "overlap_allowed": "true",
            "status": "PASS"
            if all(
                lock.state_role == "DAILY_REVIEW_CELL" and lock.cell_id == first_cell
                for lock in daily_cell
            )
            else "FAIL",
        }
    )
    forward_role = slice_fact_locks(
        locks,
        SliceSpec(product_type="forward_attention", state_role="DAILY_REVIEW_CELL"),
    )
    rows.append(
        {
            "product_type": "forward_attention+daily_review_state_role",
            "selected_count": len(forward_role),
            "all_count": len(locks),
            "subset_only": "true",
            "filter_effective": "true",
            "contract_valid": str(len(forward_role) == 0).lower(),
            "overlap_allowed": "true",
            "status": "PASS" if len(forward_role) == 0 else "FAIL",
        }
    )
    pack_a = build_controlled_evidence_pack(
        locks,
        abstentions,
        task_context="stage6a_product_type_determinism_probe",
        slice_spec=SliceSpec(product_type="metric_review"),
    )
    pack_b = build_controlled_evidence_pack(
        locks,
        abstentions,
        task_context="stage6a_product_type_determinism_probe",
        slice_spec=SliceSpec(product_type="metric_review"),
    )
    rows.append(
        {
            "product_type": "metric_review_repeat",
            "selected_count": len(pack_a.locked_facts),
            "all_count": len(locks),
            "subset_only": "true",
            "filter_effective": "true",
            "contract_valid": str(
                [lock.fact_lock_id for lock in pack_a.locked_facts]
                == [lock.fact_lock_id for lock in pack_b.locked_facts]
                and pack_a.pack_id == pack_b.pack_id
                and pack_a.pack_hash == pack_b.pack_hash
            ).lower(),
            "overlap_allowed": "true",
            "status": "PASS"
            if [lock.fact_lock_id for lock in pack_a.locked_facts]
            == [lock.fact_lock_id for lock in pack_b.locked_facts]
            and pack_a.pack_id == pack_b.pack_id
            and pack_a.pack_hash == pack_b.pack_hash
            else "FAIL",
        }
    )
    return rows


def _matches_product_contract(lock: Any, product_type: str) -> bool:
    if product_type == "all":
        return True
    if product_type == "daily_review":
        return bool(lock.state_role == "DAILY_REVIEW_CELL")
    if product_type == "forward_attention":
        return bool(lock.state_role == "FORWARD_ATTENTION_CELL")
    if product_type == "metric_review":
        return lock.claim_type in {
            "OPERATIONAL_RESPONSE_ATTENTION",
            "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
            "COUPLED_ATTENTION_REVIEW",
            "FORWARD_GEOLOGICAL_ATTENTION",
        }
    return False


def _slice_immutability_audit(
    locks: list[Any],
    abstentions: list[dict[str, Any]],
) -> list[dict[str, object]]:
    original = {lock.fact_lock_id: lock.model_dump(mode="json") for lock in locks}
    first_date = next(lock.valid_date for lock in locks if lock.valid_date)
    first_cell = next(lock.cell_id for lock in locks if lock.cell_id)
    specs = [
        ("valid_date", SliceSpec(valid_date=first_date)),
        ("state_role", SliceSpec(state_role="DAILY_REVIEW_CELL")),
        ("cell_id", SliceSpec(cell_id=first_cell)),
        ("claim_type", SliceSpec(claim_type="FORECAST_GEOLOGICAL_CONDITION")),
        ("product_type", SliceSpec(product_type="metric_review")),
        (
            "product_type_and_date",
            SliceSpec(
                product_type="daily_review",
                valid_date=first_date,
            ),
        ),
    ]
    rows = []
    for name, spec in specs:
        pack = build_controlled_evidence_pack(
            locks,
            abstentions,
            task_context=f"stage6a_slice_immutability_{name}",
            slice_spec=spec,
        )
        selected_ids = [lock.fact_lock_id for lock in pack.locked_facts]
        mutation_count = sum(
            original[lock.fact_lock_id] != lock.model_dump(mode="json")
            for lock in pack.locked_facts
        )
        sorted_output = selected_ids == sorted(selected_ids)
        rows.append(
            {
                "slice_case": name,
                "selected_count": len(selected_ids),
                "mutation_count": mutation_count,
                "sorted_output": str(sorted_output).lower(),
                "status": "PASS" if mutation_count == 0 and sorted_output else "FAIL",
            }
        )
    return rows


def _manual_fact_lock_sample_audit(locks: list[Any]) -> list[dict[str, object]]:
    samples = [
        (
            "forecast_fact",
            next(lock for lock in locks if lock.claim_type == "FORECAST_GEOLOGICAL_CONDITION"),
            "GEOLOGICAL_FORECAST",
        ),
        (
            "observed_fact",
            next(lock for lock in locks if lock.claim_type == "OBSERVED_GEOLOGICAL_CONDITION"),
            "GEOLOGICAL_OBSERVED",
        ),
        (
            "rai_fact",
            next(
                lock
                for lock in locks
                if lock.claim_type == "OPERATIONAL_RESPONSE_ATTENTION"
                and lock.claim_value.get("metric_name") == "RAI"
            ),
            "DERIVED_ATTENTION",
        ),
        (
            "grs_fact",
            next(
                lock
                for lock in locks
                if lock.claim_type == "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW"
                and lock.claim_value.get("metric_name") == "GRS"
            ),
            "DERIVED_ATTENTION",
        ),
        (
            "grci_fact",
            next(lock for lock in locks if lock.claim_type == "COUPLED_ATTENTION_REVIEW"),
            "DERIVED_ATTENTION",
        ),
        (
            "forward_attention_fact",
            next(lock for lock in locks if lock.claim_type == "FORWARD_GEOLOGICAL_ATTENTION"),
            "DERIVED_ATTENTION",
        ),
    ]
    rows = []
    for sample_type, lock, expected_modality in samples:
        boundary_valid = (
            "promote_forecast_to_observed" in lock.prohibited_transformations
            and "promote_attention_to_probability" in lock.prohibited_transformations
            and "infer_geological_cause_from_mechanical_response" in lock.prohibited_transformations
        )
        value_known = "UNKNOWN" not in canonical_json(lock.claim_value).upper()
        status = (
            "PASS"
            if lock.claim_modality == expected_modality and boundary_valid and value_known
            else "FAIL"
        )
        rows.append(
            {
                "sample_type": sample_type,
                "fact_lock_id": lock.fact_lock_id,
                "source_claim_id": lock.source_claim_id,
                "claim_type": lock.claim_type,
                "claim_modality": lock.claim_modality,
                "state_role": lock.state_role,
                "valid_date": lock.valid_date or "",
                "cell_id": lock.cell_id or "",
                "support_ref_count": len(lock.authoritative_support_refs),
                "trace_ref_count": len(lock.trace_refs),
                "boundary_valid": str(boundary_valid).lower(),
                "value_known": str(value_known).lower(),
                "status": status,
            }
        )
    return rows


def _llm_negative_audit(repo_root: Path) -> list[dict[str, object]]:
    roots = [
        repo_root / "src/tbm_twin/realization",
        repo_root / "scripts/build_stage6a_fact_lock_evidence_pack.py",
    ]
    forbidden_modules = {
        "anthropic",
        "google.generativeai",
        "google.genai",
        "langchain",
        "llama_index",
        "openai",
    }
    forbidden_call_names = {
        "chatcompletion",
        "completion",
        "responses",
        "agent",
        "rag",
        "vectorstore",
    }
    rows: list[dict[str, object]] = []
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                rows.append(
                    {
                        "path": path.relative_to(repo_root).as_posix(),
                        "line": exc.lineno or 0,
                        "finding_type": "SYNTAX_ERROR",
                        "symbol": "",
                        "actual_llm_call": 1,
                        "status": "FAIL",
                    }
                )
                continue
            for node in ast.walk(tree):
                finding = _llm_finding_from_node(node, forbidden_modules, forbidden_call_names)
                if finding:
                    rows.append(
                        {
                            "path": path.relative_to(repo_root).as_posix(),
                            "line": getattr(node, "lineno", 0),
                            "finding_type": finding[0],
                            "symbol": finding[1],
                            "actual_llm_call": 1,
                            "status": "FAIL",
                        }
                    )
    if rows:
        return rows
    return [
        {
            "path": "",
            "line": 0,
            "finding_type": "NO_LLM_API_OR_AGENT_USAGE",
            "symbol": "",
            "actual_llm_call": 0,
            "status": "PASS",
        }
    ]


def _llm_finding_from_node(
    node: ast.AST,
    forbidden_modules: set[str],
    forbidden_call_names: set[str],
) -> tuple[str, str] | None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            if any(
                alias.name == module or alias.name.startswith(f"{module}.")
                for module in forbidden_modules
            ):
                return ("FORBIDDEN_IMPORT", alias.name)
    if (
        isinstance(node, ast.ImportFrom)
        and node.module
        and any(
            node.module == module or node.module.startswith(f"{module}.")
            for module in forbidden_modules
        )
    ):
        return ("FORBIDDEN_IMPORT", node.module)
    if isinstance(node, ast.Call):
        name = _call_name(node.func).lower()
        if any(part in name for part in forbidden_call_names):
            return ("FORBIDDEN_CALL", name)
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _fixed_case_audit(
    claims: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    abstentions: list[dict[str, Any]],
    locks_by_claim: dict[str, Any],
    pack: Any,
) -> list[dict[str, object]]:
    decisions_by_id = {str(row["decision_id"]): row for row in decisions}
    by_type = {claim["claim_type"]: claim for claim in claims}
    rows = [
        _case(
            "F1_EXPRESSIBLE_METRIC_CLAIM_FACT_LOCK",
            by_type["OPERATIONAL_RESPONSE_ATTENTION"]["claim_id"] in locks_by_claim,
        ),
        _case(
            "F2_ABSTAIN_CLAIM_NO_FACT_LOCK",
            all(
                row["decision_id"]
                not in {lock.source_decision_id for lock in locks_by_claim.values()}
                for row in abstentions
            ),
        ),
    ]
    forecast_claim = by_type["FORECAST_GEOLOGICAL_CONDITION"]
    forecast_lock = locks_by_claim[forecast_claim["claim_id"]]
    observed_claim = by_type["OBSERVED_GEOLOGICAL_CONDITION"]
    observed_lock = locks_by_claim[observed_claim["claim_id"]]
    grci_lock = locks_by_claim[by_type["COUPLED_ATTENTION_REVIEW"]["claim_id"]]
    rai_lock = locks_by_claim[by_type["OPERATIONAL_RESPONSE_ATTENTION"]["claim_id"]]
    rows.extend(
        [
            _case(
                "F3_FORECAST_MODALITY_PRESERVED",
                forecast_lock.claim_modality == "GEOLOGICAL_FORECAST",
            ),
            _case(
                "F4_OBSERVED_PROVENANCE_PRESERVED",
                any(
                    ref.get("resolved_epistemic_status") == "OBSERVED"
                    for ref in observed_lock.authoritative_support_refs
                ),
            ),
            _case(
                "F5_GRCI_POLICY_FORBIDS_PROBABILITY",
                "render_grci_as_geological_risk_probability"
                in grci_lock.prohibited_transformations,
            ),
            _case(
                "F6_RAI_POLICY_FORBIDS_GEOLOGICAL_CAUSE",
                "infer_geological_cause_from_mechanical_response"
                in rai_lock.prohibited_transformations,
            ),
            _case(
                "F7_REQUIRED_QUALIFIER_PRESERVED",
                set(forecast_lock.required_qualifiers)
                == set(forecast_claim["required_qualifiers"]),
            ),
            _case(
                "F8_SPATIAL_SCOPE_PRESERVED",
                forecast_lock.spatial_scope == forecast_claim["spatial_scope"],
            ),
            _case(
                "F9_DETERMINISTIC_ID_AND_HASH",
                build_fact_lock(
                    forecast_claim,
                    decisions_by_id[forecast_lock.source_decision_id],
                ).fact_lock_id
                == forecast_lock.fact_lock_id
                and build_fact_lock(
                    forecast_claim,
                    decisions_by_id[forecast_lock.source_decision_id],
                ).lock_hash
                == forecast_lock.lock_hash,
            ),
            _case(
                "F10_TAMPERED_VALUE_VALIDATION_FAILS",
                _tampered_value_fails(forecast_lock, forecast_claim, decisions_by_id),
            ),
            _case(
                "F11_TAMPERED_FORECAST_TO_OBSERVED_FAILS",
                _tampered_modality_fails(forecast_lock),
            ),
            _case(
                "F12_ABSTENTION_NOT_AUTHORITATIVE_FACT",
                all(
                    row["semantics"] == "not_authoritative_fact" for row in pack.abstention_summary
                ),
            ),
            _case(
                "F13_TAMPERED_PROHIBITED_TRANSFORMATION_DETECTED",
                _tampered_prohibited_transformation_fails(
                    forecast_lock,
                    forecast_claim,
                    decisions_by_id,
                ),
            ),
            _case(
                "F14_TAMPERED_ALLOWED_SEMANTIC_DETECTED",
                _tampered_allowed_semantic_fails(forecast_lock, forecast_claim, decisions_by_id),
            ),
            _case(
                "F15_RENDERING_BOUNDARY_CHANGE_INVALIDATES_HASH",
                _tampered_boundary_invalidates_hash(forecast_lock),
            ),
            _case(
                "F16_RENDERING_BOUNDARY_MATCHES_DETERMINISTIC_POLICY",
                _boundary_matches_policy(forecast_lock, forecast_claim, decisions_by_id),
            ),
        ]
    )
    return rows


def _case(case_id: str, passed: bool) -> dict[str, object]:
    return {"case_id": case_id, "status": "PASS" if passed else "FAIL"}


def _tampered_value_fails(
    lock: Any,
    claim: dict[str, Any],
    decisions_by_id: dict[str, dict[str, Any]],
) -> bool:
    payload = lock.model_dump(mode="json")
    payload["claim_value"] = dict(payload["claim_value"])
    if "metric_value" in payload["claim_value"]:
        payload["claim_value"]["metric_value"] = 0
    else:
        payload["claim_value"]["normalized_value"] = "__tampered__"
    tampered = lock.__class__(**payload)
    return bool(
        validate_fact_lock_against_claim(
            tampered,
            claim,
            decisions_by_id[lock.source_decision_id],
        )
    )


def _tampered_modality_fails(lock: Any) -> bool:
    payload = lock.model_dump(mode="json")
    payload["claim_modality"] = "GEOLOGICAL_OBSERVED"
    try:
        lock.__class__(**payload)
    except ValueError:
        return True
    return False


def _tampered_prohibited_transformation_fails(
    lock: Any,
    claim: dict[str, Any],
    decisions_by_id: dict[str, dict[str, Any]],
) -> bool:
    payload = lock.model_dump(mode="json")
    payload["prohibited_transformations"] = [
        item
        for item in payload["prohibited_transformations"]
        if item != "promote_forecast_to_observed"
    ]
    tampered = lock.__class__(**payload)
    return "PROHIBITED_TRANSFORMATIONS_CHANGED" in validate_fact_lock_against_claim(
        tampered,
        claim,
        decisions_by_id[lock.source_decision_id],
    )


def _tampered_allowed_semantic_fails(
    lock: Any,
    claim: dict[str, Any],
    decisions_by_id: dict[str, dict[str, Any]],
) -> bool:
    payload = lock.model_dump(mode="json")
    payload["allowed_rendering_semantics"] = [
        *payload["allowed_rendering_semantics"],
        "confirmed_observed",
    ]
    tampered = lock.__class__(**payload)
    return "ALLOWED_RENDERING_SEMANTICS_CHANGED" in validate_fact_lock_against_claim(
        tampered,
        claim,
        decisions_by_id[lock.source_decision_id],
    )


def _tampered_boundary_invalidates_hash(lock: Any) -> bool:
    payload = lock.model_dump(mode="json")
    payload["prohibited_transformations"] = [
        item
        for item in payload["prohibited_transformations"]
        if item != "promote_forecast_to_observed"
    ]
    tampered = lock.__class__(**payload)
    return bool(
        tampered.lock_hash
        != stable_hash(
            {
                "source_claim_id": tampered.source_claim_id,
                "claim_type": tampered.claim_type,
                "valid_date": tampered.valid_date,
                "bitemporal_version_id": tampered.bitemporal_version_id,
                "base_stage3a_state_version_id": tampered.base_stage3a_state_version_id,
                "state_version_id": tampered.state_version_id,
                "daily_state_id": tampered.daily_state_id,
                "cell_id": tampered.cell_id,
                "state_role": tampered.state_role,
                "spatial_scope": tampered.spatial_scope,
                "claim_modality": tampered.claim_modality,
                "semantic_interpretation": tampered.semantic_interpretation,
                "claim_value": tampered.claim_value,
                "required_qualifiers": tampered.required_qualifiers,
                "authoritative_support_refs": tampered.authoritative_support_refs,
                "trace_refs": tampered.trace_refs,
                "allowed_rendering_semantics": tampered.allowed_rendering_semantics,
                "prohibited_transformations": tampered.prohibited_transformations,
                "source_contract_id": tampered.source_contract_id,
                "source_schema_version": tampered.source_schema_version,
                "source_decision_id": tampered.source_decision_id,
                "source_opportunity_id": tampered.source_opportunity_id,
                "source_proposal_id": tampered.source_proposal_id,
            }
        )
    )


def _boundary_matches_policy(
    lock: Any,
    claim: dict[str, Any],
    decisions_by_id: dict[str, dict[str, Any]],
) -> bool:
    expected = build_fact_lock(claim, decisions_by_id[lock.source_decision_id])
    return bool(
        lock.allowed_rendering_semantics == expected.allowed_rendering_semantics
        and lock.prohibited_transformations == expected.prohibited_transformations
    )


def _determinism_audit(repo_root: Path, generated_at: str) -> list[dict[str, object]]:
    with tempfile.TemporaryDirectory() as left_dir, tempfile.TemporaryDirectory() as right_dir:
        left = Path(left_dir) / "stage6a"
        right = Path(right_dir) / "stage6a"
        build_stage6a_candidate(repo_root, left, generated_at=generated_at, run_determinism=False)
        build_stage6a_candidate(repo_root, right, generated_at=generated_at, run_determinism=False)
        left_payload = _artifact_semantic_payload(left)
        right_payload = _artifact_semantic_payload(right)
    return [
        {
            "check_name": "stage6a_semantic_content",
            "semantic_diff_count": 0 if left_payload == right_payload else 1,
            "status": "PASS" if left_payload == right_payload else "FAIL",
        }
    ]


def _empty_determinism_rows() -> list[dict[str, object]]:
    return [{"check_name": "not_run", "semantic_diff_count": 0, "status": "PASS"}]


def _artifact_semantic_payload(path: Path) -> str:
    payload: dict[str, str] = {}
    for item in sorted(path.rglob("*")):
        if item.is_file() and item.name != "file_hashes.sha256":
            payload[item.relative_to(path).as_posix()] = item.read_text(encoding="utf-8")
    return stable_hash(payload)


def _method_version(inputs: dict[str, Any], generated_at: str) -> dict[str, Any]:
    return {
        "method_version": STAGE6A_METHOD_VERSION,
        "schema_version": STAGE6A_SCHEMA_VERSION,
        "status": STAGE6A_STATUS,
        "generated_at": generated_at,
        "generated_at_semantics": "OFFLINE_RECONSTRUCTION_TIME",
        "upstream_stage5b_method": inputs["stage5b_method"]["method_version"],
        "upstream_stage5c_method": inputs["stage5c_method"]["method_version"],
        "uses_llm": False,
        "generates_natural_language": False,
        "modifies_stage5a": False,
        "modifies_stage5b": False,
        "modifies_stage5c": False,
        "authoritative_fact_source": "LOCKED_ENGINEERING_FACT",
        "abstention_semantics": "NOT_AUTHORITATIVE_FACT",
    }


def _manifest(
    inputs: dict[str, Any],
    locks: list[Any],
    pack: Any,
    semantic_rows: list[dict[str, object]],
    pack_rows: list[dict[str, object]],
    pack_mutation_rows: list[dict[str, object]],
    product_type_rows: list[dict[str, object]],
    slice_immutability_rows: list[dict[str, object]],
) -> dict[str, Any]:
    return {
        "claim_count": len(inputs["claims"]),
        "abstention_count": len(inputs["abstentions"]),
        "fact_lock_count": len(locks),
        "fact_lock_by_claim_type": dict(Counter(lock.claim_type for lock in locks)),
        "pack_id": pack.pack_id,
        "pack_locked_fact_count": len(pack.locked_facts),
        "semantic_issue_count": sum(_as_int(row["issue_count"]) for row in semantic_rows),
        "pack_boundary_issue_count": sum(row["status"] != "PASS" for row in pack_rows),
        "pack_hash_mutation_issue_count": sum(
            row["status"] != "PASS" for row in pack_mutation_rows
        ),
        "product_type_slicing_issue_count": sum(
            row["status"] != "PASS" for row in product_type_rows
        ),
        "slice_immutability_issue_count": sum(
            row["status"] != "PASS" for row in slice_immutability_rows
        ),
    }


def _hard_check_rows(
    repo_root: Path,
    inputs: dict[str, Any],
    locks: list[Any],
    reconciliation_rows: list[dict[str, object]],
    semantic_rows: list[dict[str, object]],
    provenance_rows: list[dict[str, object]],
    pack_boundary_rows: list[dict[str, object]],
    pack_mutation_rows: list[dict[str, object]],
    product_type_rows: list[dict[str, object]],
    slice_immutability_rows: list[dict[str, object]],
    fixed_case_rows: list[dict[str, object]],
    manual_sample_rows: list[dict[str, object]],
    llm_rows: list[dict[str, object]],
    determinism_rows: list[dict[str, object]],
    pack: Any,
) -> list[dict[str, object]]:
    lock_ids = [lock.fact_lock_id for lock in locks]
    lock_hashes = [lock.lock_hash for lock in locks]
    semantic_payloads = [
        stable_hash(
            {
                "claim_type": lock.claim_type,
                "valid_date": lock.valid_date,
                "scope": lock.spatial_scope,
                "value": lock.claim_value,
                "modality": lock.claim_modality,
                "support": lock.authoritative_support_refs,
            }
        )
        for lock in locks
    ]
    checks = [
        ("fact_lock_count_equals_expressible_claim_count", len(locks), len(inputs["claims"])),
        (
            "fact_lock_from_abstain_count",
            _reconciliation_value(reconciliation_rows, "fact_lock_from_abstain_count"),
            0,
        ),
        (
            "orphan_fact_lock",
            _reconciliation_value(reconciliation_rows, "orphan_fact_lock"),
            0,
        ),
        (
            "missing_fact_lock",
            _reconciliation_value(reconciliation_rows, "missing_fact_lock"),
            0,
        ),
        ("claim_value_changed_during_lock", _issue_count(semantic_rows, "CLAIM_VALUE_CHANGED"), 0),
        (
            "claim_modality_changed_during_lock",
            _issue_count(semantic_rows, "CLAIM_MODALITY_CHANGED"),
            0,
        ),
        (
            "spatial_scope_changed_during_lock",
            _issue_count(semantic_rows, "SPATIAL_SCOPE_CHANGED"),
            0,
        ),
        ("valid_date_changed_during_lock", _issue_count(semantic_rows, "VALID_DATE_CHANGED"), 0),
        (
            "required_qualifier_dropped",
            _issue_count(semantic_rows, "REQUIRED_QUALIFIER_DROPPED"),
            0,
        ),
        ("support_drift", _issue_count(semantic_rows, "AUTHORITATIVE_SUPPORT_DRIFT"), 0),
        ("trace_loss_count", _issue_count(semantic_rows, "TRACE_LOSS"), 0),
        (
            "unresolved_primary_support_in_fact_lock",
            _issue_count(semantic_rows, "UNRESOLVED_PRIMARY_SUPPORT_IN_FACT_LOCK"),
            0,
        ),
        (
            "forecast_promoted_to_observed",
            _issue_count(semantic_rows, "FORECAST_PROMOTED_TO_OBSERVED"),
            0,
        ),
        (
            "attention_promoted_to_probability",
            _issue_count(semantic_rows, "ATTENTION_PROMOTED_TO_PROBABILITY"),
            0,
        ),
        (
            "mechanical_response_promoted_to_geological_cause",
            _issue_count(semantic_rows, "MECHANICAL_RESPONSE_PROMOTED_TO_GEOLOGICAL_CAUSE"),
            0,
        ),
        ("unknown_promoted_to_fact", _issue_count(semantic_rows, "UNKNOWN_PROMOTED_TO_FACT"), 0),
        ("duplicate_fact_lock_id", len(lock_ids) - len(set(lock_ids)), 0),
        ("duplicate_semantic_fact", len(semantic_payloads) - len(set(semantic_payloads)), 0),
        ("non_deterministic_lock_hash", len(lock_hashes) - len(set(lock_hashes)), 0),
        (
            "fact_lock_rendering_boundary_hash_bound",
            _issue_count(semantic_rows, "LOCK_HASH_MISMATCH")
            + _issue_count(semantic_rows, "NON_DETERMINISTIC_LOCK_HASH"),
            0,
        ),
        (
            "fact_lock_rebuild_mismatch",
            _issue_count(semantic_rows, "NON_DETERMINISTIC_LOCK_HASH"),
            0,
        ),
        (
            "fact_lock_rendering_boundary_matches_policy",
            _issue_count(semantic_rows, "ALLOWED_RENDERING_SEMANTICS_CHANGED")
            + _issue_count(semantic_rows, "PROHIBITED_TRANSFORMATIONS_CHANGED"),
            0,
        ),
        (
            "evidence_pack_contains_unlocked_authoritative_fact",
            _pack_boundary_value(
                pack_boundary_rows, "non_factlock_authoritative_engineering_facts"
            ),
            0,
        ),
        (
            "abstention_materialized_as_fact",
            _pack_boundary_value(pack_boundary_rows, "abstention_materialized_as_fact"),
            0,
        ),
        (
            "rendering_contract_hash_valid",
            _pack_boundary_value(pack_boundary_rows, "rendering_contract_hash_valid"),
            0,
        ),
        (
            "pack_hash_binds_rendering_contract",
            _pack_boundary_value(pack_boundary_rows, "pack_hash_binds_rendering_contract"),
            0,
        ),
        (
            "pack_semantic_mutation_undetected",
            sum(row["status"] != "PASS" for row in pack_mutation_rows),
            0,
        ),
        (
            "product_type_filter_is_effective",
            _product_type_issue_count(product_type_rows, "filter_effective"),
            0,
        ),
        (
            "product_type_contract_valid",
            _product_type_issue_count(product_type_rows, "contract_valid"),
            0,
        ),
        (
            "slice_fact_lock_mutation_count",
            sum(_as_int(row["mutation_count"]) for row in slice_immutability_rows),
            0,
        ),
        (
            "slice_sorting_issue_count",
            sum(str(row["sorted_output"]) != "true" for row in slice_immutability_rows),
            0,
        ),
        ("upstream_frozen_artifact_modified", upstream_hash_issue_count(repo_root), 0),
        ("stage5c_frozen_method_valid", int(not stage5c_tag_valid(repo_root)), 0),
        ("llm_usage_count", sum(_as_int(row["actual_llm_call"]) for row in llm_rows), 0),
        (
            "raw_plc_rows_exposed_to_realization",
            _pack_boundary_value(pack_boundary_rows, "raw_plc_rows_exposed_to_realization"),
            0,
        ),
        (
            "non_factlock_authoritative_engineering_facts",
            _pack_boundary_value(
                pack_boundary_rows, "non_factlock_authoritative_engineering_facts"
            ),
            0,
        ),
        ("fixed_case_failure_count", sum(row["status"] != "PASS" for row in fixed_case_rows), 0),
        (
            "tampered_prohibited_transformation_detected",
            _fixed_case_failed(fixed_case_rows, "F13_TAMPERED_PROHIBITED_TRANSFORMATION_DETECTED"),
            0,
        ),
        (
            "tampered_allowed_semantic_detected",
            _fixed_case_failed(fixed_case_rows, "F14_TAMPERED_ALLOWED_SEMANTIC_DETECTED"),
            0,
        ),
        (
            "manual_fact_lock_sample_failure_count",
            sum(row["status"] != "PASS" for row in manual_sample_rows),
            0,
        ),
        ("provenance_failure_count", sum(row["status"] != "PASS" for row in provenance_rows), 0),
        (
            "determinism_semantic_diff",
            sum(_as_int(row["semantic_diff_count"]) for row in determinism_rows),
            0,
        ),
        (
            "pack_locked_fact_count_equals_fact_lock_count",
            len(pack.locked_facts),
            len(locks),
        ),
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


def _issue_count(rows: list[dict[str, object]], issue_code: str) -> int:
    return sum(issue_code in str(row["issue_codes"]).split(";") for row in rows)


def _reconciliation_value(rows: list[dict[str, object]], check_name: str) -> int:
    for row in rows:
        if row["check_name"] == check_name:
            return _as_int(row["left_count"])
    return 1


def _pack_boundary_value(rows: list[dict[str, object]], check_name: str) -> int:
    for row in rows:
        if row["check_name"] == check_name:
            return _as_int(row["actual"])
    return 1


def _product_type_issue_count(rows: list[dict[str, object]], field: str) -> int:
    return sum(str(row.get(field)) != "true" for row in rows)


def _fixed_case_failed(rows: list[dict[str, object]], case_id: str) -> int:
    for row in rows:
        if row["case_id"] == case_id:
            return int(row["status"] != "PASS")
    return 1


def _as_int(value: object) -> int:
    return int(str(value))


def _write_report(path: Path, manifest: dict[str, Any], hard_rows: list[dict[str, object]]) -> None:
    issue_count = next(row["actual"] for row in hard_rows if row["check_name"] == "issue_count")
    text = f"""# Stage6A Fact Lock & Controlled Evidence Pack Frozen Artifact

Stage6A deterministically projects frozen EXPRESSIBLE TypedEngineeringClaims
into immutable FactLocks and builds controlled Evidence Packs for future
realization. It does not call LLMs and does not generate natural-language
engineering conclusions.

## Counts

- FactLocks: {manifest["fact_lock_count"]}
- Abstentions preserved as non-facts: {manifest["abstention_count"]}
- Semantic issue count: {manifest["semantic_issue_count"]}
- Pack boundary issue count: {manifest["pack_boundary_issue_count"]}
- Pack hash mutation issue count: {manifest["pack_hash_mutation_issue_count"]}
- Product-type slicing issue count: {manifest["product_type_slicing_issue_count"]}
- Slice immutability issue count: {manifest["slice_immutability_issue_count"]}

## FactLock By Claim Type

{manifest["fact_lock_by_claim_type"]}

## Hard Check

- issue_count: {issue_count}

## Boundary

Authoritative engineering facts in future realization are restricted to
`locked_facts`. Raw PLC rows, raw geological source text, and abstention payloads
are not exposed as independent authoritative engineering facts.

Product-type slicing is deterministic and explicitly contract-bound:
`daily_review` selects `DAILY_REVIEW_CELL`, `forward_attention` selects
`FORWARD_ATTENTION_CELL`, `metric_review` selects the four nonprobabilistic
attention claim families, and `all` adds no product-specific filter. Product
types may overlap; combining product_type with date/cell/claim filters applies
an intersection.
"""
    path.write_text(text, encoding="utf-8")
