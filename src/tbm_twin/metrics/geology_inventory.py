"""Geological attribute inventory for Stage 4A1 manual mapping preparation."""

from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from datetime import date
from typing import Any

from tbm_twin.metrics.io import stable_id
from tbm_twin.metrics.models import (
    GeologicalAttentionMappingTemplateEntry,
    GeologicalAttributeInventoryRecord,
)


def build_geological_inventory(
    evidence_rows: list[dict[str, Any]],
    document_rows: list[dict[str, Any]],
    stage3b_snapshots: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Inventory structured attribute values used in Stage 3B materialized snapshots."""

    documents = {str(row["document_id"]): row for row in document_rows}
    role_counts = _snapshot_role_counts(stage3b_snapshots)
    grouped: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    reference_audit: list[dict[str, Any]] = []
    for evidence in evidence_rows:
        evidence_id = str(evidence.get("evidence_uid") or evidence.get("evidence_id"))
        attributes = evidence.get("attributes")
        if not isinstance(attributes, dict):
            attributes = {}
        for attribute_name, value in sorted(attributes.items()):
            raw_value = _raw_value(value)
            normalized = normalize_attribute_value(value)
            value_type = classify_value(value)
            key = (
                attribute_name,
                normalized,
                str(evidence.get("source_type") or "UNKNOWN"),
                str(evidence.get("evidence_type") or "UNKNOWN"),
                str(evidence.get("epistemic_status") or "UNKNOWN"),
                value_type,
            )
            item = grouped.setdefault(
                key,
                {
                    "attribute_name": attribute_name,
                    "raw_values": set(),
                    "normalized_serialization": normalized,
                    "value_type": value_type,
                    "source_type": key[2],
                    "evidence_type": key[3],
                    "epistemic_status": key[4],
                    "evidence_ids": set(),
                    "document_ids": set(),
                    "source_span_ids": set(),
                    "daily_review": 0,
                    "forward_attention": 0,
                    "local_background": 0,
                    "dates": set(),
                },
            )
            item["raw_values"].add(raw_value)
            item["evidence_ids"].add(evidence_id)
            item["document_ids"].add(str(evidence.get("document_id") or ""))
            for span in evidence.get("source_spans", []):
                if isinstance(span, dict) and span.get("span_id"):
                    item["source_span_ids"].add(str(span["span_id"]))
            counts = role_counts.get(evidence_id, {})
            item["daily_review"] += int(counts.get("daily_review", 0))
            item["forward_attention"] += int(counts.get("forward_attention", 0))
            item["local_background"] += int(counts.get("local_background", 0))
            doc = documents.get(str(evidence.get("document_id") or ""))
            doc_date = _document_date(doc)
            if doc_date is not None:
                item["dates"].add(doc_date)
            reference_audit.append(
                {
                    "evidence_id": evidence_id,
                    "attribute_name": attribute_name,
                    "normalized_serialization": normalized,
                    "used_in_stage3b_snapshot_count": sum(counts.values()),
                    "source": "attributes",
                    "status": "PASS",
                }
            )
    inventory: list[dict[str, Any]] = []
    for item in sorted(
        grouped.values(),
        key=lambda row: (
            row["attribute_name"],
            row["source_type"],
            row["evidence_type"],
            row["epistemic_status"],
            row["normalized_serialization"],
        ),
    ):
        dates = sorted(item["dates"])
        record = GeologicalAttributeInventoryRecord(
            attribute_name=item["attribute_name"],
            raw_value=" | ".join(sorted(item["raw_values"])),
            normalized_serialization=item["normalized_serialization"],
            value_type=item["value_type"],
            source_type=item["source_type"],
            evidence_type=item["evidence_type"],
            epistemic_status=item["epistemic_status"],
            evidence_count=len(item["evidence_ids"]),
            unique_document_count=len(item["document_ids"] - {""}),
            unique_source_span_count=len(item["source_span_ids"]),
            used_in_stage3b_snapshot_count=item["daily_review"]
            + item["forward_attention"]
            + item["local_background"],
            used_in_daily_review_count=item["daily_review"],
            used_in_forward_attention_count=item["forward_attention"],
            used_in_local_background_count=item["local_background"],
            first_observed_date=dates[0] if dates else None,
            last_observed_date=dates[-1] if dates else None,
            normalization_status="DETERMINISTIC_SERIALIZATION_ONLY",
            inventory_reason_codes=(
                [] if item["value_type"] != "EMPTY_OR_NULL" else ["EMPTY_OR_NULL_VALUE"]
            ),
        )
        inventory.append(record.model_dump(mode="json"))
    template_entries = [
        GeologicalAttentionMappingTemplateEntry(
            mapping_id="geo_attention_mapping_"
            + stable_id(row["attribute_name"], row["normalized_serialization"]),
            attribute_name=str(row["attribute_name"]),
            source_value=str(row["raw_value"]),
            normalized_serialization=str(row["normalized_serialization"]),
            source_type_scope=sorted(
                {
                    str(item["source_type"])
                    for item in inventory
                    if item["attribute_name"] == row["attribute_name"]
                    and item["normalized_serialization"] == row["normalized_serialization"]
                }
            ),
            evidence_type_scope=sorted(
                {
                    str(item["evidence_type"])
                    for item in inventory
                    if item["attribute_name"] == row["attribute_name"]
                    and item["normalized_serialization"] == row["normalized_serialization"]
                }
            ),
            attention_value=None,
            review_status="PENDING_MANUAL_REVIEW",
            mapping_basis=None,
            reviewer=None,
            reviewed_at=None,
            notes=None,
        ).model_dump(mode="json")
        for row in _unique_attribute_values(inventory)
    ]
    mapping_audit = [
        {
            "mapping_id": row["mapping_id"],
            "attribute_name": row["attribute_name"],
            "normalized_serialization": row["normalized_serialization"],
            "review_status": row["review_status"],
            "attention_value_is_null": row["attention_value"] is None,
            "value_type": _value_type_for_inventory(inventory, row),
            "status": "PASS" if row["attention_value"] is None else "FAIL",
        }
        for row in template_entries
    ]
    template = {
        "schema_version": "stage4a1_geological_attention_mapping_template.v1",
        "grs_status": "GEOLOGICAL_ATTENTION_MAPPING_NOT_FROZEN",
        "grci_status": "DEPENDENT_METRICS_NOT_BUILT_IN_STAGE4A1",
        "mappings": template_entries,
    }
    return inventory, template, mapping_audit, reference_audit


def normalize_attribute_value(value: Any) -> str:
    """Normalize by deterministic serialization only."""

    if value is None:
        return "null"
    if isinstance(value, str):
        return unicodedata.normalize("NFKC", value).strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def classify_value(value: Any) -> str:
    """Classify value shape without geological interpretation."""

    if value is None:
        return "EMPTY_OR_NULL"
    if isinstance(value, str):
        normalized = normalize_attribute_value(value)
        if not normalized:
            return "EMPTY_OR_NULL"
        return "FREE_TEXT_VALUE" if len(normalized) > 80 else "CATEGORICAL_VALUE"
    if isinstance(value, bool):
        return "BOOLEAN_VALUE"
    if isinstance(value, int | float):
        return "NUMERIC_VALUE"
    if isinstance(value, dict | list):
        return "STRUCTURED_OBJECT"
    return "FREE_TEXT_VALUE"


def _raw_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _snapshot_role_counts(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for snapshot in snapshots:
        for evidence_id in snapshot.get("materialized_daily_review_evidence_ids", []):
            counts[str(evidence_id)]["daily_review"] += 1
        for evidence_id in snapshot.get("materialized_forward_attention_evidence_ids", []):
            counts[str(evidence_id)]["forward_attention"] += 1
        for evidence_id in snapshot.get("materialized_local_background_evidence_ids", []):
            counts[str(evidence_id)]["local_background"] += 1
    return counts


def _document_date(document: dict[str, Any] | None) -> date | None:
    if not document:
        return None
    for key in ("available_time_extent", "document_time_extent", "observed_time_extent"):
        extent = document.get(key)
        if isinstance(extent, dict) and extent.get("start"):
            return date.fromisoformat(str(extent["start"])[:10])
    return None


def _unique_attribute_values(inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in inventory:
        key = (str(row["attribute_name"]), str(row["normalized_serialization"]))
        rows.setdefault(key, row)
    return [rows[key] for key in sorted(rows)]


def _value_type_for_inventory(inventory: list[dict[str, Any]], template_row: dict[str, Any]) -> str:
    for row in inventory:
        if (
            row["attribute_name"] == template_row["attribute_name"]
            and row["normalized_serialization"] == template_row["normalized_serialization"]
        ):
            return str(row["value_type"])
    return "UNKNOWN"
