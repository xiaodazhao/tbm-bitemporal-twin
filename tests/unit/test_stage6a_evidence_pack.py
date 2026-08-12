"""Stage6A controlled Evidence Pack tests."""

from __future__ import annotations

from tbm_twin.realization.evidence_pack import build_controlled_evidence_pack, slice_fact_locks
from tbm_twin.realization.models import LockedEngineeringFact, SliceSpec
from tests.unit.stage6a_helpers import read_csv, read_json, read_jsonl, stage6a_artifact


def test_stage6a_pack_contains_only_factlock_authoritative_facts(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    boundary = read_csv(artifact / "evidence_pack_boundary_audit.csv")

    assert _row(boundary, "raw_plc_rows_exposed_to_realization")["actual"] == "0"
    assert _row(boundary, "non_factlock_authoritative_engineering_facts")["actual"] == "0"
    assert _row(boundary, "abstention_materialized_as_fact")["actual"] == "0"


def test_stage6a_pack_abstention_summary_is_not_fact(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    pack = read_json(artifact / "evidence_pack_examples/full_pack_manifest.json")

    assert pack["locked_facts"]
    assert all(row["semantics"] == "not_authoritative_fact" for row in pack["abstention_summary"])


def test_stage6a_slicing_does_not_modify_facts(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    locks = [LockedEngineeringFact(**row) for row in read_jsonl(artifact / "fact_locks.jsonl")]
    target_date = next(lock.valid_date for lock in locks if lock.valid_date)
    sliced = slice_fact_locks(locks, SliceSpec(valid_date=target_date))

    assert sliced
    assert all(lock.valid_date == target_date for lock in sliced)
    original_by_id = {lock.fact_lock_id: lock.model_dump(mode="json") for lock in locks}
    assert all(original_by_id[lock.fact_lock_id] == lock.model_dump(mode="json") for lock in sliced)


def test_stage6a_product_type_all_does_not_change_set(tmp_path_factory) -> None:
    locks = _locks(stage6a_artifact(tmp_path_factory))

    assert [
        lock.fact_lock_id for lock in slice_fact_locks(locks, SliceSpec(product_type="all"))
    ] == [lock.fact_lock_id for lock in sorted(locks, key=lambda item: item.fact_lock_id)]


def test_stage6a_product_type_contracts(tmp_path_factory) -> None:
    locks = _locks(stage6a_artifact(tmp_path_factory))

    daily = slice_fact_locks(locks, SliceSpec(product_type="daily_review"))
    forward = slice_fact_locks(locks, SliceSpec(product_type="forward_attention"))
    metric = slice_fact_locks(locks, SliceSpec(product_type="metric_review"))

    assert daily and all(lock.state_role == "DAILY_REVIEW_CELL" for lock in daily)
    assert forward and all(lock.state_role == "FORWARD_ATTENTION_CELL" for lock in forward)
    assert metric and all(
        lock.claim_type
        in {
            "OPERATIONAL_RESPONSE_ATTENTION",
            "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
            "COUPLED_ATTENTION_REVIEW",
            "FORWARD_GEOLOGICAL_ATTENTION",
        }
        for lock in metric
    )


def test_stage6a_product_type_combines_with_date_and_claim_type(tmp_path_factory) -> None:
    locks = _locks(stage6a_artifact(tmp_path_factory))
    target_date = next(lock.valid_date for lock in locks if lock.valid_date)

    daily_date = slice_fact_locks(
        locks, SliceSpec(product_type="daily_review", valid_date=target_date)
    )
    metric_forecast = slice_fact_locks(
        locks,
        SliceSpec(product_type="metric_review", claim_type="FORECAST_GEOLOGICAL_CONDITION"),
    )

    assert daily_date
    assert all(
        lock.state_role == "DAILY_REVIEW_CELL" and lock.valid_date == target_date
        for lock in daily_date
    )
    assert metric_forecast == []


def test_stage6a_product_type_combines_with_cell_and_state_role(tmp_path_factory) -> None:
    locks = _locks(stage6a_artifact(tmp_path_factory))
    target_cell = next(lock.cell_id for lock in locks if lock.cell_id)

    daily_cell = slice_fact_locks(
        locks, SliceSpec(product_type="daily_review", cell_id=target_cell)
    )
    impossible_role = slice_fact_locks(
        locks,
        SliceSpec(product_type="forward_attention", state_role="DAILY_REVIEW_CELL"),
    )

    assert daily_cell
    assert all(
        lock.state_role == "DAILY_REVIEW_CELL" and lock.cell_id == target_cell
        for lock in daily_cell
    )
    assert impossible_role == []


def test_stage6a_product_type_repeat_pack_is_deterministic(tmp_path_factory) -> None:
    locks = _locks(stage6a_artifact(tmp_path_factory))
    spec = SliceSpec(product_type="metric_review")
    first = build_controlled_evidence_pack(locks, [], task_context="repeat", slice_spec=spec)
    second = build_controlled_evidence_pack(locks, [], task_context="repeat", slice_spec=spec)

    assert [lock.fact_lock_id for lock in first.locked_facts] == [
        lock.fact_lock_id for lock in second.locked_facts
    ]
    assert first.pack_id == second.pack_id
    assert first.pack_hash == second.pack_hash


def test_stage6a_pack_hash_mutation_audit_passes(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    rows = read_csv(artifact / "pack_hash_mutation_audit.csv")

    assert {row["mutation_case"] for row in rows} == {
        "P1_CLAIM_VALUE_CHANGE",
        "P2_MODALITY_CHANGE",
        "P3_SPATIAL_SCOPE_CHANGE",
        "P4_REQUIRED_QUALIFIER_CHANGE",
        "P5_RENDERING_BOUNDARY_CHANGE",
        "P6_RENDERING_CONTRACT_CONTENT_CHANGE",
        "P7_SLICE_SPEC_CHANGE",
    }
    assert all(row["detected"] == "true" for row in rows)
    assert all(row["status"] == "PASS" for row in rows)


def test_stage6a_slice_immutability_audit_passes(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    rows = read_csv(artifact / "slice_immutability_audit.csv")

    assert rows
    assert all(row["mutation_count"] == "0" for row in rows)
    assert all(row["sorted_output"] == "true" for row in rows)
    assert all(row["status"] == "PASS" for row in rows)


def test_stage6a_hard_check_passes(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    rows = read_csv(artifact / "stage6a_hard_check.csv")

    assert all(row["status"] == "PASS" for row in rows)
    assert _row(rows, "issue_count")["actual"] == "0"


def test_stage6a_determinism_passes(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    rows = read_csv(artifact / "stage6a_determinism_audit.csv")

    assert rows == [
        {
            "check_name": "stage6a_semantic_content",
            "semantic_diff_count": "0",
            "status": "PASS",
        }
    ]


def _row(rows: list[dict[str, str]], check_name: str) -> dict[str, str]:
    return next(row for row in rows if row["check_name"] == check_name)


def _locks(artifact) -> list[LockedEngineeringFact]:
    return [LockedEngineeringFact(**row) for row in read_jsonl(artifact / "fact_locks.jsonl")]
