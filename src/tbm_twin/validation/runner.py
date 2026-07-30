"""Stage 1.5 real-data validation runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tbm_twin.assets.models import SourceType
from tbm_twin.assets.registry import register_source_asset
from tbm_twin.channels.catalog import load_channel_catalog
from tbm_twin.process.episode_builder import build_excavation_episodes, finalize_episode_quality
from tbm_twin.process.weak_labels import label_operation_phases
from tbm_twin.settings import load_settings
from tbm_twin.timeseries.normalization import normalize_plc_csv, write_normalized_parquet
from tbm_twin.timeseries.reader import read_plc_csv
from tbm_twin.trajectory.footprint_builder import build_spatial_footprints
from tbm_twin.validation.config import (
    load_episode_builder_config,
    load_footprint_builder_config,
    load_phase_rule_config,
    load_validation_config,
)
from tbm_twin.validation.diagnostics import (
    build_automatic_diagnostics,
    build_channel_audit,
    build_phase_intervals,
)
from tbm_twin.validation.models import ValidationErrorRecord
from tbm_twin.validation.summaries import (
    build_episode_summary_rows,
    build_footprint_summary_rows,
    build_validation_summary_rows,
    write_csv,
    write_manual_template,
)
from tbm_twin.validation.visualization import write_episode_review_plot

DEFAULT_DATES = ["2023-12-30", "2023-12-28", "2023-09-15"]


def resolve_validation_paths(
    *,
    plc_data_dir: Path | None = None,
    artifact_dir: Path | None = None,
) -> tuple[Path | None, Path]:
    """Resolve validation directories from explicit arguments or environment defaults."""

    settings = load_settings()
    resolved_plc_dir = plc_data_dir or settings.plc_data_dir
    if resolved_plc_dir is None and settings.tbm_data_root is not None:
        resolved_plc_dir = settings.tbm_data_root / "TBM9_2023"
    return resolved_plc_dir, artifact_dir or settings.artifact_dir / "stage1_validation"


def run_stage1_validation(
    *,
    plc_data_dir: Path | None = None,
    dates: list[str] | None = None,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    """Run Stage 1 validation for real or fixture PLC data."""

    dates = dates or DEFAULT_DATES
    resolved_plc_dir, resolved_artifact_dir = resolve_validation_paths(
        plc_data_dir=plc_data_dir,
        artifact_dir=artifact_dir,
    )
    resolved_artifact_dir.mkdir(parents=True, exist_ok=True)
    before_episode_summary = _read_existing_csv(resolved_artifact_dir / "episode_summary.csv")
    before_footprint_summary = _read_existing_csv(resolved_artifact_dir / "footprint_summary.csv")
    catalog = load_channel_catalog()
    phase_config = load_phase_rule_config()
    episode_config = load_episode_builder_config()
    footprint_config = load_footprint_builder_config()
    validation_config = load_validation_config()

    date_results: list[dict[str, Any]] = []
    all_channel_rows: list[dict[str, Any]] = []
    all_episode_rows: list[dict[str, Any]] = []
    all_footprint_rows: list[dict[str, Any]] = []

    for date in dates:
        date_dir = resolved_artifact_dir / date
        date_dir.mkdir(parents=True, exist_ok=True)
        try:
            if resolved_plc_dir is None:
                msg = "PLC data directory is not configured. Provide --plc-data-dir."
                raise FileNotFoundError(msg)
            input_path = resolved_plc_dir / f"tbm_data_{date.replace('-', '')}.csv"
            if not input_path.exists():
                msg = f"Expected PLC file is missing: {input_path}"
                raise FileNotFoundError(msg)

            raw_frame = read_plc_csv(input_path)
            source_asset = register_source_asset(
                input_path,
                SourceType.PLC_CSV,
                source_timezone=catalog.timezone.source_timezone,
                canonical_timezone=catalog.timezone.canonical_timezone,
                timezone_confidence=catalog.timezone.timezone_confidence.value,
                timezone_basis=catalog.timezone.timezone_basis.value,
            )
            channel_audit = build_channel_audit(raw_frame, catalog)
            normalization = normalize_plc_csv(input_path, source_asset, catalog)
            source_asset = source_asset.model_copy(
                update={"timezone_warnings": normalization.metadata.timezone_warnings}
            )
            normalized_path = date_dir / "normalized_plc.parquet"
            write_normalized_parquet(normalization, normalized_path)
            labeled = label_operation_phases(normalization.frame, phase_config)
            phase_intervals = build_phase_intervals(labeled)
            episodes = build_excavation_episodes(labeled, episode_config)
            footprints = build_spatial_footprints(labeled, episodes, footprint_config)
            footprint_by_episode = {footprint.episode_id: footprint for footprint in footprints}
            episodes = [
                finalize_episode_quality(
                    episode,
                    labeled,
                    footprint_status=footprint_by_episode[
                        episode.episode_id
                    ].consistency_status.value
                    if episode.episode_id in footprint_by_episode
                    else None,
                    footprint_quality_flags=footprint_by_episode[episode.episode_id].quality_flags
                    if episode.episode_id in footprint_by_episode
                    else [],
                    config=episode_config,
                )
                for episode in episodes
            ]
            diagnostics = build_automatic_diagnostics(
                date=date,
                raw_frame=raw_frame,
                normalized_frame=normalization.frame,
                labeled_frame=labeled,
                quality_report=normalization.quality_report,
                phase_intervals=phase_intervals,
                episodes=episodes,
                footprints=footprints,
                config=validation_config,
            )
            warnings = _validation_warnings(diagnostics, channel_audit)
            warnings.extend(
                write_episode_review_plot(
                    date=date,
                    labeled_frame=labeled,
                    episodes=episodes,
                    output_path=date_dir / "episode_review.png",
                    config=validation_config,
                )
            )
            status = "warning" if warnings else "success"

            _write_json(date_dir / "source_asset.json", source_asset.model_dump(mode="json"))
            _write_json(date_dir / "channel_audit.json", channel_audit)
            _write_json(
                date_dir / "normalization_metadata.json",
                normalization.metadata.model_dump(mode="json"),
            )
            _write_json(
                date_dir / "plc_quality_report.json",
                normalization.quality_report.model_dump(mode="json"),
            )
            _write_json(
                date_dir / "phase_intervals.json",
                [interval.model_dump(mode="json") for interval in phase_intervals],
            )
            _write_json(
                date_dir / "episodes.json",
                [episode.model_dump(mode="json") for episode in episodes],
            )
            _write_json(
                date_dir / "spatial_footprints.json",
                [footprint.model_dump(mode="json") for footprint in footprints],
            )
            _write_json(date_dir / "automatic_diagnostics.json", diagnostics)

            episode_rows = build_episode_summary_rows(date, episodes, footprints)
            footprint_rows = build_footprint_summary_rows(date, footprints)
            write_csv(date_dir / "episode_review.csv", episode_rows)
            _write_json(
                date_dir / "validation_summary.json",
                {
                    "date": date,
                    "status": status,
                    "warnings": warnings,
                    "diagnostics": diagnostics,
                },
            )
            all_channel_rows.extend({"date": date, **row} for row in channel_audit)
            all_episode_rows.extend(episode_rows)
            all_footprint_rows.extend(footprint_rows)
            date_results.append(
                {
                    "date": date,
                    "status": status,
                    "input_path": str(input_path),
                    "output_dir": str(date_dir),
                    "warnings": warnings,
                    "quality_grade": normalization.quality_report.grade.value,
                    "diagnostics": diagnostics,
                    "error": None,
                }
            )
        except (OSError, ValueError, RuntimeError) as exc:
            error = ValidationErrorRecord(
                error_type=type(exc).__name__,
                message=str(exc),
            )
            _write_json(
                date_dir / "validation_summary.json",
                {
                    "date": date,
                    "status": "failed",
                    "warnings": [],
                    "error": error.model_dump(mode="json"),
                },
            )
            date_results.append(
                {
                    "date": date,
                    "status": "failed",
                    "input_path": str(resolved_plc_dir / f"tbm_data_{date.replace('-', '')}.csv")
                    if resolved_plc_dir
                    else None,
                    "output_dir": str(date_dir),
                    "warnings": [],
                    "quality_grade": None,
                    "diagnostics": {},
                    "error": error.model_dump(mode="json"),
                }
            )

    validation_rows = build_validation_summary_rows(date_results)
    write_csv(resolved_artifact_dir / "validation_summary.csv", validation_rows)
    _write_json(
        resolved_artifact_dir / "validation_summary.json",
        {
            "plc_data_dir": str(resolved_plc_dir) if resolved_plc_dir else None,
            "artifact_dir": str(resolved_artifact_dir),
            "success_count": sum(result["status"] == "success" for result in date_results),
            "warning_count": sum(result["status"] == "warning" for result in date_results),
            "failed_count": sum(result["status"] == "failed" for result in date_results),
            "dates": date_results,
        },
    )
    write_csv(resolved_artifact_dir / "channel_mapping_summary.csv", all_channel_rows)
    write_csv(resolved_artifact_dir / "episode_summary.csv", all_episode_rows)
    write_csv(resolved_artifact_dir / "footprint_summary.csv", all_footprint_rows)
    comparison_rows = _build_stage16_comparison(
        before_episode_summary,
        before_footprint_summary,
        pd.DataFrame(all_episode_rows),
        pd.DataFrame(all_footprint_rows),
        dates,
    )
    write_csv(resolved_artifact_dir / "stage16_regression_comparison.csv", comparison_rows)
    _write_json(
        resolved_artifact_dir / "stage16_regression_comparison.json",
        {"rows": comparison_rows},
    )
    write_manual_template(resolved_artifact_dir / "plc_episode_reference_review.csv")
    _write_json(
        resolved_artifact_dir / "calibration_history.json",
        {"no_calibration_applied": True, "entries": []},
    )
    _write_report(
        resolved_artifact_dir / "stage1_validation_report.md",
        plc_data_dir=resolved_plc_dir,
        artifact_dir=resolved_artifact_dir,
        date_results=date_results,
    )
    return {
        "plc_data_dir": str(resolved_plc_dir) if resolved_plc_dir else None,
        "artifact_dir": str(resolved_artifact_dir),
        "success_count": sum(result["status"] == "success" for result in date_results),
        "warning_count": sum(result["status"] == "warning" for result in date_results),
        "failed_count": sum(result["status"] == "failed" for result in date_results),
        "dates": date_results,
    }


def _validation_warnings(
    diagnostics: dict[str, Any],
    channel_audit: list[dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    chainage = next(
        (row for row in channel_audit if row["canonical_name"] == "shield_head_chainage"),
        None,
    )
    if chainage and chainage["matched_raw_column"] != "导向盾首里程":
        warnings.append("shield_head_chainage did not match 导向盾首里程")
    if diagnostics["episode"]["episode_gap_crossing_count"]:
        warnings.append("episode crosses DATA_GAP")
    if diagnostics["episode"]["episode_long_idle_crossing_count"]:
        warnings.append("episode contains long IDLE interval")
    if diagnostics["footprint"]["negative_advance_count"]:
        warnings.append("negative estimated advance emitted")
    if diagnostics["footprint"]["implausible_advance_count"]:
        warnings.append("implausible estimated advance emitted")
    if diagnostics["phase"]["unknown_ratio"] > 0.5:
        warnings.append("UNKNOWN phase ratio above 0.5")
    return warnings


def _read_existing_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path)


def _build_stage16_comparison(
    before_episodes: pd.DataFrame | None,
    before_footprints: pd.DataFrame | None,
    after_episodes: pd.DataFrame,
    after_footprints: pd.DataFrame,
    dates: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for date in dates:
        before_ep = _filter_date(before_episodes, date)
        before_fp = _filter_date(before_footprints, date)
        after_ep = _filter_date(after_episodes, date)
        after_fp = _filter_date(after_footprints, date)
        rows.append(
            {
                "date": date,
                "before_available": before_episodes is not None and before_footprints is not None,
                "episode_count_before": len(before_ep),
                "episode_count_after": len(after_ep),
                "core_duration_before": _sum_column(before_ep, "system_duration_seconds"),
                "core_duration_after": _sum_column(after_ep, "system_duration_seconds"),
                "context_duration_before": _sum_column(
                    before_ep, "system_context_duration_seconds"
                ),
                "context_duration_after": _sum_column(after_ep, "system_context_duration_seconds"),
                "boundary_status_before": _value_counts(before_ep, "system_boundary_status"),
                "boundary_status_after": _value_counts(after_ep, "system_boundary_status"),
                "quality_distribution_before": _value_counts(before_ep, "system_quality_grade"),
                "quality_distribution_after": _value_counts(after_ep, "system_quality_grade"),
                "footprint_status_before": _value_counts(before_fp, "consistency_status"),
                "footprint_status_after": _value_counts(after_fp, "consistency_status"),
                "zero_advance_flags_before": _contains_count(
                    before_fp,
                    "quality_flags",
                    "ZERO_ADVANCE_DURING_EXCAVATION",
                ),
                "zero_advance_flags_after": _contains_count(
                    after_fp,
                    "quality_flags",
                    "ZERO_ADVANCE_DURING_EXCAVATION",
                ),
            }
        )
    return rows


def _filter_date(frame: pd.DataFrame | None, date: str) -> pd.DataFrame:
    if frame is None or frame.empty or "date" not in frame.columns:
        return pd.DataFrame()
    return frame[frame["date"].astype(str).eq(date)].copy()


def _sum_column(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame.columns:
        return None
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0.0).sum())


def _value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    return {str(key): int(value) for key, value in frame[column].value_counts().to_dict().items()}


def _contains_count(frame: pd.DataFrame, column: str, needle: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(frame[column].fillna("").astype(str).str.contains(needle, regex=False).sum())


def _write_report(
    path: Path,
    *,
    plc_data_dir: Path | None,
    artifact_dir: Path,
    date_results: list[dict[str, Any]],
) -> None:
    success_count = sum(result["status"] == "success" for result in date_results)
    warning_count = sum(result["status"] == "warning" for result in date_results)
    failed_count = sum(result["status"] == "failed" for result in date_results)
    conclusion = _stage1_conclusion(date_results)
    lines = [
        "# Stage 1 Real Data Validation",
        "",
        (
            "Legacy outputs are diagnostic references rather than PLC-informed proxy "
            "reference annotations."
        ),
        "",
        "## 1. 验证目的",
        "",
        (
            "验证真实PLC CSV是否能通过 Stage 1 的字段映射、标准化、质量诊断、"
            "弱Phase、Episode和SpatialFootprint闭环。"
        ),
        "",
        "## 2. 代表日期",
        "",
        ", ".join(result["date"] for result in date_results),
        "",
        "## 3. 数据配置",
        "",
        f"- PLC data dir: `{plc_data_dir}`",
        f"- Artifact dir: `{artifact_dir}`",
        "",
        "## 4. 字段匹配结果",
        "",
        (
            "详见 `channel_mapping_summary.csv`。重点检查 `shield_head_chainage` "
            "是否匹配 `导向盾首里程`。"
        ),
        "",
        "## 5. 数据质量结果",
        "",
        "详见每个日期目录下的 `plc_quality_report.json` 和 `automatic_diagnostics.json`。",
        "",
        "## 6. Phase分布",
        "",
        "详见 `automatic_diagnostics.json` 中的 `phase` 节。",
        "",
        "## 7. Episode结果",
        "",
        "详见 `episode_summary.csv` 与每个日期的 `episode_review.csv` / `episode_review.png`。",
        (
            "Episode now separates core excavation time from context time; "
            "see `system_context_*` fields."
        ),
        "",
        "## 8. Footprint结果",
        "",
        (
            "详见 `footprint_summary.csv`。INCONSISTENT 或 INSUFFICIENT 的 "
            "`estimated_advance_m` 不作为精确Claim依据。0m推进复核标记也不作为精确进尺依据。"
        ),
        "",
        "## 9. 与旧系统的诊断差异",
        "",
        (
            "本次未把旧系统输出作为真值。若运行旧仓库导出脚本, "
            "可只比较行数、时间范围、盾首里程首尾、旧工作区间和旧质量警告。"
        ),
        "",
        "## 10. 当前限制",
        "",
        "- 尚未完成PLC-informed proxy reference复核。",
        "- 单位未验证字段只用于透明弱标签和诊断, 不用于物理结论。",
        "- Episode有效性仍需要人工复核图和标注模板确认。",
        "",
        "## 11. 人工标注计划",
        "",
        (
            "填写 `plc_episode_reference_review.csv`, "
            "再用 `scripts/evaluate_episodes.py` 与 `episode_summary.csv` 做Episode级IoU评价。"
        ),
        "",
        "## 12. Stage 1验收结论",
        "",
        f"`{conclusion}`",
        "",
        "## Run Summary",
        "",
        f"- success: {success_count}",
        f"- warning: {warning_count}",
        f"- failed: {failed_count}",
        "- Stage 1.6 comparison: `stage16_regression_comparison.csv`",
        "",
    ]
    for result in date_results:
        diagnostics = result.get("diagnostics", {})
        lines.extend(
            [
                f"### {result['date']}",
                "",
                f"- status: `{result['status']}`",
                f"- quality grade: `{result.get('quality_grade')}`",
                f"- raw rows: `{_nested(diagnostics, 'data_scale', 'raw_row_count')}`",
                f"- episodes: `{_nested(diagnostics, 'episode', 'episode_count')}`",
                (
                    "- footprint distribution: "
                    f"`{_nested(diagnostics, 'footprint', 'footprint_consistency_distribution')}`"
                ),
                f"- warnings: `{'; '.join(result.get('warnings', []))}`",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _stage1_conclusion(date_results: list[dict[str, Any]]) -> str:
    if any(result["status"] == "failed" for result in date_results):
        return "NOT_READY"
    if any(result["status"] == "warning" for result in date_results):
        return "PASS_WITH_LIMITATIONS"
    if len(date_results) < 3:
        return "PASS_WITH_LIMITATIONS"
    return "PASS_WITH_LIMITATIONS"


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value
