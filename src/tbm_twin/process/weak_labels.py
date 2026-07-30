"""Transparent weak-label rules for PLC operation phases."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tbm_twin.process.models import OperationPhase, ValidExcavationSubphase

PHASE_METHOD_VERSION = "operation_phase_weak_rules_v1"


@dataclass(frozen=True)
class PhaseRuleConfig:
    """Centralized thresholds for weak phase labels."""

    speed_eps: float = 1e-9
    thrust_eps: float = 1e-9
    torque_eps: float = 1e-9
    rpm_eps: float = 1e-9
    large_gap_factor: float = 5.0
    minimum_large_gap_seconds: float = 300.0
    set_speed_relative_tolerance: float = 0.2


def label_operation_phases(
    normalized_frame: pd.DataFrame,
    config: PhaseRuleConfig | None = None,
) -> pd.DataFrame:
    """Label normalized PLC rows with explainable weak operation phases."""

    config = config or PhaseRuleConfig()
    frame = (
        normalized_frame.sort_values(["timestamp", "source_row_number"])
        .reset_index(drop=True)
        .copy()
    )
    threshold = _infer_gap_threshold(frame, config)
    time_diffs = frame["timestamp"].diff().dt.total_seconds()
    phases: list[str] = []
    subphases: list[str | None] = []
    reasons: list[list[str]] = []

    for idx, row in frame.iterrows():
        if idx > 0 and threshold is not None and float(time_diffs.iloc[idx]) > threshold:
            phases.append(OperationPhase.DATA_GAP.value)
            subphases.append(None)
            reasons.append(["large_time_gap"])
            continue
        phase, subphase, row_reasons = _classify_row(row, config)
        phases.append(phase.value)
        subphases.append(subphase.value if subphase else None)
        reasons.append(row_reasons)

    frame["operation_phase"] = phases
    frame["excavation_subphase"] = subphases
    frame["phase_reason_codes"] = reasons
    frame["phase_method_version"] = PHASE_METHOD_VERSION
    return frame


def _infer_gap_threshold(frame: pd.DataFrame, config: PhaseRuleConfig) -> float | None:
    if len(frame) < 2:
        return None
    diffs = frame["timestamp"].sort_values().diff().dt.total_seconds().dropna()
    positive = diffs[diffs > 0]
    if positive.empty:
        return None
    median = float(positive.median())
    return max(config.large_gap_factor * median, config.minimum_large_gap_seconds)


def _classify_row(
    row: pd.Series,
    config: PhaseRuleConfig,
) -> tuple[OperationPhase, ValidExcavationSubphase | None, list[str]]:
    state = row.get("excavation_state")
    speed = _num(row.get("advance_speed"))
    thrust = _num(row.get("total_thrust"))
    torque = _num(row.get("cutterhead_torque"))
    rpm = _num(row.get("cutterhead_rpm"))
    set_speed = _num(row.get("set_advance_speed"))

    signals = {
        "speed": speed,
        "thrust": thrust,
        "torque": torque,
        "rpm": rpm,
    }
    present_count = sum(value is not None for value in signals.values())
    state_known = state is not None and not pd.isna(state)

    speed_on = speed is not None and speed > config.speed_eps
    thrust_on = thrust is not None and thrust > config.thrust_eps
    torque_on = torque is not None and torque > config.torque_eps
    rpm_on = rpm is not None and rpm > config.rpm_eps

    if not state_known and present_count < 2:
        return OperationPhase.UNKNOWN, None, ["insufficient_core_signals"]

    if state_known and _state_is_idle(state):
        return OperationPhase.IDLE, None, ["excavation_state_idle"]

    if speed_on and thrust_on and (torque_on or rpm_on or not _has(torque, rpm)):
        return (
            OperationPhase.EXCAVATING,
            _subphase(speed, set_speed, config),
            ["speed_and_thrust_positive"],
        )

    if (thrust_on or torque_on or rpm_on) and not speed_on:
        return OperationPhase.STARTUP, None, ["machine_response_without_advance_speed"]

    if speed_on and not (thrust_on or torque_on):
        return OperationPhase.COASTDOWN, None, ["advance_speed_without_primary_load"]

    if present_count >= 2 and not any([speed_on, thrust_on, torque_on, rpm_on]):
        return OperationPhase.IDLE, None, ["core_signals_near_zero"]

    return OperationPhase.UNKNOWN, None, ["weak_rules_inconclusive"]


def _num(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(str(value))


def _has(*values: float | None) -> bool:
    return any(value is not None for value in values)


def _state_is_idle(state: object) -> bool:
    text = str(state).strip().lower()
    return text in {"0", "0.0", "idle", "stop", "stopped", "停机"}


def _subphase(
    speed: float | None,
    set_speed: float | None,
    config: PhaseRuleConfig,
) -> ValidExcavationSubphase:
    if speed is None or speed <= config.speed_eps:
        return ValidExcavationSubphase.TRANSIENT
    if set_speed is None or abs(set_speed) <= config.speed_eps:
        return ValidExcavationSubphase.VARIABLE
    relative = abs(speed - set_speed) / abs(set_speed)
    if relative <= config.set_speed_relative_tolerance:
        return ValidExcavationSubphase.STEADY
    return ValidExcavationSubphase.VARIABLE
