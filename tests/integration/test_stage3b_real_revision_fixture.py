from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from tbm_twin.bitemporal import Stage3BConfig, Stage3BRevisionBuilder
from tbm_twin.state.io import read_json, read_jsonl


def test_stage3b_real_revision_fixture(tmp_path: Path) -> None:
    output_dir = tmp_path / "stage3b"
    result = Stage3BRevisionBuilder(
        Stage3BConfig(
            repo_root=Path.cwd(),
            output_dir=output_dir,
            generated_at=datetime.fromisoformat("2026-07-30T14:30:00+08:00"),
            knowledge_cutoff_date=date(2024, 11, 17),
            overwrite=True,
        )
    ).build()

    assert result.version1_count == 1322
    assert result.revision_version_count > 0
    assert result.revision_event_count > 0
    assert result.revision_link_count > 0
    assert result.hard_check_issue_count == 0

    manifest = read_json(output_dir / "freeze_manifest.json")
    assert manifest["source_geology_manifest_hash"] == (
        "30b6a2916719a2f980a8d16911725e48028738be057e5b2ee6925aa353727e08"
    )
    assert manifest["source_applicability_manifest_hash"] == (
        "dd5a82af4cc3ba61a3239c3c2c8218e970975f98ddb0e9db846341f13c22fe9a"
    )
    assert manifest["source_operational_manifest_hash"] == (
        "57e4687670c4e611ac3627382fe3ddd7e48e27f80440c1a85cd0a0b4dd595660"
    )

    versions = read_jsonl(output_dir / "bitemporal_state_versions.jsonl")
    revised = [row for row in versions if row["version_number"] > 1]
    assert revised
    for version in revised[:10]:
        root = next(
            row
            for row in versions
            if row["base_stage3a_state_version_id"] == version["base_stage3a_state_version_id"]
            and row["version_number"] == 1
        )
        assert (
            version["materialized_response_evidence_ids"]
            == root["materialized_response_evidence_ids"]
        )
        assert version["materialized_episode_ids"] == root["materialized_episode_ids"]
        assert version["cell_scope_role"] == root["cell_scope_role"]

    with (output_dir / "fixed_bitemporal_case_audit.csv").open() as handle:
        fixed_rows = list(csv.DictReader(handle))
    assert fixed_rows
    assert all(row["status"] == "PASS" for row in fixed_rows)

    with (output_dir / "stage3b_hard_check.csv").open() as handle:
        hard_rows = list(csv.DictReader(handle))
    assert hard_rows == []
