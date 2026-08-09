"""Cell response profile construction for Stage 4A1."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date
from typing import Any

from tbm_twin.metrics.io import stable_id
from tbm_twin.metrics.models import (
    STAGE4A1_METHOD_VERSION,
    BitemporalResponseProfileBinding,
    CellOperationalResponseProfile,
    ChannelDeviationSummary,
)


def build_response_profiles(
    state_versions: list[dict[str, Any]],
    response_links: list[dict[str, Any]],
    components_by_response_id: dict[str, dict[str, Any]],
    channels: list[str],
    coverage_by_response_id: dict[str, str],
    source_stage3a_manifest_hash: str,
    source_operational_manifest_hash: str,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Build one descriptive response profile per Stage 3A state version."""

    links_by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for link in response_links:
        links_by_state[str(link["state_version_id"])].append(link)
    profiles: list[dict[str, Any]] = []
    profile_by_state_id: dict[str, dict[str, Any]] = {}
    coverage_audit: list[dict[str, Any]] = []
    multicell_audit = _build_multicell_audit(response_links, components_by_response_id)
    for version in state_versions:
        state_id = str(version["state_version_id"])
        links = links_by_state.get(state_id, [])
        response_ids = sorted({str(link["response_evidence_id"]) for link in links})
        components = [
            components_by_response_id[item]
            for item in response_ids
            if item in components_by_response_id
        ]
        summaries = [_summarize_channel(channel, components) for channel in channels]
        present_channels = sorted(
            {
                str(component["channel_name"])
                for component in components
                if component["channel_name"] in channels
            }
        )
        linked_non_cell = [
            response_id
            for response_id in response_ids
            if coverage_by_response_id.get(response_id) != "CELL_LINKED"
        ]
        reason_codes: list[str] = []
        if not response_ids:
            reason_codes.append("NO_CELL_LINKED_RESPONSE_EVIDENCE")
        if linked_non_cell:
            reason_codes.append("NON_CELL_COVERAGE_RESPONSE_IN_PROFILE")
        profile_id = "response_profile_" + stable_id(state_id, STAGE4A1_METHOD_VERSION)
        model = CellOperationalResponseProfile(
            response_profile_id=profile_id,
            base_stage3a_state_version_id=state_id,
            daily_state_id=str(version["daily_state_id"]),
            cell_id=str(version["cell_id"]),
            cell_scope_role=str(version["cell_scope_role"]),
            valid_date=date.fromisoformat(str(version["valid_date"])),
            episode_ids=sorted({str(item) for item in version.get("episode_ids", [])}),
            response_evidence_ids=response_ids,
            response_link_ids=sorted(str(link["link_id"]) for link in links),
            response_component_ids=sorted(
                str(component["component_id"]) for component in components
            ),
            channel_names_present=present_channels,
            available_channel_count=len(present_channels),
            unavailable_channel_count=len(channels) - len(present_channels),
            per_channel_summary=summaries,
            shared_episode_statistic_present=any(
                link.get("response_stat_scope") == "EPISODE_LEVEL_SHARED" for link in links
            ),
            point_response_present=any(
                link.get("trusted_overlap_kind") == "POINT" for link in links
            ),
            response_stat_scopes=sorted({str(link.get("response_stat_scope")) for link in links}),
            profile_status=(
                "DESCRIPTIVE_PROFILE_AVAILABLE" if response_ids else "NO_CELL_LINKED_RESPONSE"
            ),
            profile_reason_codes=reason_codes,
            source_stage3a_manifest_hash=source_stage3a_manifest_hash,
            source_operational_manifest_hash=source_operational_manifest_hash,
            metric_foundation_method_version=STAGE4A1_METHOD_VERSION,
        )
        row = model.model_dump(mode="json")
        profiles.append(row)
        profile_by_state_id[state_id] = row
        coverage_audit.append(
            {
                "base_stage3a_state_version_id": state_id,
                "response_profile_id": profile_id,
                "cell_linked_response_count": len(response_ids),
                "non_cell_coverage_response_count": len(linked_non_cell),
                "profile_status": row["profile_status"],
                "status": "PASS" if not linked_non_cell else "FAIL",
            }
        )
    return profiles, profile_by_state_id, coverage_audit, multicell_audit


