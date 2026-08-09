"""Formal RAI computation for Stage 4A2."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from tbm_twin.metrics.io import stable_id
from tbm_twin.metrics.state_metric_models import (
    STAGE4A2_METHOD_VERSION,
    RAIFamilyComponent,
    StateRAI,
)

SCALAR_FAMILIES = {
    "LOAD_RESPONSE": ["total_thrust", "cutterhead_torque"],
    "ADVANCE_KINEMATIC_RESPONSE": ["advance_speed", "penetration"],
}
RPM_CHANNEL = "cutterhead_rpm"
RAI_SATURATION_ROBUST_Z = 3.0


def build_rai_by_base_state(
    profiles: list[dict[str, Any]],
    components_by_response_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Compute base-state RAI from cell profiles and Stage4A1 response components."""

    rai_by_base: dict[str, dict[str, Any]] = {}
    family_rows: list[dict[str, Any]] = []
    support_audit: list[dict[str, Any]] = []
    for profile in profiles:
        base_id = str(profile["base_stage3a_state_version_id"])
        response_ids = sorted({str(item) for item in profile.get("response_evidence_ids", [])})
        response_components = [
            components_by_response_id[response_id]
            for response_id in response_ids
            if response_id in components_by_response_id
        ]
        families: dict[str, dict[str, Any]] = {}
        for family, channels in SCALAR_FAMILIES.items():
            row = _family_component(profile, response_components, family, channels)
            families[family] = row
            family_rows.append(row)
        rai_row = _state_rai_base(profile, families, response_ids, response_components)
        rai_by_base[base_id] = rai_row
        support_audit.append(
            {
                "base_stage3a_state_version_id": base_id,
                "response_profile_id": profile["response_profile_id"],
                "all_cell_response_evidence_count": len(response_ids),
                "scalar_support_count": len(rai_row["scalar_support_response_evidence_ids"]),
                "diagnostic_count": len(rai_row["diagnostic_response_evidence_ids"]),
                "rpm_cell_evidence_count": len(rai_row["diagnostic_response_evidence_ids"]),
                "rpm_scalar_support_count": sum(
                    1
                    for response_id in rai_row["scalar_support_response_evidence_ids"]
                    if components_by_response_id.get(response_id, {}).get("channel_name")
                    == RPM_CHANNEL
                ),
                "load_support_count": len(
                    families["LOAD_RESPONSE"]["family_support_response_evidence_ids"]
                ),
                "kinematic_support_count": len(
                    families["ADVANCE_KINEMATIC_RESPONSE"]["family_support_response_evidence_ids"]
                ),
                "load_status": families["LOAD_RESPONSE"]["component_status"],
                "kinematic_status": families["ADVANCE_KINEMATIC_RESPONSE"]["component_status"],
                "rai_status": rai_row["rai_status"],
                "status": "PASS"
                if not any(
                    components_by_response_id.get(response_id, {}).get("channel_name")
                    == RPM_CHANNEL
                    for response_id in rai_row["scalar_support_response_evidence_ids"]
                )
                else "FAIL",
            }
        )
    return rai_by_base, family_rows, support_audit


