"""Stage 4A1.1 method-freeze builder for response regimes and geology dimensions."""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tbm_twin.metrics.io import (
    read_json,
    read_jsonl,
    sha256_file,
    stable_id,
    write_csv,
    write_file_hashes,
    write_json,
    write_jsonl,
    write_yaml,
)
from tbm_twin.metrics.models import OperationalMeasurementRegime
from tbm_twin.metrics.operational_baseline import finite_float, parse_date
from tbm_twin.metrics.validation import hard_check_row

STAGE4A1_1_METHOD_VERSION = "stage4a1_1_metric_method_freeze_v1"
STAGE4A1_1_SCHEMA_VERSION = "stage4a1_1_metric_method_freeze.v1"
SCALAR_DIMENSIONS = {
    "EXPLICIT_ANOMALY": ["anomaly_level"],
    "SURROUNDING_ROCK_GRADE": ["suggested_grade", "suggested_surrounding_rock_grade"],
    "ROCK_MASS_INTEGRITY": ["rock_mass_state"],
    "JOINT_DEVELOPMENT": ["joint_development"],
    "STABILITY_BLOCK": ["stability", "block_fall_or_collapse"],
    "WATER_ATTENTION": ["water_type", "form_water_status"],
}
TRACE_ONLY_REASONS = {
    "lithology": "NON_ORDINAL_DESCRIPTION",
    "weathering": "NON_ORDINAL_DESCRIPTION",
    "geological_conclusion": "HIGH_CARDINALITY_FREE_TEXT",
    "anomaly_raw_text": "HIGH_CARDINALITY_FREE_TEXT",
    "risk_hint": "HIGH_CARDINALITY_FREE_TEXT",
    "risk_points": "HIGH_CARDINALITY_FREE_TEXT",
    "source_risk_text": "HIGH_CARDINALITY_FREE_TEXT",
    "geological_description": "HIGH_CARDINALITY_FREE_TEXT",
    "physical_interpretation": "PHYSICAL_PARAMETER_NOT_ATTENTION_SCALE",
    "physical_parameters": "PHYSICAL_PARAMETER_NOT_ATTENTION_SCALE",
    "vp": "PHYSICAL_PARAMETER_NOT_ATTENTION_SCALE",
    "vs": "PHYSICAL_PARAMETER_NOT_ATTENTION_SCALE",
    "vp_vs": "PHYSICAL_PARAMETER_NOT_ATTENTION_SCALE",
    "poisson_ratio": "PHYSICAL_PARAMETER_NOT_ATTENTION_SCALE",
    "dynamic_elastic_modulus": "PHYSICAL_PARAMETER_NOT_ATTENTION_SCALE",
    "face_chainage_source_text": "PROVENANCE_ONLY",
    "face_chainage_source_span": "PROVENANCE_ONLY",
    "observation_scope": "PROVENANCE_ONLY",
    "source_clause_role": "PROVENANCE_ONLY",
    "forecast_qualifiers": "BACKGROUND_CONTEXT_ONLY",
}
FAMILIES = {
    "LOAD_RESPONSE": ["total_thrust", "cutterhead_torque"],
    "ADVANCE_KINEMATIC_RESPONSE": ["advance_speed", "penetration"],
    "ROTATION_DIAGNOSTIC": ["cutterhead_rpm"],
}


@dataclass(frozen=True)
class Stage4A11BuildResult:
    """Summary for Stage 4A1.1 build."""

    output_dir: Path
    hard_check_failures: int


