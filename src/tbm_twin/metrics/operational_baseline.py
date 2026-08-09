"""Causal operational baseline construction for Stage 4A1."""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from tbm_twin.metrics.io import stable_id
from tbm_twin.metrics.models import STAGE4A1_METHOD_VERSION, CausalOperationalBaseline


def parse_date(value: str) -> date:
    """Parse an ISO date or datetime prefix as a local target date."""

    return date.fromisoformat(value[:10])


def finite_float(value: Any) -> float | None:
    """Return finite float or None."""

    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def median_from_response(response: dict[str, Any]) -> float | None:
    """Extract the response median from Stage 2E statistics."""

    stats = response.get("statistics")
    if not isinstance(stats, dict):
        return None
    return finite_float(stats.get("median"))


def sample_count_from_response(response: dict[str, Any]) -> int:
    """Extract positive sample count from Stage 2E statistics."""

    stats = response.get("statistics")
    if not isinstance(stats, dict):
        return 0
    try:
        return int(stats.get("sample_count") or 0)
    except (TypeError, ValueError):
        return 0


def assess_mechanical_eligibility(
    responses: list[dict[str, Any]],
    channels: set[str],
    invalid_quality_flags: set[str],
    invalid_reason_codes: set[str],
) -> tuple[dict[str, bool], list[dict[str, Any]], list[dict[str, Any]]]:
    """Audit whether ResponseEvidence can participate in mechanical baselines."""

    eligibility: dict[str, bool] = {}
    audit_rows: list[dict[str, Any]] = []
    reason_counter: Counter[str] = Counter()
    for response in responses:
        response_id = str(response["evidence_id"])
        reason_codes: list[str] = []
        channel = str(response.get("channel_name") or "")
        stats = response.get("statistics")
        median = median_from_response(response)
        sample_count = sample_count_from_response(response)
        flags = [str(item) for item in response.get("quality_flags", [])]
        quality_components = response.get("quality_components") or {}
        component_reasons: list[str] = []
        if isinstance(quality_components, dict):
            for key, value in quality_components.items():
                if key.endswith("_reason_codes") and isinstance(value, list):
                    component_reasons.extend(str(item) for item in value)
        if channel not in channels:
            reason_codes.append("NON_FORMAL_CHANNEL")
        if not isinstance(stats, dict):
            reason_codes.append("MISSING_STATISTICS")
        if median is None:
            reason_codes.append("NON_FINITE_MEDIAN")
        if sample_count <= 0:
            reason_codes.append("NO_CORE_SAMPLES")
        if not response.get("core_observation_refs"):
            reason_codes.append("NO_CORE_OBSERVATION_REFS")
        invalid_flags = sorted(set(flags) & invalid_quality_flags)
        if invalid_flags:
            reason_codes.append("CONFIGURED_MECHANICAL_INVALID_QUALITY_FLAG")
        invalid_reasons = sorted(set(component_reasons) & invalid_reason_codes)
        if invalid_reasons:
            reason_codes.append("CONFIGURED_MECHANICAL_INVALID_REASON_CODE")
        eligible = not reason_codes
        eligibility[response_id] = eligible
        for reason in reason_codes or ["MECHANICALLY_ELIGIBLE"]:
            reason_counter[reason] += 1
        audit_rows.append(
            {
                "response_evidence_id": response_id,
                "target_date": response.get("target_date"),
                "channel_name": channel,
                "median": median,
                "sample_count": sample_count,
                "spatial_scope_usable": bool(response.get("spatial_scope_usable")),
                "quality_grade": response.get("quality_grade"),
                "quality_flags": flags,
                "mechanically_eligible": eligible,
                "reason_codes": reason_codes,
                "configured_invalid_quality_flags": invalid_flags,
                "configured_invalid_reason_codes": invalid_reasons,
            }
        )
    inventory = [
        {"reason_code": reason, "response_evidence_count": count}
        for reason, count in sorted(reason_counter.items())
    ]
    return eligibility, audit_rows, inventory


