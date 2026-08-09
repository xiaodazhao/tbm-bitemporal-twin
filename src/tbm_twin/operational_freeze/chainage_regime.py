"""Cross-day PLC chainage-regime governance without rewriting source values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import pandas as pd


class ChainageRegimeStatus(StrEnum):
    """Governance status for a shield-head chainage observation or scope."""

    TRUSTED = "TRUSTED"
    SUSPECT_JUMP = "SUSPECT_JUMP"
    SUSPECT_SHIFTED_REGIME = "SUSPECT_SHIFTED_REGIME"
    UNRESOLVED = "UNRESOLVED"
    RESTORED = "RESTORED"


@dataclass(frozen=True)
class ChainageRegimeConfig:
    """Thresholds for regime governance."""

    chainage_jump_threshold_m: float = 5.0
    implausible_advance_m: float = 100.0
    max_cross_file_time_gap_seconds: float = 60.0
    max_cross_file_chainage_gap_m: float = 1.0


@dataclass
class ChainageRegimeState:
    """State carried across daily files."""

    previous_raw_chainage: float | None = None
    previous_trusted_chainage: float | None = None
    active_status: ChainageRegimeStatus = ChainageRegimeStatus.TRUSTED
    active_regime_id: str = "regime-0001"
    regime_index: int = 1

    def next_regime_id(self) -> str:
        self.regime_index += 1
        self.active_regime_id = f"regime-{self.regime_index:04d}"
        return self.active_regime_id


def classify_daily_observations(
    *,
    target_date: str,
    frame: pd.DataFrame,
    state: ChainageRegimeState,
    config: ChainageRegimeConfig,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    """Classify observations while preserving raw shield-head chainage values."""

    ordered = frame.sort_values(["timestamp", "source_row_number"]).reset_index(drop=True).copy()
    audit_rows: list[dict[str, Any]] = []
    statuses: list[str] = []
    regime_ids: list[str] = []
    usable_flags: list[bool] = []
    reason_codes_by_row: list[list[str]] = []

    for row in ordered.itertuples(index=False):
        raw = _to_float(getattr(row, "shield_head_chainage", None))
        previous_raw = state.previous_raw_chainage
        delta = raw - previous_raw if raw is not None and previous_raw is not None else None
        status, spatially_usable, reason_codes = _classify_one(raw, delta, state, config)
        statuses.append(status.value)
        regime_ids.append(state.active_regime_id)
        usable_flags.append(spatially_usable)
        reason_codes_by_row.append(reason_codes)
        audit_rows.append(
            {
                "target_date": target_date,
                "timestamp": row.timestamp.isoformat(),
                "observation_id": row.observation_id,
                "raw_shield_head_chainage": raw,
                "previous_raw_chainage": previous_raw,
                "delta_m": delta,
                "regime_id": state.active_regime_id,
                "regime_status": status.value,
                "spatially_usable": spatially_usable,
                "reason_codes": reason_codes,
            }
        )
        if raw is not None:
            state.previous_raw_chainage = raw
        if spatially_usable and raw is not None:
            state.previous_trusted_chainage = raw

    ordered["chainage_regime_id"] = regime_ids
    ordered["chainage_regime_status"] = statuses
    ordered["chainage_spatially_usable"] = usable_flags
    ordered["chainage_regime_reason_codes"] = reason_codes_by_row
    daily_audit = _daily_audit(target_date, ordered)
    return ordered, audit_rows, daily_audit


def _classify_one(
    raw: float | None,
    delta: float | None,
    state: ChainageRegimeState,
    config: ChainageRegimeConfig,
) -> tuple[ChainageRegimeStatus, bool, list[str]]:
    if raw is None:
        return ChainageRegimeStatus.UNRESOLVED, False, ["MISSING_SHIELD_HEAD_CHAINAGE"]

    if state.active_status in {
        ChainageRegimeStatus.SUSPECT_JUMP,
        ChainageRegimeStatus.SUSPECT_SHIFTED_REGIME,
        ChainageRegimeStatus.UNRESOLVED,
    }:
        if _can_restore(raw, state.previous_trusted_chainage, config):
            state.next_regime_id()
            state.active_status = ChainageRegimeStatus.RESTORED
            return ChainageRegimeStatus.RESTORED, True, ["CHAINAGE_REGIME_RESTORED"]
        state.active_status = ChainageRegimeStatus.SUSPECT_SHIFTED_REGIME
        return (
            ChainageRegimeStatus.SUSPECT_SHIFTED_REGIME,
            False,
            ["SUSPECT_SHIFTED_REGIME_PENDING_REVIEW"],
        )

    if delta is not None and abs(delta) > config.chainage_jump_threshold_m:
        if abs(delta) > config.implausible_advance_m:
            state.next_regime_id()
            state.active_status = ChainageRegimeStatus.SUSPECT_SHIFTED_REGIME
            return ChainageRegimeStatus.SUSPECT_JUMP, False, ["CHAINAGE_REGIME_JUMP"]
        return ChainageRegimeStatus.UNRESOLVED, False, ["CHAINAGE_JUMP_EXCEEDS_THRESHOLD"]

    return state.active_status, True, []


def _can_restore(
    raw: float,
    previous_trusted_chainage: float | None,
    config: ChainageRegimeConfig,
) -> bool:
    if previous_trusted_chainage is None:
        return False
    forward_delta = raw - previous_trusted_chainage
    return 0 <= forward_delta <= config.implausible_advance_m


def _daily_audit(target_date: str, frame: pd.DataFrame) -> dict[str, Any]:
    raw = pd.to_numeric(frame["shield_head_chainage"], errors="coerce").dropna()
    usable = frame[frame["chainage_spatially_usable"]]
    trusted = pd.to_numeric(usable["shield_head_chainage"], errors="coerce").dropna()
    statuses = sorted(set(frame["chainage_regime_status"].astype(str).to_list()))
    if trusted.empty:
        trusted_range = None
        spatial_scope_status = "UNAVAILABLE"
    else:
        trusted_range = {
            "kind": "INTERVAL",
            "start_chainage": float(trusted.min()),
            "end_chainage": float(trusted.max()),
            "basis": "trusted_chainage_regime_daily_range",
        }
        spatial_scope_status = "AVAILABLE" if len(statuses) == 1 else "PARTIAL"
    return {
        "target_date": target_date,
        "raw_daily_plc_range": {
            "kind": "INTERVAL",
            "start_chainage": float(raw.min()) if not raw.empty else None,
            "end_chainage": float(raw.max()) if not raw.empty else None,
            "basis": "raw_shield_head_chainage_daily_range",
        },
        "trusted_daily_plc_range": trusted_range,
        "spatial_scope_status": spatial_scope_status,
        "regime_statuses": statuses,
        "usable_observation_count": int(usable.shape[0]),
        "unusable_observation_count": int((~frame["chainage_spatially_usable"]).sum()),
    }


def _to_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