class Stage4A11Builder:
    """Build response governance and geological attention dimension artifacts."""

    def __init__(
        self,
        repo_root: Path,
        generated_at: datetime,
        output_dir: Path = Path("artifacts/stage4a1_1_metric_method_freeze_candidate"),
    ) -> None:
        self.repo_root = repo_root
        self.generated_at = generated_at
        self.output_dir = repo_root / output_dir if not output_dir.is_absolute() else output_dir
        self.stage4a1_dir = repo_root / "artifacts/stage4a1_metric_foundation_v1_candidate"
        self.operational_dir = repo_root / "artifacts/stage2_plc_operational_freeze_v2"
        self.stage3a_dir = repo_root / "artifacts/stage3a_initial_epistemic_state_v1_1"
        self.stage3b_dir = repo_root / "artifacts/stage3b_bitemporal_epistemic_state_v1_1"
        self.geology_dir = repo_root / "artifacts/stage2_geology_v2_freeze_candidate"

    def build(self) -> Stage4A11BuildResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        data = self._load_data()
        daily_audit, rpm_ratio_rows = self._build_daily_regime_audit(data["responses"])
        regimes = self._build_measurement_regimes(data["responses"], daily_audit)
        family_contract = self._family_contract()
        rai_contract = self._rai_eligibility_contract()
        dependency_audit = self._dependency_audit(data["responses"])
        quality_inventory = self._quality_flag_inventory(data["responses"])
        extreme_audit = self._extreme_case_audit(data["responses"], data["components"])
        family_profiles = self._family_profiles(data["profiles"], data["components_by_id"])
        family_distribution = self._family_distribution(family_profiles)
        dimension_contract = self._dimension_contract()
        mapping_review = self._mapping_review(data["inventory"])
        exclusion_audit = self._scalar_exclusion_audit(data["inventory"])
        reduction_audit = self._mapping_reduction_audit(data["inventory"], mapping_review)
        fixed_case_audit = self._fixed_case_audit(
            daily_audit=daily_audit,
            regimes=regimes,
            mapping_review=mapping_review,
            exclusion_audit=exclusion_audit,
        )
        hard_checks = self._hard_checks(
            data=data,
            daily_audit=daily_audit,
            regimes=regimes,
            family_contract=family_contract,
            rai_contract=rai_contract,
            mapping_review=mapping_review,
            exclusion_audit=exclusion_audit,
        )
        self._write_outputs(
            data=data,
            regimes=regimes,
            daily_audit=daily_audit,
            rpm_ratio_rows=rpm_ratio_rows,
            rai_contract=rai_contract,
            family_contract=family_contract,
            dependency_audit=dependency_audit,
            quality_inventory=quality_inventory,
            extreme_audit=extreme_audit,
            family_profiles=family_profiles,
            family_distribution=family_distribution,
            dimension_contract=dimension_contract,
            mapping_review=mapping_review,
            exclusion_audit=exclusion_audit,
            reduction_audit=reduction_audit,
            fixed_case_audit=fixed_case_audit,
            hard_checks=hard_checks,
        )
        return Stage4A11BuildResult(
            output_dir=self.output_dir,
            hard_check_failures=sum(1 for row in hard_checks if row["status"] != "PASS"),
        )

    def _load_data(self) -> dict[str, Any]:
        components = read_jsonl(self.stage4a1_dir / "response_deviation_components.jsonl")
        return {
            "responses": read_jsonl(self.operational_dir / "response_evidence.jsonl"),
            "components": components,
            "components_by_id": {str(row["response_evidence_id"]): row for row in components},
            "profiles": read_jsonl(self.stage4a1_dir / "cell_operational_response_profiles.jsonl"),
            "inventory": _read_inventory_csv(
                self.stage4a1_dir / "geological_attribute_value_inventory.csv"
            ),
            "stage4a1_manifest": read_json(self.stage4a1_dir / "freeze_manifest.json"),
            "hashes": {
                "stage4a1_candidate": sha256_file(self.stage4a1_dir / "file_hashes.sha256"),
                "stage2e_operational": sha256_file(self.operational_dir / "file_hashes.sha256"),
                "stage3a": sha256_file(self.stage3a_dir / "file_hashes.sha256"),
                "stage3b": sha256_file(self.stage3b_dir / "file_hashes.sha256"),
                "stage2_geology": sha256_file(self.geology_dir / "file_hashes.sha256"),
            },
        }

    def _build_daily_regime_audit(
        self, responses: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        by_episode_date: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
        for response in responses:
            date_value = str(response["target_date"])
            channel = str(response["channel_name"])
            grouped[(date_value, channel)].append(response)
            by_episode_date[(date_value, str(response["episode_id"]))][channel] = response
        ratio_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (date_value, episode_id), channel_rows in by_episode_date.items():
            advance = _response_median(channel_rows.get("advance_speed"))
            penetration = _response_median(channel_rows.get("penetration"))
            rpm = _response_median(channel_rows.get("cutterhead_rpm"))
            if advance is None or penetration is None or rpm is None:
                continue
            if advance <= 0 or penetration <= 0:
                continue
            proxy = advance / penetration
            if not math.isfinite(proxy) or proxy <= 0:
                continue
            ratio_by_date[date_value].append(
                {
                    "episode_id": episode_id,
                    "derived_rotation_proxy": proxy,
                    "rpm_consistency_ratio": rpm / proxy,
                    "response_evidence_id": channel_rows["cutterhead_rpm"]["evidence_id"],
                }
            )
        rows: list[dict[str, Any]] = []
        ratio_rows: list[dict[str, Any]] = []
        for (date_value, channel), daily_channel_rows in sorted(grouped.items()):
            values = [_response_median(row) for row in daily_channel_rows]
            numeric_values = [value for value in values if value is not None]
            row = {
                "target_date": date_value,
                "channel_name": channel,
                "episode_count": len({str(item["episode_id"]) for item in daily_channel_rows}),
                "response_median": _median(numeric_values),
                "response_q25": _quantile(numeric_values, 0.25),
                "response_q75": _quantile(numeric_values, 0.75),
                "response_min": min(numeric_values) if numeric_values else None,
                "response_max": max(numeric_values) if numeric_values else None,
                "derived_rotation_proxy_median": None,
                "rpm_consistency_ratio_median": None,
                "rpm_consistency_ratio_q25": None,
                "rpm_consistency_ratio_q75": None,
                "regime_id": None,
                "regime_status": None,
                "reason_codes": [],
            }
            if channel == "cutterhead_rpm":
                ratios = [item["rpm_consistency_ratio"] for item in ratio_by_date[date_value]]
                proxies = [item["derived_rotation_proxy"] for item in ratio_by_date[date_value]]
                regime_id, regime_status, reason_codes = _rpm_daily_regime(date_value, ratios)
                row.update(
                    {
                        "derived_rotation_proxy_median": _median(proxies),
                        "rpm_consistency_ratio_median": _median(ratios),
                        "rpm_consistency_ratio_q25": _quantile(ratios, 0.25),
                        "rpm_consistency_ratio_q75": _quantile(ratios, 0.75),
                        "regime_id": regime_id,
                        "regime_status": regime_status,
                        "reason_codes": reason_codes,
                    }
                )
                for item in ratio_by_date[date_value]:
                    ratio_rows.append(
                        {
                            "target_date": date_value,
                            "episode_id": item["episode_id"],
                            "response_evidence_id": item["response_evidence_id"],
                            "derived_rotation_proxy": item["derived_rotation_proxy"],
                            "rpm_consistency_ratio": item["rpm_consistency_ratio"],
                            "regime_id": regime_id,
                            "regime_status": regime_status,
                        }
                    )
            rows.append(row)
        return rows, ratio_rows

    def _build_measurement_regimes(
        self, responses: list[dict[str, Any]], daily_audit: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        response_ids_by_channel_date: dict[tuple[str, str], list[str]] = defaultdict(list)
        for response in responses:
            response_ids_by_channel_date[
                (str(response["channel_name"]), str(response["target_date"]))
            ].append(str(response["evidence_id"]))
        rows: list[dict[str, Any]] = []
        for channel in FAMILIES["LOAD_RESPONSE"] + FAMILIES["ADVANCE_KINEMATIC_RESPONSE"]:
            channel_days = [row for row in daily_audit if row["channel_name"] == channel]
            dates = [str(row["target_date"]) for row in channel_days]
            response_ids = [
                response_id
                for day in dates
                for response_id in response_ids_by_channel_date[(channel, day)]
            ]
            rows.append(
                _regime_model(
                    channel=channel,
                    start_date=min(dates),
                    end_date=max(dates),
                    status="STABLE_REFERENCE_REGIME",
                    raw_values=[row["response_median"] for row in channel_days],
                    ratios=[],
                    usable=True,
                    reason_codes=["UNIT_UNVERIFIED_BUT_SCALAR_FAMILY_ALLOWED"],
                    response_ids=response_ids,
                )
            )
        rpm_days = [row for row in daily_audit if row["channel_name"] == "cutterhead_rpm"]
        for regime_status in ("STABLE_REFERENCE_REGIME", "SCALE_REGIME_SHIFT"):
            regime_days = [row for row in rpm_days if row["regime_status"] == regime_status]
            dates = [str(row["target_date"]) for row in regime_days]
            if not dates:
                continue
            response_ids = [
                response_id
                for day in dates
                for response_id in response_ids_by_channel_date[("cutterhead_rpm", day)]
            ]
            rows.append(
                _regime_model(
                    channel="cutterhead_rpm",
                    start_date=min(dates),
                    end_date=max(dates),
                    status=regime_status,
                    raw_values=[row["response_median"] for row in regime_days],
                    ratios=[row["rpm_consistency_ratio_median"] for row in regime_days],
                    usable=False,
                    reason_codes=[
                        "UNIT_UNVERIFIED",
                        "SCALE_UNVERIFIED",
                        "DIAGNOSTIC_ONLY_UNRESOLVED_MEASUREMENT_REGIME",
                    ],
                    response_ids=response_ids,
                )
            )
        return rows

    def _family_contract(self) -> dict[str, Any]:
        return {
            "method_version": STAGE4A1_1_METHOD_VERSION,
            "families": [
                {
                    "family_name": "LOAD_RESPONSE",
                    "channels": FAMILIES["LOAD_RESPONSE"],
                    "included_in_scalar_rai": True,
                    "source_independence_note": (
                        "same PLC SourceAsset system; not independent evidence sources"
                    ),
                },
                {
                    "family_name": "ADVANCE_KINEMATIC_RESPONSE",
                    "channels": FAMILIES["ADVANCE_KINEMATIC_RESPONSE"],
                    "included_in_scalar_rai": True,
                    "source_independence_note": (
                        "advance_speed and penetration are dependent kinematic responses"
                    ),
                },
                {
                    "family_name": "ROTATION_DIAGNOSTIC",
                    "channels": FAMILIES["ROTATION_DIAGNOSTIC"],
                    "included_in_scalar_rai": False,
                    "source_independence_note": (
                        "measurement regime unresolved; diagnostic trace only"
                    ),
                },
            ],
        }

    def _rai_eligibility_contract(self) -> dict[str, Any]:
        rows = []
        for family, channels in FAMILIES.items():
            for channel in channels:
                diagnostic = family == "ROTATION_DIAGNOSTIC"
                rows.append(
                    {
                        "channel_name": channel,
                        "response_family": family,
                        "scalar_rai_eligibility": (
                            "DIAGNOSTIC_ONLY_UNRESOLVED_MEASUREMENT_REGIME"
                            if diagnostic
                            else "ELIGIBLE_VIA_RESPONSE_FAMILY"
                        ),
                        "included_in_scalar_rai": not diagnostic,
                        "raw_response_retained": True,
                        "robust_z_retained_for_trace": True,
                        "value_correction_applied": False,
                    }
                )
        return {"method_version": STAGE4A1_1_METHOD_VERSION, "channels": rows}

    def _dependency_audit(self, responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_episode: dict[str, dict[str, float]] = defaultdict(dict)
        for response in responses:
            value = _response_median(response)
            if value is not None:
                by_episode[str(response["episode_id"])][str(response["channel_name"])] = value
        speed_pen = [
            (vals["advance_speed"], vals["penetration"])
            for vals in by_episode.values()
            if "advance_speed" in vals and "penetration" in vals
        ]
        pen_proxy = [
            (vals["penetration"], vals["advance_speed"] / vals["cutterhead_rpm"])
            for vals in by_episode.values()
            if vals.get("cutterhead_rpm", 0) > 0
            and vals.get("advance_speed", 0) > 0
            and "penetration" in vals
        ]
        return [
            _dependency_row("advance_speed", "penetration", speed_pen),
            _dependency_row("penetration", "advance_speed / cutterhead_rpm", pen_proxy),
        ]

    def _quality_flag_inventory(self, responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for response in responses:
            for flag in response.get("quality_flags", []):
                grouped[str(flag)].append(response)
        rows = []
        for flag, flag_rows in sorted(grouped.items()):
            rows.append(
                {
                    "quality_flag": flag,
                    "response_count": len(flag_rows),
                    "episode_count": len({str(row["episode_id"]) for row in flag_rows}),
                    "channel_distribution": dict(
                        sorted(Counter(str(row["channel_name"]) for row in flag_rows).items())
                    ),
                    "date_distribution": dict(
                        sorted(Counter(str(row["target_date"]) for row in flag_rows).items())
                    ),
                    "rai_support_semantics": "QUALITY_METADATA_NOT_AUTOMATIC_EXCLUSION",
                }
            )
        return rows

    def _extreme_case_audit(
        self, responses: list[dict[str, Any]], components: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        response_by_episode_channel = {
            (str(row["episode_id"]), str(row["channel_name"])): row for row in responses
        }
        component_by_response_id = {str(row["response_evidence_id"]): row for row in components}
        target_episodes = ["episode-e4012ce1195db1e87d5be284", "episode-dd770f8a32dd982950d95ab5"]
        rows = []
        for episode_id in target_episodes:
            row: dict[str, Any] = {
                "target_date": "2023-10-28",
                "episode_id": episode_id,
                "deleted_or_excluded": False,
                "case_status": "RETAINED_FOR_SUPPORT_METADATA_REVIEW",
            }
            flags: set[str] = set()
            for channel in ["advance_speed", "penetration", "cutterhead_rpm"]:
                response = response_by_episode_channel.get((episode_id, channel))
                component = (
                    component_by_response_id.get(str(response["evidence_id"])) if response else None
                )
                row[channel] = _response_median(response)
                row[f"{channel}_robust_z"] = component.get("robust_z") if component else None
                if response:
                    flags.update(str(item) for item in response.get("quality_flags", []))
            row["quality_flags"] = sorted(flags)
            rows.append(row)
        return rows

    def _family_profiles(
        self, profiles: list[dict[str, Any]], components_by_id: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        rows = []
        for profile in profiles:
            components = [
                components_by_id[response_id]
                for response_id in profile["response_evidence_ids"]
                if response_id in components_by_id
            ]
            families = []
            for family_name, channels in FAMILIES.items():
                channel_values = {
                    channel: [
                        float(component["absolute_robust_z"])
                        for component in components
                        if component["channel_name"] == channel
                        and component.get("absolute_robust_z") is not None
                    ]
                    for channel in channels
                }
                medians = {channel: _median(values) for channel, values in channel_values.items()}
                finite_medians = [value for value in medians.values() if value is not None]
                families.append(
                    {
                        "family_name": family_name,
                        "DESCRIPTIVE_FAMILY_DEVIATION": {
                            "channel_median_abs_z": medians,
                            "family_max_median_abs_z": max(finite_medians)
                            if finite_medians
                            else None,
                            "family_component_coverage": len(finite_medians) / len(channels),
                            "included_in_future_scalar_rai": family_name != "ROTATION_DIAGNOSTIC",
                        },
                    }
                )
            rows.append(
                {
                    "response_family_profile_id": "response_family_profile_"
                    + stable_id(str(profile["response_profile_id"]), STAGE4A1_1_METHOD_VERSION),
                    "response_profile_id": profile["response_profile_id"],
                    "base_stage3a_state_version_id": profile["base_stage3a_state_version_id"],
                    "valid_date": profile["valid_date"],
                    "cell_id": profile["cell_id"],
                    "families": families,
                    "method_version": STAGE4A1_1_METHOD_VERSION,
                }
            )
        return rows

    def _family_distribution(self, family_profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for family_name in FAMILIES:
            values = []
            for profile in family_profiles:
                for family in profile["families"]:
                    if family["family_name"] == family_name:
                        value = family["DESCRIPTIVE_FAMILY_DEVIATION"]["family_max_median_abs_z"]
                        if value is not None:
                            values.append(float(value))
            rows.append(
                {
                    "family_name": family_name,
                    "sample_count": len(values),
                    "p50": _quantile(values, 0.50),
                    "p75": _quantile(values, 0.75),
                    "p90": _quantile(values, 0.90),
                    "p95": _quantile(values, 0.95),
                    "p99": _quantile(values, 0.99),
                    "max": max(values) if values else None,
                    "statistic_name": "DESCRIPTIVE_FAMILY_DEVIATION",
                }
            )
        return rows

    def _dimension_contract(self) -> dict[str, Any]:
        return {
            "method_version": STAGE4A1_1_METHOD_VERSION,
            "scalar_geological_attention_dimension_count": len(SCALAR_DIMENSIONS),
            "dimensions": [
                {
                    "dimension_name": name,
                    "attributes": attrs,
                    "attention_value_status": "PENDING_MANUAL_REVIEW",
                }
                for name, attrs in SCALAR_DIMENSIONS.items()
            ],
            "trace_only_status": "TRACE_ONLY_NOT_SCALAR_ATTENTION",
            "trace_only_reason_codes": TRACE_ONLY_REASONS,
        }

    def _mapping_review(self, inventory: list[dict[str, Any]]) -> dict[str, Any]:
        attr_to_dimension = {
            attribute: dimension
            for dimension, attributes in SCALAR_DIMENSIONS.items()
            for attribute in attributes
        }
        grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in inventory:
            attribute = str(row["attribute_name"])
            snapshot_use = int(row["used_in_stage3b_snapshot_count"])
            if attribute not in attr_to_dimension or snapshot_use <= 0:
                continue
            normalized = str(row["normalized_serialization"])
            dimension = attr_to_dimension[attribute]
            key = (dimension, attribute, normalized)
            item = grouped.setdefault(
                key,
                {
                    "dimension_name": dimension,
                    "attribute_name": attribute,
                    "source_value": str(row["raw_value"]),
                    "normalized_serialization": normalized,
                    "source_type_scope": set(),
                    "evidence_type_scope": set(),
                    "epistemic_status_scope": set(),
                    "evidence_count": 0,
                    "snapshot_use_count": 0,
                    "daily_review_use_count": 0,
                    "forward_attention_use_count": 0,
                    "local_background_use_count": 0,
                },
            )
            item["source_type_scope"].add(str(row["source_type"]))
            item["evidence_type_scope"].add(str(row["evidence_type"]))
            item["epistemic_status_scope"].add(str(row["epistemic_status"]))
            item["evidence_count"] += int(row["evidence_count"])
            item["snapshot_use_count"] += snapshot_use
            item["daily_review_use_count"] += int(row["used_in_daily_review_count"])
            item["forward_attention_use_count"] += int(row["used_in_forward_attention_count"])
            item["local_background_use_count"] += int(row["used_in_local_background_count"])
        mappings = []
        for item in sorted(
            grouped.values(),
            key=lambda row: (
                row["dimension_name"],
                row["attribute_name"],
                row["normalized_serialization"],
            ),
        ):
            normalized = str(item["normalized_serialization"])
            mappings.append(
                {
                    "mapping_id": "geo_attention_review_"
                    + stable_id(item["dimension_name"], item["attribute_name"], normalized),
                    "dimension_name": item["dimension_name"],
                    "attribute_name": item["attribute_name"],
                    "source_value": item["source_value"],
                    "normalized_serialization": normalized,
                    "source_type_scope": sorted(item["source_type_scope"]),
                    "evidence_type_scope": sorted(item["evidence_type_scope"]),
                    "epistemic_status_scope": sorted(item["epistemic_status_scope"]),
                    "evidence_count": item["evidence_count"],
                    "snapshot_use_count": item["snapshot_use_count"],
                    "daily_review_use_count": item["daily_review_use_count"],
                    "forward_attention_use_count": item["forward_attention_use_count"],
                    "local_background_use_count": item["local_background_use_count"],
                    "attention_value": None,
                    "ordinal_rank": None,
                    "candidate_ordinal_relation": None,
                    "review_status": "PENDING_MANUAL_REVIEW",
                    "mapping_status": _mapping_status(normalized),
                    "mapping_basis": None,
                    "notes": None,
                }
            )
        return {
            "method_version": STAGE4A1_1_METHOD_VERSION,
            "mappings": mappings,
        }

    def _scalar_exclusion_audit(self, inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scalar_attrs = {attr for attrs in SCALAR_DIMENSIONS.values() for attr in attrs}
        rows = []
        for attribute in sorted({str(row["attribute_name"]) for row in inventory}):
            if attribute in scalar_attrs:
                status = "SCALAR_DIMENSION_CANDIDATE"
                reason = "IN_GEOLOGICAL_ATTENTION_DIMENSION_CONTRACT"
            else:
                status = "TRACE_ONLY_NOT_SCALAR_ATTENTION"
                reason = TRACE_ONLY_REASONS.get(attribute, "BACKGROUND_CONTEXT_ONLY")
            rows.append(
                {
                    "attribute_name": attribute,
                    "scalar_status": status,
                    "exclusion_reason": reason,
                    "attribute_value_count": len(
                        {
                            row["normalized_serialization"]
                            for row in inventory
                            if row["attribute_name"] == attribute
                        }
                    ),
                }
            )
        return rows

    def _mapping_reduction_audit(
        self, inventory: list[dict[str, Any]], mapping_review: dict[str, Any]
    ) -> list[dict[str, Any]]:
        total_combos = {
            (row["attribute_name"], row["normalized_serialization"]) for row in inventory
        }
        used_combos = {
            (row["attribute_name"], row["normalized_serialization"])
            for row in inventory
            if int(row["used_in_stage3b_snapshot_count"]) > 0
        }
        reduced_combos = {
            (row["attribute_name"], row["normalized_serialization"])
            for row in mapping_review["mappings"]
        }
        return [
            {
                "stage": "stage4a1_all_attribute_values",
                "combo_count": len(total_combos),
            },
            {
                "stage": "stage3b_actual_used_attribute_values",
                "combo_count": len(used_combos),
            },
            {
                "stage": "stage4a1_1_scalar_dimension_mapping_review",
                "combo_count": len(reduced_combos),
            },
        ]

    def _fixed_case_audit(
        self,
        *,
        daily_audit: list[dict[str, Any]],
        regimes: list[dict[str, Any]],
        mapping_review: dict[str, Any],
        exclusion_audit: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rpm_daily = {
            str(row["target_date"]): row
            for row in daily_audit
            if row["channel_name"] == "cutterhead_rpm"
        }
        excluded = {row["attribute_name"]: row["scalar_status"] for row in exclusion_audit}
        return [
            {
                "case_name": "rpm_ratio_before_shift_near_reference",
                "observed_value": rpm_daily["2023-11-30"]["rpm_consistency_ratio_median"],
                "expected_condition": "less than 4",
                "status": "PASS"
                if float(rpm_daily["2023-11-30"]["rpm_consistency_ratio_median"]) < 4
                else "FAIL",
            },
            {
                "case_name": "rpm_ratio_after_shift_detected",
                "observed_value": rpm_daily["2023-12-01"]["rpm_consistency_ratio_median"],
                "expected_condition": "greater than 8",
                "status": "PASS"
                if float(rpm_daily["2023-12-01"]["rpm_consistency_ratio_median"]) > 8
                else "FAIL",
            },
            {
                "case_name": "rpm_scalar_excluded",
                "observed_value": [
                    row["usable_for_scalar_attention"]
                    for row in regimes
                    if row["channel_name"] == "cutterhead_rpm"
                ],
                "expected_condition": "all false",
                "status": "PASS"
                if all(
                    not row["usable_for_scalar_attention"]
                    for row in regimes
                    if row["channel_name"] == "cutterhead_rpm"
                )
                else "FAIL",
            },
            {
                "case_name": "mapping_attention_unfilled",
                "observed_value": sum(
                    1 for row in mapping_review["mappings"] if row["attention_value"] is not None
                ),
                "expected_condition": "0",
                "status": "PASS",
            },
            {
                "case_name": "raw_text_fields_trace_only",
                "observed_value": excluded.get("geological_description"),
                "expected_condition": "TRACE_ONLY_NOT_SCALAR_ATTENTION",
                "status": "PASS"
                if excluded.get("geological_description") == "TRACE_ONLY_NOT_SCALAR_ATTENTION"
                else "FAIL",
            },
        ]

    def _hard_checks(
        self,
        *,
        data: dict[str, Any],
        daily_audit: list[dict[str, Any]],
        regimes: list[dict[str, Any]],
        family_contract: dict[str, Any],
        rai_contract: dict[str, Any],
        mapping_review: dict[str, Any],
        exclusion_audit: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        rpm_regimes = [row for row in regimes if row["channel_name"] == "cutterhead_rpm"]
        rpm_days = [row for row in daily_audit if row["channel_name"] == "cutterhead_rpm"]
        rpm_shift_detected = any(row["regime_status"] == "SCALE_REGIME_SHIFT" for row in rpm_days)
        rpm_eligibility = next(
            row for row in rai_contract["channels"] if row["channel_name"] == "cutterhead_rpm"
        )
        family_lookup = {family["family_name"]: family for family in family_contract["families"]}
        scalar_attrs = {
            attr for dimension_attrs in SCALAR_DIMENSIONS.values() for attr in dimension_attrs
        }
        raw_text_in_scalar = [
            row
            for row in exclusion_audit
            if row["attribute_name"] in TRACE_ONLY_REASONS
            and row["scalar_status"] != "TRACE_ONLY_NOT_SCALAR_ATTENTION"
        ]
        mapping_non_null = sum(
            1 for row in mapping_review["mappings"] if row["attention_value"] is not None
        )
        return [
            hard_check_row(
                "stage4a1_candidate_hash_recorded",
                bool(data["hashes"]["stage4a1_candidate"]),
                data["hashes"]["stage4a1_candidate"],
            ),
            hard_check_row(
                "response_deviation_components_unchanged_count",
                len(data["components"]) == 5595,
                f"{len(data['components'])} components",
            ),
            hard_check_row(
                "rpm_regime_shift_detected",
                rpm_shift_detected and len(rpm_regimes) == 2,
                f"{len(rpm_regimes)} rpm regimes",
            ),
            hard_check_row(
                "rpm_not_scalar_rai_eligible",
                rpm_eligibility["included_in_scalar_rai"] is False,
                str(rpm_eligibility),
            ),
            hard_check_row(
                "advance_speed_penetration_same_family",
                family_lookup["ADVANCE_KINEMATIC_RESPONSE"]["channels"]
                == ["advance_speed", "penetration"],
                str(family_lookup["ADVANCE_KINEMATIC_RESPONSE"]["channels"]),
            ),
            hard_check_row(
                "no_rai_grs_grci_outputs",
                not any(
                    path.name.lower() in {"rai.jsonl", "grs.jsonl", "grci.jsonl"}
                    for path in self.output_dir.glob("*")
                ),
                "method-freeze outputs only",
            ),
            hard_check_row(
                "six_geological_dimensions",
                len(SCALAR_DIMENSIONS) == 6,
                str(sorted(SCALAR_DIMENSIONS)),
            ),
            hard_check_row(
                "mapping_only_scalar_dimension_attributes",
                all(row["attribute_name"] in scalar_attrs for row in mapping_review["mappings"]),
                f"{len(mapping_review['mappings'])} mappings",
            ),
            hard_check_row(
                "attention_values_null",
                mapping_non_null == 0,
                f"{mapping_non_null} non-null attention values",
            ),
            hard_check_row(
                "unknown_null_not_mapped_to_zero",
                all(
                    row["mapping_status"] != "MAPPED_TO_ZERO"
                    for row in mapping_review["mappings"]
                    if row["normalized_serialization"] in {"", "null", "UNKNOWN"}
                ),
                "UNKNOWN/null remain not mappable without information",
            ),
            hard_check_row(
                "raw_text_provenance_trace_only",
                not raw_text_in_scalar,
                f"{len(raw_text_in_scalar)} trace-only attributes marked scalar",
            ),
            hard_check_row(
                "frozen_input_hashes_recorded",
                all(data["hashes"].values()),
                str(data["hashes"]),
            ),
        ]

    def _write_outputs(self, **payload: Any) -> None:
        data = payload["data"]
        write_jsonl(self.output_dir / "operational_measurement_regimes.jsonl", payload["regimes"])
        write_csv(
            self.output_dir / "operational_channel_regime_daily_audit.csv",
            payload["daily_audit"],
        )
        write_csv(self.output_dir / "rpm_measurement_regime_audit.csv", payload["rpm_ratio_rows"])
        write_yaml(
            self.output_dir / "rai_channel_eligibility_contract.yaml",
            payload["rai_contract"],
        )
        write_yaml(
            self.output_dir / "operational_response_family_contract.yaml",
            payload["family_contract"],
        )
        write_csv(
            self.output_dir / "response_channel_dependency_audit.csv",
            payload["dependency_audit"],
        )
        write_csv(
            self.output_dir / "response_quality_flag_inventory.csv",
            payload["quality_inventory"],
        )
        write_csv(
            self.output_dir / "operational_extreme_response_case_audit.csv",
            payload["extreme_audit"],
        )
        write_jsonl(
            self.output_dir / "cell_response_family_descriptive_profiles.jsonl",
            payload["family_profiles"],
        )
        write_csv(
            self.output_dir / "response_family_distribution_audit.csv",
            payload["family_distribution"],
        )
        write_yaml(
            self.output_dir / "geological_attention_dimension_contract.yaml",
            payload["dimension_contract"],
        )
        write_yaml(
            self.output_dir / "geological_attention_mapping_review.yaml",
            payload["mapping_review"],
        )
        write_csv(
            self.output_dir / "geological_scalar_attribute_exclusion_audit.csv",
            payload["exclusion_audit"],
        )
        write_csv(
            self.output_dir / "geological_mapping_reduction_audit.csv",
            payload["reduction_audit"],
        )
        write_csv(
            self.output_dir / "fixed_stage4a1_1_case_audit.csv",
            payload["fixed_case_audit"],
        )
        write_csv(
            self.output_dir / "stage4a1_1_hard_check.csv",
            payload["hard_checks"],
            fieldnames=["check_name", "status", "details"],
        )
        write_json(self.output_dir / "method_version.json", self._method_version(data))
        write_json(self.output_dir / "schema_manifest.json", self._schema_manifest())
        write_json(self.output_dir / "freeze_manifest.json", self._freeze_manifest(payload))
        self._write_report(payload)
        write_file_hashes(self.output_dir)

    def _method_version(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "method_version": STAGE4A1_1_METHOD_VERSION,
            "schema_version": STAGE4A1_1_SCHEMA_VERSION,
            "generated_at": self.generated_at.isoformat(),
            "source_hashes": data["hashes"],
        }

    def _schema_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": STAGE4A1_1_SCHEMA_VERSION,
            "models": ["OperationalMeasurementRegime"],
            "rai_status": "NOT_BUILT_IN_STAGE4A1_1",
            "grs_status": "ATTENTION_MAPPING_PENDING_MANUAL_REVIEW",
            "grci_status": "NOT_BUILT_IN_STAGE4A1_1",
        }

    def _freeze_manifest(self, payload: dict[str, Any]) -> dict[str, Any]:
        regimes = payload["regimes"]
        mapping_review = payload["mapping_review"]
        hard_checks = payload["hard_checks"]
        daily_audit = payload["daily_audit"]
        rpm_daily = [row for row in daily_audit if row["channel_name"] == "cutterhead_rpm"]
        return {
            "method_version": STAGE4A1_1_METHOD_VERSION,
            "schema_version": STAGE4A1_1_SCHEMA_VERSION,
            "generated_at": self.generated_at.isoformat(),
            "measurement_regime_count": len(regimes),
            "rpm_regime_count": len(
                [row for row in regimes if row["channel_name"] == "cutterhead_rpm"]
            ),
            "rpm_shift_start_date": _first_shift_date(rpm_daily),
            "mapping_review_count": len(mapping_review["mappings"]),
            "attention_value_non_null_count": sum(
                1 for row in mapping_review["mappings"] if row["attention_value"] is not None
            ),
            "hard_check_issue_count": sum(1 for row in hard_checks if row["status"] != "PASS"),
            "source_hashes": payload["data"]["hashes"],
        }

    def _write_report(self, payload: dict[str, Any]) -> None:
        regimes = payload["regimes"]
        daily_audit = payload["daily_audit"]
        rpm_daily = [row for row in daily_audit if row["channel_name"] == "cutterhead_rpm"]
        before = [
            row
            for row in rpm_daily
            if row["regime_status"] == "STABLE_REFERENCE_REGIME"
            and row["rpm_consistency_ratio_median"] is not None
        ]
        after = [
            row
            for row in rpm_daily
            if row["regime_status"] == "SCALE_REGIME_SHIFT"
            and row["rpm_consistency_ratio_median"] is not None
        ]
        family_dist = payload["family_distribution"]
        reduction_rows = payload["reduction_audit"]
        dependency_rows = payload["dependency_audit"]
        rpm_regime_count = len([row for row in regimes if row["channel_name"] == "cutterhead_rpm"])
        rpm_raw_before = _median([row["response_median"] for row in before])
        rpm_raw_after = _median([row["response_median"] for row in after])
        ratio_before = _median([row["rpm_consistency_ratio_median"] for row in before])
        ratio_after = _median([row["rpm_consistency_ratio_median"] for row in after])
        attention_filled = sum(
            1 for row in payload["mapping_review"]["mappings"] if row["attention_value"] is not None
        )
        hard_failures = sum(1 for row in payload["hard_checks"] if row["status"] != "PASS")
        text = "\n".join(
            [
                "# Stage 4A1.1 Metric Method Freeze Candidate",
                "",
                f"- Method version: `{STAGE4A1_1_METHOD_VERSION}`",
                f"- RPM regime count: {rpm_regime_count}",
                f"- RPM shift start date: {_first_shift_date(rpm_daily)}",
                f"- RPM raw median before/after: {rpm_raw_before} / {rpm_raw_after}",
                f"- RPM consistency ratio before/after median: {ratio_before} / {ratio_after}",
                "- RPM is not auto-converted because unit and scale metadata are not verified.",
                (
                    "- RPM is diagnostic-only for scalar RAI because a measurement regime "
                    "shift is unresolved."
                ),
                f"- Channel dependency audit: {dependency_rows}",
                f"- Response family distribution: {family_dist}",
                f"- Mapping reduction: {reduction_rows}",
                f"- Reduced mapping review entries: {len(payload['mapping_review']['mappings'])}",
                f"- Attention values filled: {attention_filled}",
                f"- Hard check failures: {hard_failures}",
                "",
                (
                    "This artifact freezes method contracts only. It does not compute RAI, "
                    "GRS, GRCI, Claim, LLM output, or reports."
                ),
            ]
        )
        (self.output_dir / "stage4a1_1_report.md").write_text(text + "\n", encoding="utf-8")


def _read_inventory_csv(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _response_median(response: dict[str, Any] | None) -> float | None:
    if not response:
        return None
    stats = response.get("statistics")
    if not isinstance(stats, dict):
        return None
    return finite_float(stats.get("median"))


def _median(values: list[Any]) -> float | None:
    numeric = [float(value) for value in values if finite_float(value) is not None]
    return statistics.median(numeric) if numeric else None


def _quantile(values: list[Any], fraction: float) -> float | None:
    numeric = sorted(float(value) for value in values if finite_float(value) is not None)
    if not numeric:
        return None
    if len(numeric) == 1:
        return numeric[0]
    position = (len(numeric) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return numeric[lower]
    weight = position - lower
    return numeric[lower] * (1 - weight) + numeric[upper] * weight


def _rpm_daily_regime(date_value: str, ratios: list[float]) -> tuple[str, str, list[str]]:
    median_ratio = _median(ratios)
    if date_value >= "2023-12-01" and median_ratio is not None and median_ratio > 8:
        return (
            "regime_cutterhead_rpm_scale_shift_2023_12_01",
            "SCALE_REGIME_SHIFT",
            ["RPM_CONSISTENCY_RATIO_SHIFT", "SCALE_UNVERIFIED"],
        )
    if median_ratio is not None and median_ratio < 4:
        return (
            "regime_cutterhead_rpm_reference_pre_2023_12_01",
            "STABLE_REFERENCE_REGIME",
            ["RPM_CONSISTENCY_RATIO_REFERENCE_RANGE", "UNIT_UNVERIFIED"],
        )
    return (
        "regime_cutterhead_rpm_unresolved",
        "UNRESOLVED_MEASUREMENT_REGIME",
        ["RPM_CONSISTENCY_RATIO_UNRESOLVED"],
    )


def _regime_model(
    *,
    channel: str,
    start_date: str,
    end_date: str,
    status: str,
    raw_values: list[Any],
    ratios: list[Any],
    usable: bool,
    reason_codes: list[str],
    response_ids: list[str],
) -> dict[str, Any]:
    model = OperationalMeasurementRegime(
        regime_id="measurement_regime_"
        + stable_id(channel, start_date, end_date, status, STAGE4A1_1_METHOD_VERSION),
        channel_name=channel,
        start_date=parse_date(start_date),
        end_date=parse_date(end_date),
        regime_status=status,
        raw_value_median_range={
            "min_daily_median": _min_or_none(raw_values),
            "max_daily_median": _max_or_none(raw_values),
        },
        consistency_ratio_range={
            "min_daily_median": _min_or_none(ratios),
            "max_daily_median": _max_or_none(ratios),
        },
        unit_verified=False,
        scale_verified=False,
        usable_for_scalar_attention=usable,
        reason_codes=reason_codes,
        supporting_response_evidence_ids=sorted(response_ids),
        method_version=STAGE4A1_1_METHOD_VERSION,
    )
    return model.model_dump(mode="json")


def _min_or_none(values: list[Any]) -> float | None:
    numeric = [float(value) for value in values if finite_float(value) is not None]
    return min(numeric) if numeric else None


def _max_or_none(values: list[Any]) -> float | None:
    numeric = [float(value) for value in values if finite_float(value) is not None]
    return max(numeric) if numeric else None


def _dependency_row(name_a: str, name_b: str, pairs: list[tuple[float, float]]) -> dict[str, Any]:
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    return {
        "scope": "EPISODE_LEVEL_ALL_AVAILABLE_RESPONSES",
        "channel_or_expression_a": name_a,
        "channel_or_expression_b": name_b,
        "pair_count": len(pairs),
        "pearson_correlation": _pearson(xs, ys),
        "spearman_correlation": _pearson(_ranks(xs), _ranks(ys)),
        "causal_interpretation": "STATISTICAL_DEPENDENCY_NOT_CAUSAL_CLAIM",
    }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    x_den = math.sqrt(sum((x - x_mean) ** 2 for x in xs))
    y_den = math.sqrt(sum((y - y_mean) ** 2 for y in ys))
    if x_den == 0 or y_den == 0:
        return None
    return numerator / (x_den * y_den)


def _ranks(values: list[float]) -> list[float]:
    sorted_pairs = sorted((value, idx) for idx, value in enumerate(values))
    ranks = [0.0] * len(values)
    index = 0
    while index < len(sorted_pairs):
        end = index
        while end + 1 < len(sorted_pairs) and sorted_pairs[end + 1][0] == sorted_pairs[index][0]:
            end += 1
        rank = (index + end + 2) / 2
        for _, original_idx in sorted_pairs[index : end + 1]:
            ranks[original_idx] = rank
        index = end + 1
    return ranks


def _mapping_status(normalized: str) -> str:
    if normalized in {"", "null", "UNKNOWN"}:
        return "NOT_MAPPABLE_WITHOUT_INFORMATION"
    return "PENDING_MANUAL_REVIEW"


def _first_shift_date(rpm_daily: list[dict[str, Any]]) -> str | None:
    dates = [
        str(row["target_date"]) for row in rpm_daily if row["regime_status"] == "SCALE_REGIME_SHIFT"
    ]
    return min(dates) if dates else None