def build_bitemporal_profile_bindings(
    bitemporal_versions: list[dict[str, Any]],
    profile_by_state_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bind each Stage 3B bitemporal version to its base Stage 3A response profile."""

    bindings: list[dict[str, Any]] = []
    by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for version in bitemporal_versions:
        base_id = str(version["base_stage3a_state_version_id"])
        profile = profile_by_state_id[base_id]
        binding_body = stable_id(
            str(version["bitemporal_version_id"]),
            profile["response_profile_id"],
            STAGE4A1_METHOD_VERSION,
        )
        model = BitemporalResponseProfileBinding(
            binding_id="response_profile_binding_" + binding_body,
            bitemporal_version_id=str(version["bitemporal_version_id"]),
            base_stage3a_state_version_id=base_id,
            response_profile_id=str(profile["response_profile_id"]),
            valid_date=date.fromisoformat(str(version["valid_date"])),
            knowledge_time_start_local_date=date.fromisoformat(
                str(version["knowledge_time_start_local_date"])
            ),
            version_number=int(version["version_number"]),
            response_evidence_ids=list(profile["response_evidence_ids"]),
            response_component_ids=list(profile["response_component_ids"]),
            metric_foundation_method_version=STAGE4A1_METHOD_VERSION,
        )
        row = model.model_dump(mode="json")
        bindings.append(row)
        by_base[base_id].append(row)
    invariance_rows: list[dict[str, Any]] = []
    for base_id, rows in sorted(by_base.items()):
        profile_ids = sorted({str(row["response_profile_id"]) for row in rows})
        component_sets = {tuple(row["response_component_ids"]) for row in rows}
        invariance_rows.append(
            {
                "base_stage3a_state_version_id": base_id,
                "bitemporal_version_count": len(rows),
                "unique_response_profile_count": len(profile_ids),
                "profile_ids": profile_ids,
                "profile_diff_count": max(len(component_sets) - 1, 0),
                "status": "PASS" if len(profile_ids) == 1 and len(component_sets) == 1 else "FAIL",
            }
        )
    return bindings, invariance_rows


def _summarize_channel(channel: str, components: list[dict[str, Any]]) -> ChannelDeviationSummary:
    channel_components = [item for item in components if item["channel_name"] == channel]
    robust_values = [
        float(item["robust_z"]) for item in channel_components if item.get("robust_z") is not None
    ]
    abs_values = [
        float(item["absolute_robust_z"])
        for item in channel_components
        if item.get("absolute_robust_z") is not None
    ]
    episode_ids = sorted({str(item["episode_id"]) for item in channel_components})
    return ChannelDeviationSummary(
        channel_name=channel,
        summary_status="DESCRIPTIVE_ONLY_NOT_FINAL_RAI",
        unique_response_evidence_count=len(
            {str(item["response_evidence_id"]) for item in channel_components}
        ),
        unique_episode_count=len(episode_ids),
        robust_z_min=min(robust_values) if robust_values else None,
        robust_z_max=max(robust_values) if robust_values else None,
        robust_z_median=statistics.median(robust_values) if robust_values else None,
        robust_z_mean=statistics.fmean(robust_values) if robust_values else None,
        robust_z_q25=_quantile(robust_values, 0.25) if robust_values else None,
        robust_z_q75=_quantile(robust_values, 0.75) if robust_values else None,
        absolute_robust_z_max=max(abs_values) if abs_values else None,
        absolute_robust_z_median=statistics.median(abs_values) if abs_values else None,
        absolute_robust_z_mean=statistics.fmean(abs_values) if abs_values else None,
        baseline_available_count=sum(
            1 for item in channel_components if item["component_status"] == "AVAILABLE"
        ),
        baseline_unavailable_count=sum(
            1 for item in channel_components if item["component_status"] != "AVAILABLE"
        ),
        descriptive_status="MECHANICAL_RESPONSE_ONLY_NO_GEOLOGICAL_INTERPRETATION",
    )


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _build_multicell_audit(
    response_links: list[dict[str, Any]],
    components_by_response_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    links_by_response: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for link in response_links:
        links_by_response[str(link["response_evidence_id"])].append(link)
    rows: list[dict[str, Any]] = []
    for response_id, links in sorted(links_by_response.items()):
        rows.append(
            {
                "response_evidence_id": response_id,
                "linked_cell_count": len({str(link["cell_id"]) for link in links}),
                "linked_state_version_count": len(
                    {str(link["state_version_id"]) for link in links}
                ),
                "link_count": len(links),
                "component_id": components_by_response_id.get(response_id, {}).get("component_id"),
                "component_count": 1 if response_id in components_by_response_id else 0,
                "status": "PASS" if response_id in components_by_response_id else "FAIL",
            }
        )
    return rows