def build_causal_baselines(
    valid_dates: list[date],
    responses: list[dict[str, Any]],
    eligibility: dict[str, bool],
    channels: list[str],
    min_sample_count: int,
    mad_scale_factor: float,
    iqr_scale_divisor: float,
    alignment_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build one causal baseline per valid date and formal channel."""

    eligible_by_channel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for response in responses:
        response_id = str(response["evidence_id"])
        if not eligibility.get(response_id):
            continue
        item = dict(response)
        item["_target_date"] = parse_date(str(response["target_date"]))
        item["_median"] = median_from_response(response)
        eligible_by_channel[str(response["channel_name"])].append(item)

    baseline_rows: list[dict[str, Any]] = []
    sample_audit_rows: list[dict[str, Any]] = []
    future_leakage_rows: list[dict[str, Any]] = []
    for valid_date in sorted(valid_dates):
        for channel in channels:
            samples = [
                row
                for row in eligible_by_channel.get(channel, [])
                if row["_target_date"] < valid_date
            ]
            sample_ids = sorted({str(row["evidence_id"]) for row in samples})
            values = [float(row["_median"]) for row in samples if row["_median"] is not None]
            dates = sorted({row["_target_date"] for row in samples})
            episodes = sorted({str(row.get("episode_id")) for row in samples})
            q1 = _quantile(values, 0.25) if values else None
            q3 = _quantile(values, 0.75) if values else None
            median_value = statistics.median(values) if values else None
            mad = (
                statistics.median([abs(value - median_value) for value in values])
                if median_value is not None
                else None
            )
            iqr = q3 - q1 if q1 is not None and q3 is not None else None
            mad_scaled = mad * mad_scale_factor if mad is not None else None
            iqr_scaled = iqr / iqr_scale_divisor if iqr is not None else None
            robust_scale: float | None = None
            robust_scale_basis: str | None = None
            reason_codes: list[str] = []
            if len(values) < min_sample_count:
                status = "INSUFFICIENT_CAUSAL_HISTORY"
                reason_codes.append("BASELINE_SAMPLE_COUNT_BELOW_THRESHOLD")
            elif mad_scaled is not None and mad_scaled > 0:
                status = "AVAILABLE"
                robust_scale = mad_scaled
                robust_scale_basis = "MAD"
            elif iqr_scaled is not None and iqr_scaled > 0:
                status = "AVAILABLE"
                robust_scale = iqr_scaled
                robust_scale_basis = "IQR_FALLBACK"
                reason_codes.append("MAD_ZERO_IQR_FALLBACK")
            else:
                status = "ZERO_ROBUST_SCALE"
                reason_codes.append("ZERO_ROBUST_SCALE")
            baseline_id = "causal_baseline_" + stable_id(
                valid_date.isoformat(), channel, STAGE4A1_METHOD_VERSION
            )
            model = CausalOperationalBaseline(
                baseline_id=baseline_id,
                valid_date=valid_date,
                channel_name=channel,
                alignment_id=alignment_id,
                sample_count=len(values),
                unique_episode_count=len(episodes),
                source_date_count=len(dates),
                earliest_source_date=dates[0] if dates else None,
                latest_source_date=dates[-1] if dates else None,
                median=median_value,
                mad=mad,
                iqr=iqr,
                q1=q1,
                q3=q3,
                mad_scaled=mad_scaled,
                iqr_scaled=iqr_scaled,
                robust_scale=robust_scale,
                robust_scale_basis=robust_scale_basis,
                baseline_status=status,
                reason_codes=reason_codes,
                source_response_evidence_ids=sample_ids,
                baseline_method_version=STAGE4A1_METHOD_VERSION,
            )
            baseline_rows.append(model.model_dump(mode="json"))
            sample_audit_rows.append(
                {
                    "baseline_id": baseline_id,
                    "valid_date": valid_date.isoformat(),
                    "channel_name": channel,
                    "sample_count": len(values),
                    "unique_response_evidence_count": len(sample_ids),
                    "unique_episode_count": len(episodes),
                    "source_date_count": len(dates),
                    "earliest_source_date": dates[0].isoformat() if dates else None,
                    "latest_source_date": dates[-1].isoformat() if dates else None,
                    "baseline_status": status,
                    "reason_codes": reason_codes,
                }
            )
            for sample in samples:
                if sample["_target_date"] >= valid_date:
                    future_leakage_rows.append(
                        {
                            "baseline_id": baseline_id,
                            "valid_date": valid_date.isoformat(),
                            "sample_response_evidence_id": sample["evidence_id"],
                            "sample_target_date": sample["_target_date"].isoformat(),
                            "status": "FUTURE_LEAKAGE",
                        }
                    )
    return baseline_rows, sample_audit_rows, future_leakage_rows


def _quantile(values: list[float], fraction: float) -> float:
    """Linear interpolation quantile for deterministic robust summaries."""

    if not values:
        msg = "values must not be empty"
        raise ValueError(msg)
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
