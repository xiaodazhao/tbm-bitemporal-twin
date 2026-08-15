"""Stage 5C revision lineage closure tests."""

from __future__ import annotations

from tbm_twin.claim_analysis.analysis import (
    _revision_analysis,
    _revision_comparison_key,
    _revision_transition_from_flags,
    _transition_flags,
)
from tests.unit.stage5c_helpers import read_csv, stage5c_artifact


def test_stage5c_revision_uses_authoritative_version_number(tmp_path_factory) -> None:
    artifact = stage5c_artifact(tmp_path_factory)
    rows = read_csv(artifact / "revision_lineage_order_audit.csv")
    target = next(
        row
        for row in rows
        if row["base_stage3a_state_version_id"] == "state_version_ed221b03b2e40479c7ba42c2"
    )

    assert (
        target["reported_v1_bitemporal_version_id"] == "bitemporal_version_72e60100df4f5a214d5119f4"
    )
    assert target["reported_v1_version_number"] == "1"
    assert (
        target["reported_v2_bitemporal_version_id"] == "bitemporal_version_43194bb14cfc647ee8b539c8"
    )
    assert target["reported_v2_version_number"] == "2"
    assert target["supersession_valid"] == "true"


def test_stage5c_revision_supersedes_lineage_fixture() -> None:
    records = [_record("v_zzz", 0.5), _record("v_aaa", 0.5)]
    stage3b_versions = [
        {
            "base_stage3a_state_version_id": "base",
            "bitemporal_version_id": "v_zzz",
            "version_number": 1,
            "supersedes_bitemporal_version_id": None,
            "valid_date": "2023-01-01",
            "cell_id": "cell",
            "cell_scope_role": "DAILY_REVIEW_CELL",
        },
        {
            "base_stage3a_state_version_id": "base",
            "bitemporal_version_id": "v_aaa",
            "version_number": 2,
            "supersedes_bitemporal_version_id": "v_zzz",
            "valid_date": "2023-01-01",
            "cell_id": "cell",
            "cell_scope_role": "DAILY_REVIEW_CELL",
        },
    ]

    chains, _, _, lineage, _, _ = _revision_analysis(records, stage3b_versions, {}, {})

    assert chains[0]["v1_bitemporal_version_id"] == "v_zzz"
    assert chains[0]["v2_bitemporal_version_id"] == "v_aaa"
    assert lineage[0]["status"] == "PASS"
    assert lineage[0]["legacy_lexicographic_direction_error"] == 1


def test_stage5c_revision_comparison_key_excludes_metric_wrapper_payload() -> None:
    left = _record("v1", 0.58, metric_id="state_grs_A", metric_status="AVAILABLE")
    right = _record("v2", 0.74, metric_id="state_grs_B", metric_status="DIFFERENT")

    assert _revision_comparison_key(left) == _revision_comparison_key(right)
    flags = _transition_flags(left, right, {}, {})

    assert flags["business_claim_value_changed"] == "true"
    assert _revision_transition_from_flags(flags, left, right) == "CLAIM_VALUE_CHANGED"


def test_stage5c_revision_wrapper_support_id_is_not_semantic_support_change() -> None:
    left = _record("v1", 0.58, metric_id="state_grs_A")
    right = _record("v2", 0.58, metric_id="state_grs_B")
    left["decision"]["resolved_support_refs"][0]["support_id"] = "state_grs_A"
    right["decision"]["resolved_support_refs"][0]["support_id"] = "state_grs_B"

    flags = _transition_flags(left, right, {}, {})

    assert flags["wrapper_identity_only_support_change"] == "true"
    assert flags["support_semantics_changed"] == "false"
    assert _revision_transition_from_flags(flags, left, right) == "UNCHANGED_EXPRESSIBLE"


def _record(
    version_id: str,
    value: float,
    *,
    metric_id: str = "state_grs_x",
    metric_status: str = "AVAILABLE",
) -> dict:
    return {
        "claim_type": "GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW",
        "state_role": "DAILY_REVIEW_CELL",
        "valid_date": "2023-01-01",
        "expressible": True,
        "abstained": False,
        "abstention_reason": "",
        "opportunity": {
            "opportunity_id": f"opp_{version_id}",
            "base_stage3a_state_version_id": "base",
            "bitemporal_version_id": version_id,
            "valid_date": "2023-01-01",
            "cell_id": "cell",
            "state_role": "DAILY_REVIEW_CELL",
            "source_kind": "STATE_GRS",
            "source_object_ids": [metric_id],
            "payload": {
                "metric_id": metric_id,
                "metric_name": "GRS",
                "metric_status": metric_status,
                "metric_value": value,
            },
        },
        "proposal": {
            "proposal_id": f"proposal_{version_id}",
            "claim_value": {
                "metric_name": "GRS",
                "metric_value": value,
                "metric_status": metric_status,
                "metric_semantics": "GEOLOGICAL_EVIDENCE_ATTENTION",
                "is_probability": False,
                "is_hazard_probability": False,
                "is_causal_estimate": False,
                "source_metric_id": metric_id,
            },
        },
        "decision": {
            "decision_id": f"decision_{version_id}",
            "expressibility": "EXPRESSIBLE",
            "resolved_support_refs": [
                {
                    "support_kind": "STATE_GRS",
                    "support_id": metric_id,
                    "support_role": "PRIMARY_SUPPORT",
                }
            ],
        },
    }
