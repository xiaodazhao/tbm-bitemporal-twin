"""Load frozen upstream rows for Stage 5C analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tbm_twin.claim_analysis.models import STAGE5B_ARTIFACT
from tbm_twin.claim_analysis.storage import read_json, read_jsonl


@dataclass(frozen=True)
class Stage5CInputs:
    """Frozen rows consumed by Stage 5C."""

    repo_root: Path
    stage5b_artifact: Path
    opportunities: list[dict[str, Any]]
    proposals: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    abstentions: list[dict[str, Any]]
    method: dict[str, Any]
    stage2_evidence: list[dict[str, Any]]
    stage3b_versions: list[dict[str, Any]]
    stage4_grs: list[dict[str, Any]]
    stage4_grci: list[dict[str, Any]]


def load_inputs(
    repo_root: Path,
    stage5b_artifact: Path = STAGE5B_ARTIFACT,
) -> Stage5CInputs:
    """Load frozen Stage5B rows plus read-only metadata from frozen upstream artifacts."""

    root = repo_root.resolve()
    artifact = stage5b_artifact if stage5b_artifact.is_absolute() else root / stage5b_artifact
    return Stage5CInputs(
        repo_root=root,
        stage5b_artifact=artifact,
        opportunities=read_jsonl(artifact / "claim_opportunities.jsonl"),
        proposals=read_jsonl(artifact / "claim_proposals.jsonl"),
        decisions=read_jsonl(artifact / "claim_decisions.jsonl"),
        claims=read_jsonl(artifact / "typed_engineering_claims.jsonl"),
        abstentions=read_jsonl(artifact / "claim_abstentions.jsonl"),
        method=read_json(artifact / "method_version.json"),
        stage2_evidence=read_jsonl(
            root / "artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl"
        ),
        stage3b_versions=read_jsonl(
            root / "artifacts/stage3b_bitemporal_epistemic_state_v1_1/"
            "bitemporal_state_versions.jsonl"
        ),
        stage4_grs=read_jsonl(
            root / "artifacts/stage4_bitemporal_state_metrics_v1_1/state_grs.jsonl"
        ),
        stage4_grci=read_jsonl(
            root / "artifacts/stage4_bitemporal_state_metrics_v1_1/state_grci.jsonl"
        ),
    )
