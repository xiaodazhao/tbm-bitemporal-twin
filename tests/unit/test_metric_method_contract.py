from pathlib import Path

import pytest

from tbm_twin.metrics.method_contract import load_and_validate_contract


def test_metric_method_contract_matches_implementation() -> None:
    contract = load_and_validate_contract(Path.cwd())
    assert all(row["status"] == "PASS" for row in contract.audit_rows)
    assert contract.state_metric_definition_sha256
    assert contract.geological_attention_mapping_sha256
    assert contract.operational_measurement_regime_review_sha256


def test_metric_method_contract_fails_on_missing_repo(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_and_validate_contract(tmp_path)
