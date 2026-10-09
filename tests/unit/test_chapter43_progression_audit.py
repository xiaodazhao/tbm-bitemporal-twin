from __future__ import annotations

from pathlib import Path

from tbm_twin.evaluation.chapter43_progression_audit import (
    build_chapter43_progression_audit,
    intervals_intersect,
    is_strict_trusted_footprint,
)


def test_chapter43_interval_intersection_keeps_boundary_touch() -> None:
    assert intervals_intersect(100.0, 110.0, 110.0, 110.0)
    assert not intervals_intersect(100.0, 109.9, 110.0, 110.0)


def test_chapter43_strict_footprint_excludes_restored_regime() -> None:
    base = {
        "spatial_scope_usable": True,
        "trusted_spatial_scope": {"start_chainage": 100.0, "end_chainage": 101.0},
    }
    assert is_strict_trusted_footprint({**base, "chainage_regime_status": "TRUSTED"})
    assert not is_strict_trusted_footprint({**base, "chainage_regime_status": "RESTORED"})


def test_chapter43_frozen_funnel_reconciles(tmp_path: Path) -> None:
    result = build_chapter43_progression_audit(Path.cwd(), tmp_path)
    assert result["broad_context_count"] == 40
    assert result["strict_candidate_context_count"] == 19
    assert result["strict_candidate_association_count"] == 27
    assert result["final_context_count"] == 5
    assert result["final_association_count"] == 6
    assert result["final_source_type_distribution"] == {"SONIC_FORECAST": 6}
    assert result["existing_output_reconciliation"] == {
        "broad_association_key_difference_count": 0,
        "final_context_id_difference_count": 0,
    }