def bind_rai_to_bitemporal_versions(
    bitemporal_versions: list[dict[str, Any]],
    rai_by_base: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create one StateRAI row per bitemporal version; values are invariant by base state."""

    rows: list[dict[str, Any]] = []
    for version in bitemporal_versions:
        base = rai_by_base[str(version["base_stage3a_state_version_id"])]
        model = StateRAI(
            state_rai_id="state_rai_"
            + stable_id(str(version["bitemporal_version_id"]), STAGE4A2_METHOD_VERSION),
            bitemporal_version_id=str(version["bitemporal_version_id"]),
            base_stage3a_state_version_id=str(version["base_stage3a_state_version_id"]),
            response_profile_id=base["response_profile_id"],
            valid_date=date.fromisoformat(str(version["valid_date"])),
            knowledge_time_start_local_date=date.fromisoformat(
                str(version["knowledge_time_start_local_date"])
            ),
            cell_id=str(version["cell_id"]),
            cell_scope_role=str(version["cell_scope_role"]),
            rai=base["rai"],
            rai_status=base["rai_status"],
            rai_raw_deviation=base["rai_raw_deviation"],
            dominant_response_family=base["dominant_response_family"],
            co_dominant_response_families=base.get(
                "co_dominant_response_families",
                [base["dominant_response_family"]] if base["dominant_response_family"] else [],
            ),
            response_family_attention_tie=base.get("response_family_attention_tie", False),
            raw_deviation_dominant_family=base.get(
                "raw_deviation_dominant_family", base["dominant_response_family"]
            ),
            raw_deviation_dominant_value=base.get(
                "raw_deviation_dominant_value", base["rai_raw_deviation"]
            ),
            family_attention_values=base["family_attention_values"],
            support_episode_count=base["support_episode_count"],
            support_response_evidence_count=base["support_response_evidence_count"],
            support_response_evidence_ids=base["support_response_evidence_ids"],
            scalar_support_response_evidence_ids=base.get(
                "scalar_support_response_evidence_ids", base["support_response_evidence_ids"]
            ),
            diagnostic_response_evidence_ids=base.get("diagnostic_response_evidence_ids", []),
            excluded_scalar_response_evidence_ids=base.get(
                "excluded_scalar_response_evidence_ids", []
            ),
            excluded_scalar_response_reasons=base.get("excluded_scalar_response_reasons", {}),
            quality_flags=base["quality_flags"],
            reason_codes=base["reason_codes"],
            is_probability=False,
            is_causal_estimate=False,
            stage4a2_method_version=STAGE4A2_METHOD_VERSION,
        )
        rows.append(model.model_dump(mode="json"))
    return rows


def _family_component(
    profile: dict[str, Any],
    components: list[dict[str, Any]],
    family: str,
    channels: list[str],
) -> dict[str, Any]:
    channel_values: dict[str, list[float]] = defaultdict(list)
    channel_response_ids: dict[str, set[str]] = defaultdict(set)
    episode_ids: set[str] = set()
    for component in components:
        channel = str(component["channel_name"])
        if channel not in channels:
            continue
        value = component.get("absolute_robust_z")
        if value is not None:
            channel_values[channel].append(float(value))
            channel_response_ids[channel].add(str(component["response_evidence_id"]))
            episode_ids.add(str(component["episode_id"]))
    medians = {
        channel: _median(channel_values[channel]) if channel_values[channel] else None
        for channel in channels
    }
    available = {channel: value for channel, value in medians.items() if value is not None}
    response_ids = sorted({item for values in channel_response_ids.values() for item in values})
    if len(available) == len(channels):
        raw_deviation = max(available.values())
        dominant = max(available, key=lambda channel: available[channel])
        attention = min(raw_deviation / RAI_SATURATION_ROBUST_Z, 1.0)
        status = "AVAILABLE"
        reasons: list[str] = []
    elif not components:
        raw_deviation = None
        dominant = None
        attention = None
        status = "NO_CELL_LINKED_OPERATIONAL_RESPONSE"
        reasons = ["NO_CELL_LINKED_OPERATIONAL_RESPONSE"]
    elif not available:
        raw_deviation = None
        dominant = None
        attention = None
        status = "INSUFFICIENT_CAUSAL_BASELINE"
        reasons = ["INSUFFICIENT_CAUSAL_BASELINE"]
    else:
        raw_deviation = None
        dominant = None
        attention = None
        status = "INCOMPLETE_RESPONSE_FAMILY_SUPPORT"
        reasons = ["INCOMPLETE_RESPONSE_FAMILY_SUPPORT"]
    return RAIFamilyComponent(
        rai_component_id="rai_family_component_"
        + stable_id(str(profile["base_stage3a_state_version_id"]), family, STAGE4A2_METHOD_VERSION),
        base_stage3a_state_version_id=str(profile["base_stage3a_state_version_id"]),
        response_profile_id=str(profile["response_profile_id"]),
        valid_date=date.fromisoformat(str(profile["valid_date"])),
        cell_id=str(profile["cell_id"]),
        response_family=family,
        family_raw_deviation=raw_deviation,
        family_attention=attention,
        family_support_channel_count=len(available),
        family_support_episode_count=len(episode_ids),
        family_support_response_evidence_ids=response_ids,
        dominant_channel=dominant,
        component_status=status,
        reason_codes=reasons,
        stage4a2_method_version=STAGE4A2_METHOD_VERSION,
    ).model_dump(mode="json")


def _state_rai_base(
    profile: dict[str, Any],
    families: dict[str, dict[str, Any]],
    response_ids: list[str],
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    values = {
        family: row["family_attention"]
        for family, row in families.items()
        if row["component_status"] == "AVAILABLE"
    }
    scalar_response_ids = sorted(
        {
            response_id
            for row in families.values()
            for response_id in row["family_support_response_evidence_ids"]
        }
    )
    diagnostic_response_ids = sorted(
        {
            str(component["response_evidence_id"])
            for component in components
            if component["channel_name"] == RPM_CHANNEL
        }
    )
    if not response_ids:
        status = "NO_CELL_LINKED_OPERATIONAL_RESPONSE"
        rai = None
        raw = None
        dominant = None
        co_dominant: list[str] = []
        attention_tie = False
        raw_dominant = None
        raw_dominant_value = None
        reasons = ["NO_CELL_LINKED_OPERATIONAL_RESPONSE"]
    elif len(values) < len(SCALAR_FAMILIES):
        statuses = {row["component_status"] for row in families.values()}
        status = (
            "INSUFFICIENT_CAUSAL_BASELINE"
            if statuses == {"INSUFFICIENT_CAUSAL_BASELINE"}
            else "INCOMPLETE_RESPONSE_FAMILY_SUPPORT"
        )
        rai = None
        raw = None
        dominant = None
        co_dominant = []
        attention_tie = False
        raw_dominant = None
        raw_dominant_value = None
        reasons = [status]
    else:
        max_attention = max(float(value) for value in values.values() if value is not None)
        co_dominant = sorted(
            family for family, value in values.items() if float(value) == max_attention
        )
        attention_tie = len(co_dominant) > 1
        dominant = co_dominant[0] if not attention_tie else None
        rai = max_attention
        raw_values = {
            family: float(row["family_raw_deviation"])
            for family, row in families.items()
            if row["family_raw_deviation"] is not None
        }
        raw = max(raw_values.values())
        raw_winners = sorted(family for family, value in raw_values.items() if value == raw)
        raw_dominant = raw_winners[0] if len(raw_winners) == 1 else None
        raw_dominant_value = raw
        status = "AVAILABLE"
        reasons = []
    support_episode_ids = {
        str(component["episode_id"])
        for component in components
        if component["channel_name"]
        in {channel for channels in SCALAR_FAMILIES.values() for channel in channels}
    }
    return {
        "base_stage3a_state_version_id": profile["base_stage3a_state_version_id"],
        "response_profile_id": profile["response_profile_id"],
        "rai": rai,
        "rai_status": status,
        "rai_raw_deviation": raw,
        "dominant_response_family": dominant,
        "co_dominant_response_families": co_dominant,
        "response_family_attention_tie": attention_tie,
        "raw_deviation_dominant_family": raw_dominant,
        "raw_deviation_dominant_value": raw_dominant_value,
        "family_attention_values": {
            family: families[family]["family_attention"] for family in SCALAR_FAMILIES
        },
        "support_episode_count": len(support_episode_ids),
        "support_response_evidence_count": len(scalar_response_ids),
        "support_response_evidence_ids": scalar_response_ids,
        "scalar_support_response_evidence_ids": scalar_response_ids,
        "diagnostic_response_evidence_ids": diagnostic_response_ids,
        "excluded_scalar_response_evidence_ids": diagnostic_response_ids,
        "excluded_scalar_response_reasons": {
            response_id: "DIAGNOSTIC_ONLY_UNRESOLVED_MEASUREMENT_REGIME"
            for response_id in diagnostic_response_ids
        },
        "quality_flags": [],
        "reason_codes": reasons,
    }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
