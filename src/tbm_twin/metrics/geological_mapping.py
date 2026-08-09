"""Formal Stage 4A2 geological attention mapping."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Any

from tbm_twin.metrics.io import stable_id
from tbm_twin.metrics.state_metric_models import (
    STAGE4A2_METHOD_VERSION,
    GeologicalAttentionMapping,
)


def normalize_value(value: Any) -> str:
    """Use the same deterministic value normalization as the review inventory."""

    if value is None:
        return "null"
    return unicodedata.normalize("NFKC", str(value)).strip()


def build_formal_mapping(
    review_entries: list[dict[str, Any]],
    config_entries: list[dict[str, Any]],
    reviewed_at: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
    """Match the 44 reviewed source values exactly to approved mapping entries."""

    config_by_key = {
        (str(row["attribute_name"]), normalize_value(row["normalized_serialization"])): row
        for row in config_entries
    }
    rows: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for review in review_entries:
        key = (str(review["attribute_name"]), normalize_value(review["normalized_serialization"]))
        config = config_by_key.get(key)
        if config is None:
            audit.append(
                {
                    "attribute_name": key[0],
                    "normalized_serialization": key[1],
                    "status": "FAIL",
                    "reason": "MISSING_FORMAL_MAPPING_ENTRY",
                }
            )
            continue
        mapping = GeologicalAttentionMapping(
            mapping_id="geo_attention_v1_" + stable_id(key[0], key[1], STAGE4A2_METHOD_VERSION),
            dimension_name=str(config["dimension_name"]),
            attribute_name=key[0],
            normalized_serialization=key[1],
            ordinal_rank=config.get("ordinal_rank"),
            ordinal_scale_max=config.get("ordinal_scale_max"),
            attention_value=config.get("attention_value"),
            mapping_basis=str(config["mapping_basis"]),
            review_status=str(config["review_status"]),
            reviewer="PROJECT_METHOD_REVIEW",
            reviewed_at=reviewed_at or datetime.fromisoformat("1970-01-01T00:00:00+00:00"),
            engineering_ordering_rationale=str(config["mapping_basis"]),
            approval_basis="OFFLINE_PROJECT_METHOD_FREEZE",
            source_review_mapping_id=str(review["mapping_id"]),
            stage4a2_method_version=STAGE4A2_METHOD_VERSION,
        ).model_dump(mode="json")
        rows.append(mapping)
        audit.append(
            {
                "mapping_id": mapping["mapping_id"],
                "source_review_mapping_id": review["mapping_id"],
                "dimension_name": mapping["dimension_name"],
                "attribute_name": key[0],
                "normalized_serialization": key[1],
                "attention_value": mapping["attention_value"],
                "review_status": mapping["review_status"],
                "status": "PASS",
                "reason": "EXACT_REVIEW_ENTRY_MATCH",
            }
        )
    mapping_by_key = {(row["attribute_name"], row["normalized_serialization"]): row for row in rows}
    return rows, mapping_by_key, audit
