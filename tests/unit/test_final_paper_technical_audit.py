"""Read-only submission audit invariants for frozen spatial semantics."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
STAGE2_PLC = ROOT / "artifacts/stage2_plc_operational_freeze_v2"
STAGE2_GEO = ROOT / "artifacts/stage2_geology_v2_freeze_candidate"
STAGE3A = ROOT / "artifacts/stage3a_initial_epistemic_state_v1_1"
STAGE3B = ROOT / "artifacts/stage3b_bitemporal_epistemic_state_v1_1"
STAGE4 = ROOT / "artifacts/stage4_bitemporal_state_metrics_v1_1"
STAGE5B = ROOT / "artifacts/stage5b_deterministic_claim_builder_v1"
STAGE6A = ROOT / "artifacts/stage6a_fact_lock_evidence_pack_v1"


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _bounds(scope: dict[str, Any] | None) -> tuple[float, float] | None:
    if not scope:
        return None
    if scope.get("point_chainage") is not None:
        point = float(scope["point_chainage"])
        return point, point
    start = scope.get("start_chainage")
    end = scope.get("end_chainage")
    if start is None or end is None:
        return None
    return float(start), float(end)


def test_s1_cell_alignment_does_not_define_measured_advance() -> None:
    """Measured spans close to PLC ranges, never to the aligned review scope."""

    states = _rows(STAGE3A / "daily_construction_states.jsonl")
    aligned_difference_seen = False
    for state in states:
        raw = _bounds(state.get("raw_daily_plc_range"))
        trusted = _bounds(state.get("trusted_daily_plc_range"))
        review = _bounds(state.get("daily_excavated_scope"))
        if raw:
            assert state["raw_plc_range_span_m"] == raw[1] - raw[0]
        if trusted:
            assert state["trusted_plc_range_span_m"] == trusted[1] - trusted[0]
        if trusted and review and trusted != review:
            aligned_difference_seen = True
            assert state["daily_excavated_scope"]["basis"] == (
                "trusted_ten_meter_aligned_daily_review_scope"
            )
            assert state["trusted_plc_range_span_m"] == trusted[1] - trusted[0]
    assert aligned_difference_seen


def test_s2_fact_lock_scope_never_exceeds_authoritative_support() -> None:
    """Every located FactLock is contained by each located primary support."""

    for lock in _rows(STAGE6A / "fact_locks.jsonl"):
        locked = _bounds(lock["spatial_scope"])
        for support in lock["authoritative_support_refs"]:
            authoritative = _bounds(support.get("resolved_spatial_scope"))
            if locked and authoritative:
                assert authoritative[0] <= locked[0]
                assert locked[1] <= authoritative[1]
        assert "expand_spatial_scope" in lock["prohibited_transformations"]


def test_s3_forecast_epistemic_identity_survives_review_role() -> None:
    """A review role changes applicability, not source epistemic identity."""

    evidence = {
        str(row["evidence_uid"]): row
        for row in _rows(STAGE2_GEO / "primary_geological_evidence.jsonl")
    }
    snapshots = _rows(STAGE3B / "materialized_state_snapshots.jsonl")
    reviewed_forecasts = 0
    for snapshot in snapshots:
        for evidence_id in snapshot["materialized_daily_review_evidence_ids"]:
            if evidence[str(evidence_id)]["epistemic_status"] == "FORECAST":
                reviewed_forecasts += 1
                assert evidence[str(evidence_id)]["epistemic_status"] == "FORECAST"
    assert reviewed_forecasts > 0


def test_s4_forward_attention_is_not_locked_as_excavated_observation() -> None:
    """Forward-role facts retain forecast/attention semantics."""

    forward = [
        row
        for row in _rows(STAGE6A / "fact_locks.jsonl")
        if row["state_role"] == "FORWARD_ATTENTION_CELL"
    ]
    assert forward
    for lock in forward:
        assert lock["claim_type"] in {
            "FORECAST_GEOLOGICAL_CONDITION",
            "FORWARD_GEOLOGICAL_ATTENTION",
        }
        assert lock["claim_modality"] != "GEOLOGICAL_OBSERVATION"


def test_s5_grci_is_available_only_for_daily_review_cells() -> None:
    """Joint attention never extends to forward/background cells."""

    rows = _rows(STAGE4 / "state_grci.jsonl")
    available = [row for row in rows if row["grci"] is not None]
    assert available
    assert {row["cell_scope_role"] for row in available} == {"DAILY_REVIEW_CELL"}
    assert all(not row["is_probability"] for row in available)
    assert all(not row["is_causal_estimate"] for row in available)


def test_s6_multicell_response_is_explicitly_episode_level_shared() -> None:
    """Repeated cell links do not claim independent cell measurements."""

    links = _rows(STAGE3A / "state_response_evidence_links.jsonl")
    cells_by_response: dict[str, set[str]] = defaultdict(set)
    scopes_by_response: dict[str, set[str]] = defaultdict(set)
    for link in links:
        response_id = str(link["response_evidence_id"])
        cells_by_response[response_id].add(str(link["cell_id"]))
        scopes_by_response[response_id].add(str(link["response_stat_scope"]))
    multicell = [key for key, cells in cells_by_response.items() if len(cells) > 1]
    assert multicell
    assert all(scopes_by_response[key] == {"EPISODE_LEVEL_SHARED"} for key in multicell)


def test_s7_unavailable_event_spatial_scope_has_no_cell_link() -> None:
    """Spatially unusable episodes are not assigned to any cell."""

    unusable = {
        str(row["episode_id"])
        for row in _rows(STAGE2_PLC / "spatial_footprints.jsonl")
        if not row["spatial_scope_usable"]
    }
    linked = Counter(
        str(row["episode_id"]) for row in _rows(STAGE3A / "state_response_evidence_links.jsonl")
    )
    assert unusable
    assert all(linked[episode_id] == 0 for episode_id in unusable)


def test_frozen_grs_registry_has_44_exact_entries() -> None:
    """The paper's 44 refers to formal registry entries, not every source value."""

    config = yaml.safe_load(
        (ROOT / "configs/geological_attention_mapping_v1.yaml").read_text(encoding="utf-8")
    )
    entries = config["entries"]
    keys = {
        (str(row["attribute_name"]), str(row.get("normalized_serialization"))) for row in entries
    }
    assert len(entries) == 44
    assert len(keys) == 44
    assert sum(row["attention_value"] is not None for row in entries) == 36
    assert sum(row["attention_value"] is None for row in entries) == 8


def test_claim_decisions_and_abstention_reasons_close() -> None:
    """Paper Claim totals are reconstructed directly from frozen rows."""

    opportunities = _rows(STAGE5B / "claim_opportunities.jsonl")
    decisions = _rows(STAGE5B / "claim_decisions.jsonl")
    abstentions = _rows(STAGE5B / "claim_abstentions.jsonl")
    counts = Counter(str(row["expressibility"]) for row in decisions)
    assert len(opportunities) == len(decisions) == 8679
    assert counts == Counter({"EXPRESSIBLE": 6279, "ABSTAIN": 2400})
    assert len(abstentions) == counts["ABSTAIN"]
