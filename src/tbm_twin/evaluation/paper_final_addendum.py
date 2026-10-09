# ruff: noqa: RUF001
"""Read-only final paper audits over frozen construction artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from tbm_twin.evaluation.paper_evidence_completion import build_rai_reason_audit

PAPER_OUTPUT_DIR = Path("artifacts/paper_evidence_completion_v2")
PLC_DIR = Path("artifacts/stage2_plc_operational_freeze_v2")
GEOLOGY_DIR = Path("artifacts/stage2_geology_v2_freeze_candidate")
STATE_DIR = Path("artifacts/stage3a_initial_epistemic_state_v1_1")
METRIC_DIR = Path("artifacts/stage4_bitemporal_state_metrics_v1_1")


def build_paper_final_addendum(
    repo_root: Path, output_dir: Path = PAPER_OUTPUT_DIR
) -> dict[str, Any]:
    """Build only the three requested paper audits without rebuilding frozen stages."""

    repo_root = repo_root.resolve()
    output_dir = (repo_root / output_dir).resolve() if not output_dir.is_absolute() else output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    coverage = audit_progression_episode_coverage(repo_root, output_dir)
    metadata = export_engineering_metadata(repo_root, output_dir)
    rai = build_rai_reason_audit(repo_root, output_dir)
    input_identity = _write_input_identity(repo_root, output_dir)
    payload = {
        "progression_episode_coverage": coverage,
        "engineering_metadata_field_count": len(metadata),
        "rai_availability": rai,
        "input_identity": input_identity,
    }
    (output_dir / "paper_final_addendum.md").write_text(_render_addendum(payload), encoding="utf-8")
    _write_addendum_hashes(output_dir)
    return payload


def audit_progression_episode_coverage(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    """Require trusted Episode footprints to intersect strict forecast-face associations."""

    contexts = pd.read_csv(
        output_dir / "construction_progression_contexts.csv", keep_default_na=False
    )
    associations = pd.read_csv(
        output_dir / "construction_progression_associations.csv", keep_default_na=False
    )
    strict_contexts = contexts[_true_series(contexts["strict_primary_context"])]
    strict_associations = associations[associations["association_tier"] == "SAME_DAY_DIRECT"]

    states = {
        str(row["state_version_id"]): row
        for row in _read_jsonl(repo_root / STATE_DIR / "initial_construction_state_versions.jsonl")
    }
    episodes = {
        str(row["episode_id"]): row
        for row in _read_jsonl(repo_root / PLC_DIR / "excavation_episodes.jsonl")
    }
    footprints = {
        str(row["episode_id"]): row
        for row in _read_jsonl(repo_root / PLC_DIR / "spatial_footprints.jsonl")
    }

    detail_rows: list[dict[str, Any]] = []
    passed_associations: set[str] = set()
    passed_contexts: set[str] = set()
    for association in strict_associations.to_dict("records"):
        state_id = str(association["state_version_id"])
        state = states[state_id]
        for episode_id_raw in state["episode_ids"]:
            episode_id = str(episode_id_raw)
            episode = episodes.get(episode_id)
            footprint = footprints.get(episode_id)
            trusted = _is_trusted_footprint(footprint)
            scope = footprint.get("trusted_spatial_scope") if footprint and trusted else None
            episode_start = float(scope["start_chainage"]) if scope else None
            episode_end = float(scope["end_chainage"]) if scope else None
            face_intersection = bool(
                episode_start is not None
                and episode_end is not None
                and _intervals_intersect(
                    episode_start,
                    episode_end,
                    float(association["observation_start"]),
                    float(association["observation_end"]),
                )
            )
            direct_intersection = bool(
                episode_start is not None
                and episode_end is not None
                and _intervals_intersect(
                    episode_start,
                    episode_end,
                    float(association["direct_overlap_start"]),
                    float(association["direct_overlap_end"]),
                )
            )
            episode_is_real = bool(episode and episode.get("episode_source") == "PLC_INFERRED")
            passes = episode_is_real and trusted and (face_intersection or direct_intersection)
            if passes:
                passed_associations.add(str(association["association_id"]))
                passed_contexts.add(state_id)
            detail_rows.append(
                {
                    "state_version_id": state_id,
                    "target_date": association["target_date"],
                    "cell_id": association["cell_id"],
                    "association_id": association["association_id"],
                    "forecast_evidence_id": association["forecast_evidence_id"],
                    "forecast_start": association["forecast_start"],
                    "forecast_end": association["forecast_end"],
                    "face_evidence_id": association["observation_evidence_id"],
                    "face_chainage": association["observation_start"],
                    "forecast_face_intersection_start": association["direct_overlap_start"],
                    "forecast_face_intersection_end": association["direct_overlap_end"],
                    "episode_id": episode_id,
                    "episode_source": episode.get("episode_source") if episode else None,
                    "footprint_id": footprint.get("footprint_id") if footprint else None,
                    "episode_start": episode_start,
                    "episode_end": episode_end,
                    "footprint_trusted": trusted,
                    "episode_intersects_face": face_intersection,
                    "episode_intersects_forecast_face_intersection": direct_intersection,
                    "intersection_flag": passes,
                    "association_passes_episode_coverage": passes,
                }
            )

    context_rows: list[dict[str, Any]] = []
    for context in strict_contexts.to_dict("records"):
        state_id = str(context["state_version_id"])
        context_rows.append(
            {
                "state_version_id": state_id,
                "target_date": context["target_date"],
                "cell_id": context["cell_id"],
                "candidate_strict_context": True,
                "trusted_episode_coverage_pass": state_id in passed_contexts,
                "final_formal_strict_context": state_id in passed_contexts,
                "decision_reason": (
                    "TRUSTED_EPISODE_FOOTPRINT_INTERSECTS_FACE_OR_DIRECT_INTERSECTION"
                    if state_id in passed_contexts
                    else "NO_TRUSTED_EPISODE_FOOTPRINT_INTERSECTION"
                ),
            }
        )

    final_associations = strict_associations[
        strict_associations["association_id"].astype(str).isin(passed_associations)
    ]
    summary = {
        "candidate_strict_context_count": len(strict_contexts),
        "final_strict_context_count": len(passed_contexts),
        "excluded_context_count": len(strict_contexts) - len(passed_contexts),
        "final_unique_date_count": final_associations["target_date"].nunique(),
        "final_unique_cell_count": final_associations["cell_id"].nunique(),
        "final_forecast_face_association_count": len(final_associations),
        "trusted_episode_association_row_count": sum(
            bool(row["association_passes_episode_coverage"]) for row in detail_rows
        ),
        "formal_result_note": (
            "The former 19-context result is a candidate set. The final formal strict result is "
            "the subset passing trusted Episode footprint intersection."
        ),
    }
    _write_csv(output_dir / "construction_progression_plc_coverage_audit.csv", detail_rows)
    _write_csv(output_dir / "construction_progression_context_final.csv", context_rows)
    _write_json(output_dir / "construction_progression_plc_coverage_summary.json", summary)
    return summary


def export_engineering_metadata(repo_root: Path, output_dir: Path) -> list[dict[str, Any]]:
    """Export only engineering metadata demonstrably present in frozen inputs."""

    plc_manifest_path = repo_root / PLC_DIR / "normalized_observation_manifest.csv"
    plc_manifest = pd.read_csv(plc_manifest_path)
    asset_audit_path = repo_root / PLC_DIR / "plc_input_asset_audit.csv"
    asset_audit = pd.read_csv(asset_audit_path)
    cells_path = repo_root / STATE_DIR / "construction_state_cells.jsonl"
    cells = _read_jsonl(cells_path)
    geology_path = repo_root / GEOLOGY_DIR / "geological_documents.jsonl"
    documents = _read_jsonl(geology_path)

    interval_counts = _plc_interval_counts(repo_root, plc_manifest)
    total_intervals = sum(interval_counts.values())
    dominant = sorted(interval_counts.items(), key=lambda item: (-item[1], item[0]))[:3]
    interval_text = "; ".join(
        f"{seconds:g} s: {count} ({count / total_intervals:.1%})" for seconds, count in dominant
    )
    dates = sorted(date.fromisoformat(str(value)) for value in plc_manifest["target_date"])
    all_dates = [
        dates[0] + timedelta(days=offset) for offset in range((dates[-1] - dates[0]).days + 1)
    ]
    missing_dates = [value.isoformat() for value in all_dates if value not in set(dates)]
    short_days = asset_audit[asset_audit["row_count"] <= 10][["target_date", "row_count"]].to_dict(
        "records"
    )
    source_counts = Counter(str(row["source_type"]) for row in documents)

    grid_start = min(float(row["spatial_start"]) for row in cells)
    grid_end = max(float(row["spatial_end"]) for row in cells)
    plc_start = float(plc_manifest["minimum_chainage"].min())
    plc_end = float(plc_manifest["maximum_chainage"].max())
    metadata: list[dict[str, Any]] = [
        _metadata_row(
            "TBM类型",
            "NOT_AVAILABLE",
            "NOT_AVAILABLE",
            "repository_and_frozen_inputs",
            "未找到可核实字段",
        ),
        _metadata_row(
            "TBM型号",
            "NOT_AVAILABLE",
            "NOT_AVAILABLE",
            "repository_and_frozen_inputs",
            "未找到可核实字段",
        ),
        _metadata_row(
            "开挖直径",
            "NOT_AVAILABLE",
            "NOT_AVAILABLE",
            "repository_and_frozen_inputs",
            "未找到可核实字段",
        ),
        _metadata_row(
            "研究线路",
            "伯舒拉岭隧道进口右线",
            "CONFIRMED",
            str(geology_path.relative_to(repo_root)),
            "canonical document filenames and source paths",
        ),
        _metadata_row(
            "固定分析网格范围",
            f"{_format_chainage(grid_start)}–{_format_chainage(grid_end)}",
            "CONFIRMED",
            str(cells_path.relative_to(repo_root)),
            f"{len(cells)} cells × 10 m",
        ),
        _metadata_row(
            "固定分析网格长度",
            f"{grid_end - grid_start:g} m",
            "CONFIRMED",
            str(cells_path.relative_to(repo_root)),
            "max(spatial_end)-min(spatial_start)",
        ),
        _metadata_row(
            "PLC实际观测里程范围",
            f"{_format_chainage(plc_start)}–{_format_chainage(plc_end)}",
            "CONFIRMED",
            str(plc_manifest_path.relative_to(repo_root)),
            "minimum/maximum chainage across normalized daily manifests",
        ),
        _metadata_row(
            "PLC实际观测里程长度",
            f"{plc_end - plc_start:g} m",
            "CONFIRMED",
            str(plc_manifest_path.relative_to(repo_root)),
            "maximum-minimum observed chainage",
        ),
        _metadata_row(
            "PLC时间范围",
            f"{dates[0].isoformat()}–{dates[-1].isoformat()}",
            "CONFIRMED",
            str(plc_manifest_path.relative_to(repo_root)),
            "first and last target_date",
        ),
        _metadata_row(
            "PLC有效文件日数",
            str(len(plc_manifest)),
            "CONFIRMED",
            str(plc_manifest_path.relative_to(repo_root)),
            "normalized daily files",
        ),
        _metadata_row(
            "PLC记录行数",
            str(int(plc_manifest["row_count"].sum())),
            "CONFIRMED",
            str(plc_manifest_path.relative_to(repo_root)),
            "sum(row_count)",
        ),
        _metadata_row(
            "PLC主要时间间隔",
            interval_text,
            "CONFIRMED",
            str((PLC_DIR / "normalized_observations").as_posix()),
            "positive consecutive timestamp differences within each daily file",
        ),
        _metadata_row(
            "掌子面记录数量",
            str(source_counts["FACE_SKETCH"]),
            "CONFIRMED",
            str(geology_path.relative_to(repo_root)),
            "canonical FACE_SKETCH documents",
        ),
        _metadata_row(
            "掌子面记录大致间隔",
            _source_spacing(documents, "FACE_SKETCH"),
            "CONFIRMED",
            str(geology_path.relative_to(repo_root)),
            "median spacing of unique document scope starts",
        ),
        _metadata_row(
            "HSP报告数量",
            str(source_counts["SONIC_FORECAST"]),
            "CONFIRMED",
            str(geology_path.relative_to(repo_root)),
            "canonical SONIC_FORECAST documents",
        ),
        _metadata_row(
            "HSP报告大致间隔",
            _source_spacing(documents, "SONIC_FORECAST"),
            "CONFIRMED",
            str(geology_path.relative_to(repo_root)),
            "median spacing of unique document scope starts",
        ),
        _metadata_row(
            "TSP报告数量",
            str(source_counts["TSP_REPORT"]),
            "CONFIRMED",
            str(geology_path.relative_to(repo_root)),
            "canonical TSP_REPORT documents",
        ),
        _metadata_row(
            "TSP报告大致间隔",
            _source_spacing(documents, "TSP_REPORT"),
            "CONFIRMED",
            str(geology_path.relative_to(repo_root)),
            "median spacing of unique document scope starts",
        ),
        _metadata_row(
            "PLC缺失日期",
            f"{len(missing_dates)} days: {';'.join(missing_dates)}",
            "CONFIRMED",
            str(asset_audit_path.relative_to(repo_root)),
            "calendar dates absent between first and last available file",
        ),
        _metadata_row(
            "PLC极短记录日",
            json.dumps(short_days, ensure_ascii=False),
            "CONFIRMED",
            str(asset_audit_path.relative_to(repo_root)),
            "daily source files with <=10 rows",
        ),
    ]
    _write_csv(output_dir / "paper_engineering_metadata.csv", metadata)
    (output_dir / "paper_engineering_metadata.md").write_text(
        _render_metadata(metadata), encoding="utf-8"
    )
    return metadata


def _is_trusted_footprint(footprint: dict[str, Any] | None) -> bool:
    return bool(
        footprint
        and footprint.get("spatial_scope_usable") is True
        and footprint.get("chainage_regime_status") == "TRUSTED"
        and footprint.get("trusted_spatial_scope")
    )


def _intervals_intersect(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    return max(a_start, b_start) <= min(a_end, b_end)


def _plc_interval_counts(repo_root: Path, manifest: pd.DataFrame) -> Counter[float]:
    counts: Counter[float] = Counter()
    for relative_path in manifest["normalized_path"]:
        frame = pd.read_parquet(repo_root / PLC_DIR / str(relative_path), columns=["timestamp"])
        timestamps = pd.to_datetime(frame["timestamp"], utc=True).sort_values().drop_duplicates()
        for value, count in timestamps.diff().dt.total_seconds().dropna().value_counts().items():
            if float(value) > 0:
                counts[float(value)] += int(count)
    return counts


def _source_spacing(documents: list[dict[str, Any]], source_type: str) -> str:
    starts = sorted(
        {
            float(row["document"]["document_spatial_scope"]["start_chainage"])
            for row in documents
            if row["source_type"] == source_type
        }
    )
    differences = [right - left for left, right in pairwise(starts)]
    return f"median {median(differences):g} m by chainage" if differences else "NOT_AVAILABLE"


def _format_chainage(value: float) -> str:
    kilometre = int(value // 1000)
    offset = value - kilometre * 1000
    offset_text = f"{offset:.1f}".rstrip("0").rstrip(".")
    if "." not in offset_text:
        offset_text = offset_text.zfill(3)
    return f"DyK{kilometre}+{offset_text}"


def _metadata_row(
    field: str, value: str, status: str, source_path: str, source_detail: str
) -> dict[str, str]:
    return {
        "field": field,
        "value": value,
        "status": status,
        "source_path": source_path,
        "source_detail": source_detail,
    }


def _render_metadata(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 论文工程元数据",
        "",
        "仅记录仓库和冻结输入中可核实的信息；缺失项不作推测。",
        "",
        "| 字段 | 值 | 状态 | 来源 |",
        "|---|---|---|---|",
    ]
    for row in rows:
        value = str(row["value"]).replace("|", "\\|")
        lines.append(
            f"| {row['field']} | {value} | {row['status']} | "
            f"`{row['source_path']}`：{row['source_detail']} |"
        )
    return "\n".join(lines) + "\n"


def _write_input_identity(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    paths = [
        PAPER_OUTPUT_DIR / "construction_progression_contexts.csv",
        PAPER_OUTPUT_DIR / "construction_progression_associations.csv",
        PLC_DIR / "excavation_episodes.jsonl",
        PLC_DIR / "spatial_footprints.jsonl",
        PLC_DIR / "normalized_observation_manifest.csv",
        PLC_DIR / "file_hashes.sha256",
        GEOLOGY_DIR / "geological_documents.jsonl",
        GEOLOGY_DIR / "file_hashes.sha256",
        STATE_DIR / "initial_construction_state_versions.jsonl",
        STATE_DIR / "construction_state_cells.jsonl",
        STATE_DIR / "file_hashes.sha256",
        METRIC_DIR / "state_rai.jsonl",
        METRIC_DIR / "file_hashes.sha256",
    ]
    file_rows = []
    for relative_path in paths:
        path = repo_root / relative_path
        file_rows.append(
            {
                "path": str(relative_path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    payload = {"git_commit": _git_head(repo_root), "files": file_rows}
    _write_json(output_dir / "paper_final_addendum_input_hashes.json", payload)
    return payload


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _render_addendum(payload: dict[str, Any]) -> str:
    coverage = payload["progression_episode_coverage"]
    rai = payload["rai_availability"]
    identity = payload["input_identity"]
    return f"""# 论文实验最终补充审计

