"""Stage 5B formal method metadata tests."""

from __future__ import annotations

from tbm_twin.claim_building.models import (
    STAGE5B_FORMAL_METHOD_VERSION,
    STAGE5B_SCHEMA_VERSION,
)
from tests.unit.stage5b_helpers import read_json, stage5b_formal_artifact


def test_stage5b_formal_method_metadata(tmp_path_factory) -> None:
    artifact = stage5b_formal_artifact(tmp_path_factory)
    method = read_json(artifact / "method_version.json")

    assert method["method_version"] == STAGE5B_FORMAL_METHOD_VERSION
    assert method["schema_version"] == STAGE5B_SCHEMA_VERSION
    assert method["status"] == "FROZEN"
    assert method["generated_at"] == "2026-08-11T17:15:00+08:00"
    assert method["generated_at_semantics"] == "OFFLINE_RECONSTRUCTION_TIME"
    assert method["upstream_stage5a_tag"] == "stage5a-claim-contract-v1.1-frozen"
    assert method["stage5b_modifies_stage5a_authorization_semantics"] is False
    assert method["stage4_metric_formula_changed"] is False
    assert method["stage4_metric_semantics_changed"] is False
    assert method["uses_llm"] is False
    assert method["generates_natural_language"] is False
    assert method["stage5c_implemented"] is False
