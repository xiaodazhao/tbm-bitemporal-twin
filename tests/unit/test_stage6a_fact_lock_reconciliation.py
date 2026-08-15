"""Stage6A FactLock reconciliation tests."""

from __future__ import annotations

from tests.unit.stage6a_helpers import read_csv, read_jsonl, stage6a_artifact


def test_stage6a_fact_lock_count_equals_expressible_claims(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    locks = read_jsonl(artifact / "fact_locks.jsonl")
    reconciliation = read_csv(artifact / "fact_lock_reconciliation.csv")

    assert len(locks) == 6279
    assert (
        _row(reconciliation, "fact_lock_count_equals_expressible_claim_count")["status"] == "PASS"
    )
    assert _row(reconciliation, "fact_lock_from_abstain_count")["left_count"] == "0"
    assert _row(reconciliation, "orphan_fact_lock")["left_count"] == "0"
    assert _row(reconciliation, "missing_fact_lock")["left_count"] == "0"


def test_stage6a_fact_lock_ids_are_unique(tmp_path_factory) -> None:
    artifact = stage6a_artifact(tmp_path_factory)
    locks = read_jsonl(artifact / "fact_locks.jsonl")

    assert len({row["fact_lock_id"] for row in locks}) == len(locks)
    assert len({row["lock_hash"] for row in locks}) == len(locks)


def _row(rows: list[dict[str, str]], check_name: str) -> dict[str, str]:
    return next(row for row in rows if row["check_name"] == check_name)
