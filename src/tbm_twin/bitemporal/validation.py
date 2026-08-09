"""Validation entry points for Stage 3B artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tbm_twin.state.io import read_jsonl


def validate_business_id_uniqueness(artifact_dir: Path) -> dict[str, Any]:
    """Validate uniqueness of core Stage 3B business IDs."""

    ids: list[str] = []
    for filename, key in [
        ("bitemporal_state_versions.jsonl", "bitemporal_version_id"),
        ("knowledge_revision_events.jsonl", "revision_event_id"),
        ("revision_geological_evidence_links.jsonl", "revision_link_id"),
        ("historical_revision_applicability.jsonl", "revision_applicability_id"),
    ]:
        ids.extend(str(row[key]) for row in read_jsonl(artifact_dir / filename))
    return {
        "id_count": len(ids),
        "unique_id_count": len(set(ids)),
        "valid": len(ids) == len(set(ids)),
    }
