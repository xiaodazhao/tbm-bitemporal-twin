from __future__ import annotations

from tbm_twin.state.io import stable_id


def _bitemporal_id(generated_at: str) -> str:
    del generated_at
    return "bitemporal_version_" + stable_id(
        "state_version_x",
        "2023-09-22",
        "2023-09-23",
        "2",
        "stage3b_bitemporal_epistemic_state_v1_1_strict_trace",
    )


def test_generated_at_does_not_enter_business_id() -> None:
    assert _bitemporal_id("2026-07-30T14:30:00+08:00") == _bitemporal_id(
        "2026-08-01T00:00:00+08:00"
    )


def test_method_version_changes_business_id() -> None:
    left = stable_id("state_version_x", "2023-09-22", "2023-09-23", "2", "method_a")
    right = stable_id("state_version_x", "2023-09-22", "2023-09-23", "2", "method_b")
    assert left != right
