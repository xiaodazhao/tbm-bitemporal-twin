"""Tests for deterministic Stage7F-B sensitivity execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from tbm_twin.bitemporal.models import Stage3BConfig
from tbm_twin.evaluation import stage7f_execution as execution
from tbm_twin.metrics.rai import build_rai_by_base_state
from tbm_twin.state.models import Stage3AStateConfig

ROOT = Path(__file__).resolve().parents[2]


def _specs() -> list[execution.ArmSpec]:
    return execution.load_arm_specs(ROOT)


def _baseline_paths() -> execution.ArmPaths:
    spec = next(row for row in _specs() if row.is_baseline)
    return execution.arm_paths(ROOT, ROOT / execution.OUTPUT_DIR, spec)


def test_all_six_arm_overrides_are_exact() -> None:
    specs = _specs()
    alternatives = [row for row in specs if not row.is_baseline]
    assert [(row.parameter_id, row.parameter_value) for row in alternatives] == [
        ("CELL_SIZE_M", 5.0),
        ("CELL_SIZE_M", 20.0),
        ("RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT", 20),
        ("RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT", 40),
        ("RAI_SATURATION_ROBUST_Z", 2.0),
        ("RAI_SATURATION_ROBUST_Z", 4.0),
    ]


def test_baseline_reuse_only() -> None:
    specs = _specs()
    assert sum(row.is_baseline for row in specs) == 1
    assert len(specs) == 7


def test_repository_config_hashes_are_stable() -> None:
    first = execution._repository_config_hashes(ROOT)
    second = execution._repository_config_hashes(ROOT)
    assert first == second


def test_frozen_corpus_has_91_dates() -> None:
    dates = execution._date_universe(_baseline_paths())
    assert len(dates) == 91
    assert (dates[0], dates[-1]) == ("2023-09-15", "2023-12-30")


def test_corpus_has_calendar_gaps() -> None:
    dates = execution._date_universe(_baseline_paths())
    assert "2023-09-16" not in dates


def test_cell_size_arm_starts_stage3a() -> None:
    assert all(
        row.expected_pipeline_start_stage == "STAGE3A"
        for row in _specs()
        if row.parameter_id == "CELL_SIZE_M"
    )


def test_only_one_cell_size_config_leaf_changes(tmp_path: Path) -> None:
    spec = next(row for row in _specs() if row.arm_id == "cell_size_m_5")
    resolved = execution.resolved_configs(ROOT, tmp_path, spec)
    baseline = execution._yaml(ROOT / "configs/construction_state.yaml")
    assert (
        execution.config_difference_count(baseline, resolved["configs"]["construction_state"]) == 1
    )


def test_raw_evidence_paths_are_frozen_constants() -> None:
    assert execution.OPERATIONAL_DIR.name == "stage2_plc_operational_freeze_v2"
    assert execution.GEOLOGY_DIR.name == "stage2_geology_v2_freeze_candidate"


def test_per_100m_denominator_uses_summed_cell_exposure(tmp_path: Path) -> None:
    stage3a = tmp_path / "stage3a"
    execution.write_jsonl(
        stage3a / "construction_state_cells.jsonl",
        [
            {"cell_id": "a", "spatial_start": 0.0, "spatial_end": 5.0},
            {"cell_id": "b", "spatial_start": 5.0, "spatial_end": 10.0},
        ],
    )
    execution.write_jsonl(
        stage3a / "initial_construction_state_versions.jsonl",
        [{"cell_id": "a"}, {"cell_id": "b"}, {"cell_id": "a"}],
    )
    paths = execution.ArmPaths(tmp_path, stage3a, tmp_path, tmp_path, tmp_path, tmp_path, tmp_path)
    assert execution.evaluated_cell_length_m(paths) == 15.0


def test_cross_resolution_layer_a_excludes_cell_id() -> None:
    source = Path(execution.__file__).read_text(encoding="utf-8")
    assert 'keys = ["valid_date", "claim_type"]' in source


def test_history_arm_starts_stage4a1() -> None:
    assert all(
        row.expected_pipeline_start_stage == "STAGE4A1"
        for row in _specs()
        if row.parameter_id == "RAI_MINIMUM_HISTORICAL_SAMPLE_COUNT"
    )


def test_history_paths_reuse_frozen_geometry() -> None:
    spec = next(row for row in _specs() if row.arm_id == "rai_history_min_samples_20")
    paths = execution.arm_paths(ROOT, ROOT / execution.OUTPUT_DIR, spec)
    assert paths.stage3a == ROOT / execution.FROZEN_STAGE3A
    assert paths.stage3b == ROOT / execution.FROZEN_STAGE3B


def test_semantic_claim_pairing_is_unique_for_frozen_baseline() -> None:
    rows = execution.semantic_transition_matrix(
        _baseline_paths(), _baseline_paths(), "baseline_self"
    )
    assert sum(row["count"] for row in rows if "_TO_" in row["transition"]) == 8679


def test_semantic_pair_key_excludes_decision_and_values() -> None:
    source = Path(execution.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("def semantic_transition_matrix") : source.index("def grci_identity_rows")
    ]
    key_block = block[block.index("key_fields") : block.index("def index")]
    assert "decision" not in key_block
    assert "metric_value" not in key_block
    assert "claim_value" not in key_block


def test_saturation_arm_starts_stage4a2() -> None:
    assert all(
        row.expected_pipeline_start_stage == "STAGE4A2"
        for row in _specs()
        if row.parameter_id == "RAI_SATURATION_ROBUST_Z"
    )


def test_saturation_paths_reuse_frozen_stage4a1() -> None:
    spec = next(row for row in _specs() if row.arm_id == "rai_saturation_robust_z_2")
    paths = execution.arm_paths(ROOT, ROOT / execution.OUTPUT_DIR, spec)
    assert paths.stage4a1 == ROOT / execution.FROZEN_STAGE4A1


def test_rai_saturation_override_changes_attention_only() -> None:
    profile = {
        "base_stage3a_state_version_id": "s",
        "response_profile_id": "p",
        "valid_date": "2023-01-01",
        "cell_id": "c",
        "response_evidence_ids": ["t", "q", "a", "n"],
    }
    components = {
        rid: {
            "response_evidence_id": rid,
            "episode_id": "e",
            "channel_name": channel,
            "absolute_robust_z": 1.0,
        }
        for rid, channel in {
            "t": "total_thrust",
            "q": "cutterhead_torque",
            "a": "advance_speed",
            "n": "penetration",
        }.items()
    }
    with execution._rai_saturation(2.0):
        low = build_rai_by_base_state([profile], components)[0]["s"]
    with execution._rai_saturation(4.0):
        high = build_rai_by_base_state([profile], components)[0]["s"]
    assert low["rai"] == 0.5
    assert high["rai"] == 0.25
    assert low["rai_status"] == high["rai_status"] == "AVAILABLE"


def test_invalid_saturation_fails_closed() -> None:
    with pytest.raises(ValueError, match="must be positive"), execution._rai_saturation(0):
        pass


def test_grci_is_product_for_frozen_baseline() -> None:
    assert (
        execution.grci_identity_rows(
            next(row for row in _specs() if row.is_baseline), _baseline_paths()
        )
        == []
    )


def test_missing_metric_is_not_zero() -> None:
    row = next(
        row
        for row in execution.read_jsonl(_baseline_paths().stage4 / "state_rai.jsonl")
        if row["rai"] is None
    )
    assert row["rai"] is None
    assert row["rai_status"] != "AVAILABLE"


def test_constant_vector_spearman_is_not_evaluable() -> None:
    base = [
        {
            "valid_date": str(index),
            "state_role": "R",
            "metric_name": "RAI",
            "summary_statistic": "median",
            "summary_status": "AVAILABLE",
            "value": 1.0,
        }
        for index in range(3)
    ]
    alternative = [{**row, "value": float(index)} for index, row in enumerate(base)]
    result = execution.paired_statistics(base, alternative, arm_id="x")[0]
    assert result["status"] == "NOT_EVALUABLE"
    assert result["spearman_rank_correlation"] is None


def test_small_pair_count_is_not_evaluable() -> None:
    base = [
        {
            "valid_date": "d",
            "state_role": "R",
            "metric_name": "RAI",
            "summary_statistic": "median",
            "summary_status": "AVAILABLE",
            "value": 1.0,
        }
    ]
    result = execution.paired_statistics(base, base, arm_id="x")[0]
    assert result["status"] == "NOT_EVALUABLE"
    assert result["reason"] == "PAIRED_N_LT_3"


def test_claim_decisions_partition_frozen_universe() -> None:
    rows = execution.claim_rows(_baseline_paths())
    assert len(rows) == 8679
    assert counter_like(rows, "decision") == {"EXPRESSIBLE": 6279, "ABSTAIN": 2400}


def counter_like(rows: list[dict[str, object]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = str(row[key])
        result[value] = result.get(value, 0) + 1
    return result


def test_layer_a_key_is_exact() -> None:
    source = Path(execution.__file__).read_text(encoding="utf-8")
    assert 'keys = ["valid_date", "claim_type"]' in source


def test_layer_b_key_is_exact() -> None:
    source = Path(execution.__file__).read_text(encoding="utf-8")
    assert 'keys += ["state_role", "epistemic_status"]' in source


def test_no_automatic_robustness_threshold() -> None:
    source = Path(execution.__file__).read_text(encoding="utf-8")
    assert "Spearman >" not in source
    assert '"automatic_stability_classification": "NOT_PERFORMED"' in source


def test_no_best_parameter_field() -> None:
    source = Path(execution.__file__).read_text(encoding="utf-8").lower()
    assert "best_cell_size" not in source
    assert "optimal_history_count" not in source
    assert "recommended_parameter" not in source


def test_no_llm_or_api_transport_import() -> None:
    source = Path(execution.__file__).read_text(encoding="utf-8")
    assert "from openai" not in source
    assert "import openai" not in source
    assert "OpenAI(" not in source
    assert "requests." not in source


def test_canonical_replay_hash_is_order_stable_for_mappings() -> None:
    assert execution.canonical_hash({"a": 1, "b": 2}) == execution.canonical_hash({"b": 2, "a": 1})


def test_stage3b_sensitivity_mode_defaults_off() -> None:
    assert "sensitivity_mode" not in Stage3BConfig.model_fields
    assert issubclass(execution.SensitivityStage3BRevisionBuilder, execution.Stage3BRevisionBuilder)


def test_stage3a_sensitivity_mode_defaults_off() -> None:
    assert "sensitivity_mode" not in Stage3AStateConfig.model_fields
    assert issubclass(execution.SensitivityStage3AStateBuilder, execution.Stage3AStateBuilder)


def test_sensitivity_mode_forbids_duplicate_or_overallocated_links() -> None:
    source = Path(execution.__file__).read_text(encoding="utf-8")
    assert 'int(row["cell_link_count"]) <= 1' in source
    assert 'float(row["linked_overlap_length_m"])' in source


def test_protocol_defines_nonprobabilistic_product() -> None:
    protocol = execution.read_json(
        ROOT / execution.PROTOCOL_DIR / "stage7f_sensitivity_protocol.json"
    )
    assert (
        protocol["frozen_metric_semantics"]["GRCI"]["operator"]
        == "NONPROBABILISTIC_CONJUNCTIVE_PRODUCT"
    )


def test_protocol_defines_max_then_mean_grs() -> None:
    protocol = execution.read_json(
        ROOT / execution.PROTOCOL_DIR / "stage7f_sensitivity_protocol.json"
    )
    grs = protocol["frozen_metric_semantics"]["GRS"]
    assert grs == {
        "dimension_operator": "max_mapped_attention",
        "state_operator": "mean_non_null_dimension_attention",
    }


def test_claim_contract_hash_is_nonempty() -> None:
    assert len(execution.sha256_file(ROOT / "configs/claim_contract_v1.yaml")) == 64


def test_baseline_exposure_matches_all_initial_states() -> None:
    paths = _baseline_paths()
    versions = execution.read_jsonl(paths.stage3a / "initial_construction_state_versions.jsonl")
    assert execution.evaluated_cell_length_m(paths) == len(versions) * 10.0


def test_per_day_denominator_is_always_91() -> None:
    endpoint = execution.common_endpoint(
        next(row for row in _specs() if row.is_baseline), _baseline_paths()
    )
    assert endpoint["expressible_per_day"] == 6279 / 91


def test_output_table_registry_contains_every_required_family() -> None:
    names = set(execution.OUTPUT_TABLES)
    assert "cell_size_metric_pairwise_statistics.csv" in names
    assert "rai_history_claim_transition_matrix.csv" in names
    assert "rai_saturation_monotonicity_audit.csv" in names
    assert "grci_product_identity_audit.csv" in names


def test_arm_local_resolved_config_does_not_modify_repository(tmp_path: Path) -> None:
    before = execution._repository_config_hashes(ROOT)
    spec = next(row for row in _specs() if row.arm_id == "rai_history_min_samples_40")
    execution.resolved_configs(ROOT, tmp_path, spec)
    assert execution._repository_config_hashes(ROOT) == before


def test_baseline_is_not_executable() -> None:
    spec = next(row for row in _specs() if row.is_baseline)
    with pytest.raises(ValueError, match="reused"):
        execution.execute_arm(ROOT, ROOT / "unused", spec)


def test_every_arm_forbids_llm_and_api() -> None:
    rows = execution.read_csv(ROOT / execution.PROTOCOL_DIR / "stage7f_arm_manifest.csv")
    assert all(row["llm_required"] == "False" and row["api_required"] == "False" for row in rows)