## 1. 施工推进情境的真实掘进足迹核验

- 原候选严格情境：{coverage["candidate_strict_context_count"]}。
- 经可信Episode空间足迹核验后的正式严格情境：{coverage["final_strict_context_count"]}。
- 日期数：{coverage["final_unique_date_count"]}；空间单元数：{coverage["final_unique_cell_count"]}。
- 预测—掌子面关联数：{coverage["final_forecast_face_association_count"]}。
- 被排除情境：{coverage["excluded_context_count"]}。

旧19个情境仅作为Episode足迹核验前的候选集合；论文正式结果使用核验后的数量。

明细：`construction_progression_plc_coverage_audit.csv`
情境判定：`construction_progression_context_final.csv`
汇总：`construction_progression_plc_coverage_summary.json`

## 2. 工程元数据

共导出{payload["engineering_metadata_field_count"]}项可核实字段。无法从仓库或冻结输入确认的
TBM类型、型号和开挖直径均记为`NOT_AVAILABLE`，未进行推测。

表格：`paper_engineering_metadata.csv`
可读版：`paper_engineering_metadata.md`

## 3. RAI可用性原因术语

论文审计层已将“因果基线不足”统一改为“历史样本基线不足”，判定逻辑和数量未改变。
当日复核状态共{rai["daily_review_count"]}个，其中RAI可用{rai["available_daily_review_count"]}个，
不可用{rai["daily_review_unavailable_count"]}个。

汇总：`rai_availability_reason_summary.csv`
逐状态：`rai_daily_review_unavailability_cases.csv`

## 输入身份

- Git commit：`{identity["git_commit"]}`
- 输入文件及SHA-256：`paper_final_addendum_input_hashes.json`

本补充仅执行只读审计，未修改主算法、主pipeline、冻结输入或既有实验判定逻辑。
"""


def _write_addendum_hashes(output_dir: Path) -> None:
    names = [
        "construction_progression_plc_coverage_audit.csv",
        "construction_progression_context_final.csv",
        "construction_progression_plc_coverage_summary.json",
        "paper_engineering_metadata.csv",
        "paper_engineering_metadata.md",
        "rai_availability_reason_summary.csv",
        "rai_daily_review_unavailability_cases.csv",
        "paper_final_addendum_input_hashes.json",
        "paper_final_addendum.md",
    ]
    rows = [
        f"{hashlib.sha256((output_dir / name).read_bytes()).hexdigest()}  {name}" for name in names
    ]
    (output_dir / "paper_final_addendum_hashes.sha256").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )


def _true_series(series: pd.Series[Any]) -> pd.Series[Any]:
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
