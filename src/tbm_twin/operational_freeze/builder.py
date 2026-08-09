"""Builder for the Stage 2E PLC operational evidence freeze."""

from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.metadata
import json
import math
import os
import shutil
import sys
import tarfile
from collections import Counter
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import pandas as pd

from tbm_twin.assets.models import SourceType
from tbm_twin.assets.registry import register_source_asset
from tbm_twin.channels.catalog import load_channel_catalog
from tbm_twin.evidence.models import BaselineMethod
from tbm_twin.evidence.response_builder import load_response_config, response_evidence_summary
from tbm_twin.operational_freeze.chainage_regime import (
    ChainageRegimeConfig,
    ChainageRegimeState,
    classify_daily_observations,
)
from tbm_twin.operational_freeze.io import (
    count_jsonl,
    hash_directory_files,
    read_csv_with_encoding,
    sha256_file,
    sha256_text,
    verify_hash_manifest,
    write_csv,
    write_file_hashes,
    write_json,
    write_jsonl,
)
from tbm_twin.operational_freeze.models import (
    STAGE2E_METHOD_NAME,
    STAGE2E_METHOD_VERSION,
    DailyScopeReference,
    DateBuildResult,
    OperationalFreezeConfig,
    OperationalFreezeResult,
    OperationalResponseEvidenceRecord,
    OperationalSourceAssetRecord,
    PlcInputAssetAuditRow,
    TargetDateSet,
)
from tbm_twin.operational_freeze.response import build_no_baseline_response_evidence
from tbm_twin.operational_freeze.validation import (
    episode_integrity_rows,
    footprint_integrity_rows,
    response_integrity_rows,
)
from tbm_twin.process.episode_builder import build_excavation_episodes, finalize_episode_quality
from tbm_twin.process.models import EpisodeBoundaryStatus, ExcavationEpisode
from tbm_twin.process.weak_labels import PHASE_METHOD_VERSION, label_operation_phases
from tbm_twin.timeseries.normalization import NORMALIZATION_VERSION, normalize_plc_csv
from tbm_twin.trajectory.footprint_builder import build_spatial_footprints
from tbm_twin.trajectory.models import SpatialFootprint
from tbm_twin.validation.config import (
    load_detection_config,
    load_episode_builder_config,
    load_footprint_builder_config,
    load_phase_rule_config,
)
from tbm_twin.validation.diagnostics import build_channel_audit, build_phase_intervals

CELL_SIZE_M = 10.0
LOOKAHEAD_M = 30.0
LOCAL_BACKGROUND_BACK_M = 100.0


class OperationalFreezeBuilder:
    """Build the deterministic Stage 2E PLC operational freeze."""

    def __init__(self, config: OperationalFreezeConfig) -> None:
        self.config = config
        self.repo = config.repo_root
        self.out = config.output_dir
        self.applicability_dir = config.resolve(config.applicability_dir)
        self.geology_dir = config.resolve(config.geology_freeze_dir)
        self.stage1_dir = config.resolve(config.stage1_validation_dir)
        self.catalog = load_channel_catalog(config.resolve(config.channel_catalog_path))
        self.phase_config = load_phase_rule_config(config.resolve(config.episode_config_path))
        self.episode_config = load_episode_builder_config(
            config.resolve(config.episode_config_path)
        )
        self.footprint_config = load_footprint_builder_config(
            config.resolve(config.episode_config_path)
        )
        self.response_config = load_response_config(config.resolve(config.response_config_path))
        self.chainage_config = self._load_chainage_regime_config()

    def build(self) -> OperationalFreezeResult:
        """Build all Stage 2E outputs."""

        self._prepare_output_dir()
        pre_protected = self._verify_protected_or_raise("PRE")
        self._assert_existing_freeze_counts()
        target_dates = self._load_target_dates()
        plc_data_dir = self._resolve_plc_data_dir()
        scopes = self._load_daily_scopes(target_dates.dates)

        all_source_assets: list[dict[str, Any]] = []
        all_phase_intervals: list[dict[str, Any]] = []
        all_episodes: list[dict[str, Any]] = []
        all_footprints: list[dict[str, Any]] = []
        all_responses: list[dict[str, Any]] = []
        all_scope_refs: list[dict[str, Any]] = []
        all_channel_rows: list[dict[str, Any]] = []
        quality_rows: list[dict[str, Any]] = []
        normalized_manifest_rows: list[dict[str, Any]] = []
        input_audit_rows: list[dict[str, Any]] = []
        episode_daily_rows: list[dict[str, Any]] = []
        episode_integrity: list[dict[str, Any]] = []
        footprint_integrity: list[dict[str, Any]] = []
        response_integrity: list[dict[str, Any]] = []
        scope_audit_rows: list[dict[str, Any]] = []
        provenance_rows: list[dict[str, Any]] = []
        response_audit_rows: list[dict[str, Any]] = []
        footprint_audit_rows: list[dict[str, Any]] = []
        regression_rows: list[dict[str, Any]] = []
        chainage_observation_rows: list[dict[str, Any]] = []
        chainage_episode_rows: list[dict[str, Any]] = []
        chainage_daily_rows: list[dict[str, Any]] = []
        plc_daily_scope_v2_rows: list[dict[str, Any]] = []

        all_date_results: list[DateBuildResult] = []
        first_last_by_date: dict[
            date, tuple[ExcavationEpisode | None, ExcavationEpisode | None]
        ] = {}
        spatial_scope_by_episode: dict[str, dict[str, Any]] = {}
        all_episode_models: list[ExcavationEpisode] = []
        all_observation_ids: set[str] = set()
        all_observation_total_count = 0
        regime_state = ChainageRegimeState()

        for target_date in target_dates.dates:
            date_result = self._build_one_date(
                target_date=target_date,
                plc_data_dir=plc_data_dir,
                scopes=scopes,
                all_source_assets=all_source_assets,
                all_phase_intervals=all_phase_intervals,
                all_episodes=all_episodes,
                all_footprints=all_footprints,
                all_responses=all_responses,
                all_scope_refs=all_scope_refs,
                all_channel_rows=all_channel_rows,
                quality_rows=quality_rows,
                normalized_manifest_rows=normalized_manifest_rows,
                input_audit_rows=input_audit_rows,
                episode_daily_rows=episode_daily_rows,
                episode_integrity=episode_integrity,
                footprint_integrity=footprint_integrity,
                response_integrity=response_integrity,
                scope_audit_rows=scope_audit_rows,
                provenance_rows=provenance_rows,
                response_audit_rows=response_audit_rows,
                footprint_audit_rows=footprint_audit_rows,
                regression_rows=regression_rows,
                chainage_observation_rows=chainage_observation_rows,
                chainage_episode_rows=chainage_episode_rows,
                chainage_daily_rows=chainage_daily_rows,
                plc_daily_scope_v2_rows=plc_daily_scope_v2_rows,
                first_last_by_date=first_last_by_date,
                spatial_scope_by_episode=spatial_scope_by_episode,
                all_episode_models=all_episode_models,
                all_observation_ids=all_observation_ids,
                regime_state=regime_state,
            )
            all_date_results.append(date_result)
            all_observation_total_count += date_result.normalized_row_count

        cross_file_rows = self._cross_file_candidates(
            target_dates.dates,
            first_last_by_date,
            spatial_scope_by_episode,
        )
        hard_check_rows = self._hard_checks(
            target_dates=target_dates,
            source_assets=all_source_assets,
            normalized_manifest=normalized_manifest_rows,
            scope_audit_rows=scope_audit_rows,
            episode_integrity=episode_integrity,
            footprint_integrity=footprint_integrity,
            response_integrity=response_integrity,
            response_records=all_responses,
            all_observation_ids=all_observation_ids,
            all_observation_total_count=all_observation_total_count,
            provenance_rows=provenance_rows,
        )

        self._write_outputs(
            all_source_assets=all_source_assets,
            normalized_manifest_rows=normalized_manifest_rows,
            all_phase_intervals=all_phase_intervals,
            all_episodes=all_episodes,
            all_footprints=all_footprints,
            all_responses=all_responses,
            all_scope_refs=all_scope_refs,
            input_audit_rows=input_audit_rows,
            all_channel_rows=all_channel_rows,
            quality_rows=quality_rows,
            episode_daily_rows=episode_daily_rows,
            episode_integrity=episode_integrity,
            cross_file_rows=cross_file_rows,
            footprint_audit_rows=footprint_audit_rows,
            response_audit_rows=response_audit_rows,
            scope_audit_rows=scope_audit_rows,
            provenance_rows=provenance_rows,
            regression_rows=regression_rows,
            chainage_observation_rows=chainage_observation_rows,
            chainage_episode_rows=chainage_episode_rows,
            chainage_daily_rows=chainage_daily_rows,
            plc_daily_scope_v2_rows=plc_daily_scope_v2_rows,
            hard_check_rows=hard_check_rows,
            pre_protected=pre_protected,
            date_results=all_date_results,
        )

        post_protected = self._verify_protected_or_raise("POST")
        self._write_protected_hash_audit(pre_protected + post_protected)
        hashes = self._write_final_manifests(
            target_dates=target_dates,
            date_results=all_date_results,
            source_assets=all_source_assets,
            phase_intervals=all_phase_intervals,
            episodes=all_episodes,
            footprints=all_footprints,
            responses=all_responses,
            scope_audit_rows=scope_audit_rows,
            cross_file_rows=cross_file_rows,
            hard_check_rows=hard_check_rows,
            protected_rows=pre_protected + post_protected,
            provenance_rows=provenance_rows,
            chainage_episode_rows=chainage_episode_rows,
        )
        _ = hashes

        if hard_check_rows:
            msg = f"Operational freeze hard checks failed: {len(hard_check_rows)} issues"
            raise RuntimeError(msg)

        return OperationalFreezeResult(
            output_dir=self.out,
            target_date_count=len(target_dates.dates),
            source_asset_count=len(all_source_assets),
            normalized_observation_count=sum(r.normalized_row_count for r in all_date_results),
            phase_interval_count=len(all_phase_intervals),
            episode_count=len(all_episodes),
            footprint_count=len(all_footprints),
            response_evidence_count=len(all_responses),
            scope_exact_match_count=sum(
                1 for row in scope_audit_rows if row["exact_match"] == "True"
            ),
            cross_file_candidate_count=len(cross_file_rows),
            hard_check_issue_count=len(hard_check_rows),
            baseline_mode=BaselineMethod.NO_BASELINE.value,
            reconstruction_time=self.config.reconstruction_time,
        )

    def _prepare_output_dir(self) -> None:
        if self.out.exists() and any(self.out.iterdir()):
            if not self.config.overwrite:
                msg = f"Output directory already exists and is not empty: {self.out}"
                raise FileExistsError(msg)
            shutil.rmtree(self.out)
        (self.out / "normalized_observations").mkdir(parents=True, exist_ok=True)

    def _verify_protected_or_raise(self, phase: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for directory in [self.geology_dir, self.applicability_dir]:
            for row in verify_hash_manifest(directory):
                row["phase"] = phase
                row["protected_dir"] = str(directory)
                rows.append(row)
        bad = [row for row in rows if not row["unchanged"]]
        if bad:
            msg = f"Protected freeze hash verification failed during {phase}: {bad[:3]}"
            raise RuntimeError(msg)
        return rows

    def _load_chainage_regime_config(self) -> ChainageRegimeConfig:
        data = load_detection_config(self.config.resolve(self.config.episode_config_path))
        diagnostics = dict(data.get("diagnostics", {}))
        cross_file = dict(data.get("cross_file_episode_candidates", {}))
        return ChainageRegimeConfig(
            chainage_jump_threshold_m=float(
                diagnostics.get(
                    "large_jump_threshold_m",
                    ChainageRegimeConfig.chainage_jump_threshold_m,
                )
            ),
            implausible_advance_m=float(
                diagnostics.get(
                    "implausible_advance_m",
                    ChainageRegimeConfig.implausible_advance_m,
                )
            ),
            max_cross_file_time_gap_seconds=float(
                cross_file.get(
                    "max_cross_file_time_gap_seconds",
                    ChainageRegimeConfig.max_cross_file_time_gap_seconds,
                )
            ),
            max_cross_file_chainage_gap_m=float(
                cross_file.get(
                    "max_cross_file_chainage_gap_m",
                    ChainageRegimeConfig.max_cross_file_chainage_gap_m,
                )
            ),
        )

    def _assert_existing_freeze_counts(self) -> None:
        geology_manifest = json.loads((self.geology_dir / "freeze_manifest.json").read_text())
        geology_summary = geology_manifest["summary"]
        expected_geology = {
            "canonical_documents": 223,
            "primary_evidence": 659,
            "report_assertions": 122,
            "unlocated_clauses": 496,
            "source_spans": 4713,
        }
        for key, expected in expected_geology.items():
            actual = int(geology_summary[key])
            if actual != expected:
                msg = f"Geology freeze baseline mismatch for {key}: {actual} != {expected}"
                raise RuntimeError(msg)
        expected_applicability = {
            "applicability_daily_summary.csv": 91,
            "evidence_applicability_assignments.jsonl": 59969,
            "assertion_applicability_assignments.jsonl": 11102,
            "clause_applicability_assignments.jsonl": 45136,
        }
        for filename, expected in expected_applicability.items():
            path = self.applicability_dir / filename
            actual = _count_csv_data_rows(path) if path.suffix == ".csv" else count_jsonl(path)
            if actual != expected:
                msg = f"Applicability baseline mismatch for {filename}: {actual} != {expected}"
                raise RuntimeError(msg)

    def _load_target_dates(self) -> TargetDateSet:
        daily_path = self.applicability_dir / "applicability_daily_summary.csv"
        with daily_path.open("r", encoding="utf-8", newline="") as handle:
            dates = [date.fromisoformat(row["target_date"]) for row in csv.DictReader(handle)]
        assignment_dates: set[date] = set()
        assignments_path = self.applicability_dir / "evidence_applicability_assignments.jsonl"
        with assignments_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    assignment_dates.add(date.fromisoformat(json.loads(line)["target_date"]))
        unique_dates = sorted(set(dates))
        if len(dates) != len(unique_dates):
            msg = "applicability_daily_summary.csv contains duplicate target_date values"
            raise ValueError(msg)
        if unique_dates != sorted(assignment_dates):
            msg = "Applicability daily summary dates differ from assignment target dates"
            raise ValueError(msg)
        if len(unique_dates) != 91:
            msg = f"Expected 91 target dates, found {len(unique_dates)}"
            raise ValueError(msg)
        if unique_dates[0] != date(2023, 9, 15) or unique_dates[-1] != date(2023, 12, 30):
            msg = f"Unexpected target date bounds: {unique_dates[0]}..{unique_dates[-1]}"
            raise ValueError(msg)
        return TargetDateSet(
            dates=unique_dates,
            source_file=daily_path,
            assignment_date_count=len(assignment_dates),
        )

    def _load_daily_scopes(self, dates: list[date]) -> dict[date, dict[str, Any]]:
        scopes: dict[date, dict[str, Any]] = {}
        scope_fields = [
            "daily_plc_range",
            "daily_excavated_scope",
            "forward_scope",
            "local_background_scope",
        ]
        path = self.applicability_dir / "evidence_applicability_assignments.jsonl"
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                obj = json.loads(line)
                target_date = date.fromisoformat(obj["target_date"])
                current = {field: obj[field] for field in scope_fields}
                if target_date in scopes and scopes[target_date] != current:
                    msg = f"Non-unique daily scope in Applicability for {target_date}"
                    raise ValueError(msg)
                scopes[target_date] = current
        expected = set(dates)
        if set(scopes) != expected:
            msg = "Daily scope references do not cover the target date set"
            raise ValueError(msg)
        return scopes

    def _resolve_plc_data_dir(self) -> Path:
        explicit = self.config.plc_data_dir or _env_plc_data_dir()
        if explicit is not None:
            resolved = explicit
        else:
            summary = json.loads((self.stage1_dir / "validation_summary.json").read_text())
            raw_dir = summary.get("plc_data_dir")
            if not raw_dir:
                msg = "PLC_DATA_DIR is unset and Stage 1 validation summary has no plc_data_dir"
                raise FileNotFoundError(msg)
            resolved = Path(str(raw_dir))
        if not resolved.exists():
            msg = f"PLC data directory does not exist: {resolved}"
            raise FileNotFoundError(msg)
        return resolved

    def _build_one_date(
        self,
        *,
        target_date: date,
        plc_data_dir: Path,
        scopes: dict[date, dict[str, Any]],
        all_source_assets: list[dict[str, Any]],
        all_phase_intervals: list[dict[str, Any]],
        all_episodes: list[dict[str, Any]],
        all_footprints: list[dict[str, Any]],
        all_responses: list[dict[str, Any]],
        all_scope_refs: list[dict[str, Any]],
        all_channel_rows: list[dict[str, Any]],
        quality_rows: list[dict[str, Any]],
        normalized_manifest_rows: list[dict[str, Any]],
        input_audit_rows: list[dict[str, Any]],
        episode_daily_rows: list[dict[str, Any]],
        episode_integrity: list[dict[str, Any]],
        footprint_integrity: list[dict[str, Any]],
        response_integrity: list[dict[str, Any]],
        scope_audit_rows: list[dict[str, Any]],
        provenance_rows: list[dict[str, Any]],
        response_audit_rows: list[dict[str, Any]],
        footprint_audit_rows: list[dict[str, Any]],
        regression_rows: list[dict[str, Any]],
        chainage_observation_rows: list[dict[str, Any]],
        chainage_episode_rows: list[dict[str, Any]],
        chainage_daily_rows: list[dict[str, Any]],
        plc_daily_scope_v2_rows: list[dict[str, Any]],
        first_last_by_date: dict[date, tuple[ExcavationEpisode | None, ExcavationEpisode | None]],
        spatial_scope_by_episode: dict[str, dict[str, Any]],
        all_episode_models: list[ExcavationEpisode],
        all_observation_ids: set[str],
        regime_state: ChainageRegimeState,
    ) -> DateBuildResult:
        raw_path = plc_data_dir / f"tbm_data_{target_date.strftime('%Y%m%d')}.csv"
        raw, encoding = read_csv_with_encoding(raw_path)
        source_asset = register_source_asset(
            raw_path,
            SourceType.PLC_CSV,
            ingested_time=self.config.reconstruction_time,
            source_timezone=self.catalog.timezone.source_timezone,
            canonical_timezone=self.catalog.timezone.canonical_timezone,
            timezone_confidence=self.catalog.timezone.timezone_confidence.value,
            timezone_basis=self.catalog.timezone.timezone_basis.value,
        )
        normalized = normalize_plc_csv(raw_path, source_asset, self.catalog)
        source_asset = source_asset.model_copy(
            update={"timezone_warnings": normalized.metadata.timezone_warnings}
        )
        asset_row = source_asset.model_dump(mode="json")
        asset_row.update(
            {
                "target_date": target_date,
                "reconstructed_at": self.config.reconstruction_time,
                "historical_ingestion_time": None,
                "ingestion_time_known": False,
                "ingestion_time_basis": "OFFLINE_RECONSTRUCTION_NOT_HISTORICAL",
            }
        )
        all_source_assets.append(
            OperationalSourceAssetRecord.model_validate(asset_row).model_dump(mode="json")
        )
        input_audit_rows.append(
            PlcInputAssetAuditRow(
                target_date=target_date,
                raw_filename=raw_path.name,
                resolved_local_path=raw_path.resolve(),
                file_exists=True,
                file_size=raw_path.stat().st_size,
                sha256=source_asset.content_hash,
                encoding=encoding,
                row_count=len(raw),
                column_count=len(raw.columns),
                source_asset_id=source_asset.asset_id,
                status="OK",
                warning_codes=[],
            ).model_dump(mode="json")
        )

        channel_rows = self._channel_rows(target_date, raw)
        all_channel_rows.extend(channel_rows)
        classified_frame, observation_audit, daily_regime = classify_daily_observations(
            target_date=target_date.isoformat(),
            frame=normalized.frame,
            state=regime_state,
            config=self.chainage_config,
        )
        chainage_observation_rows.extend(observation_audit)
        chainage_daily_rows.append(daily_regime)
        plc_daily_scope_v2_rows.append(
            self._daily_scope_v2_row(
                target_date,
                scopes[target_date],
                daily_regime,
            )
        )
        normalized_path = (
            self.out / "normalized_observations" / f"{target_date.isoformat()}.parquet"
        )
        classified_frame.to_parquet(normalized_path, index=False)
        normalized_sha = sha256_file(normalized_path)
        all_observation_ids.update(classified_frame["observation_id"].astype(str).to_list())
        labeled = label_operation_phases(classified_frame, self.phase_config)
        phase_intervals = build_phase_intervals(labeled)
        episodes = build_excavation_episodes(labeled, self.episode_config)
        footprints = build_spatial_footprints(labeled, episodes, self.footprint_config)
        footprint_by_id = {footprint.episode_id: footprint for footprint in footprints}
        episodes = [
            finalize_episode_quality(
                episode,
                labeled,
                footprint_status=footprint_by_id[episode.episode_id].consistency_status.value
                if episode.episode_id in footprint_by_id
                else None,
                footprint_quality_flags=footprint_by_id[episode.episode_id].quality_flags
                if episode.episode_id in footprint_by_id
                else [],
                config=self.episode_config,
            )
            for episode in episodes
        ]
        responses = build_no_baseline_response_evidence(
            labeled,
            episodes,
            footprints,
            config=self.response_config,
            reconstruction_time=self.config.reconstruction_time,
        )

        all_phase_intervals.extend(
            self._phase_interval_records(target_date, source_asset.asset_id, phase_intervals)
        )
        all_episodes.extend(self._episode_records(target_date, episodes))
        episode_regime_rows, episode_spatial = self._episode_regime_rows(
            target_date,
            episodes,
            footprints,
            labeled,
        )
        chainage_episode_rows.extend(episode_regime_rows)
        all_footprints.extend(self._footprint_records(target_date, footprints, episode_spatial))
        all_responses.extend(self._response_records(target_date, responses, episode_spatial))
        all_episode_models.extend(episodes)
        spatial_scope_by_episode.update(episode_spatial)
        first_last_by_date[target_date] = (
            episodes[0] if episodes else None,
            episodes[-1] if episodes else None,
        )

        raw_min, raw_max = _min_max_chainage(classified_frame)
        scope_ref = DailyScopeReference(
            daily_scope_reference_id=_stable_id(
                "daily-scope",
                target_date.isoformat(),
                json.dumps(scopes[target_date], sort_keys=True),
            ),
            target_date=target_date,
            daily_plc_range=scopes[target_date]["daily_plc_range"],
            daily_excavated_scope=scopes[target_date]["daily_excavated_scope"],
            forward_scope=scopes[target_date]["forward_scope"],
            local_background_scope=scopes[target_date]["local_background_scope"],
            raw_min_chainage=raw_min,
            raw_max_chainage=raw_max,
            method_version=STAGE2E_METHOD_VERSION,
        )
        all_scope_refs.append(scope_ref.model_dump(mode="json"))
        scope_audit_rows.append(
            self._scope_audit_row(target_date, raw_min, raw_max, scopes[target_date])
        )
        normalized_manifest_rows.append(
            self._normalized_manifest_row(
                target_date,
                source_asset.asset_id,
                normalized_path,
                classified_frame,
                normalized_sha,
            )
        )
        quality_rows.append(self._quality_row(target_date, normalized.quality_report))
        episode_daily_rows.append(self._episode_daily_row(target_date, episodes))
        episode_integrity.extend(
            episode_integrity_rows(
                target_date=target_date,
                episodes=episodes,
                labeled_frame=labeled,
            )
        )
        footprint_integrity.extend(
            footprint_integrity_rows(
                target_date=target_date,
                footprints=footprints,
                episode_ids={episode.episode_id for episode in episodes},
            )
        )
        response_integrity.extend(
            response_integrity_rows(
                target_date=target_date,
                responses=responses,
                episodes_by_id={episode.episode_id: episode for episode in episodes},
            )
        )
        provenance_rows.extend(
            self._provenance_rows(
                target_date,
                phase_intervals,
                episodes,
                footprints,
                responses,
                set(classified_frame["observation_id"].astype(str).to_list()),
            )
        )
        footprint_audit_rows.extend(
            self._footprint_audit_rows(target_date, footprints, episode_spatial)
        )
        response_audit_rows.extend(self._response_audit_rows(target_date, responses))
        regression_rows.extend(
            self._stage1_regression_rows(
                target_date,
                phase_intervals,
                episodes,
                footprints,
                responses,
            )
        )

        return DateBuildResult(
            target_date=target_date,
            source_asset_id=source_asset.asset_id,
            normalized_row_count=len(normalized.frame),
            phase_interval_count=len(phase_intervals),
            episode_count=len(episodes),
            footprint_count=len(footprints),
            response_evidence_count=len(responses),
            raw_min_chainage=raw_min,
            raw_max_chainage=raw_max,
        )

    def _channel_rows(self, target_date: date, raw: pd.DataFrame) -> list[dict[str, Any]]:
        rows = []
        raw_columns = [str(column) for column in raw.columns]
        selected = self.catalog.resolve_columns(raw_columns)
        selected_anchor = selected.get("shield_head_chainage")
        nearby_chainage = [
            column
            for column in raw_columns
            if column != (selected_anchor.raw_name if selected_anchor else None)
            and ("里程" in column or "chainage" in column.lower())
        ]
        for row in build_channel_audit(raw, self.catalog):
            row = dict(row)
            row["target_date"] = target_date
            row["nearby_non_anchor_chainage_columns"] = (
                nearby_chainage if row["canonical_name"] == "shield_head_chainage" else []
            )
            rows.append(row)
        return rows

    def _phase_interval_records(
        self,
        target_date: date,
        asset_id: str,
        intervals: list[Any],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for idx, interval in enumerate(intervals):
            row = interval.model_dump(mode="json")
            row.update(
                {
                    "phase_interval_id": _stable_id(
                        "phase",
                        target_date.isoformat(),
                        asset_id,
                        str(idx),
                        row["phase"],
                        row["valid_start"],
                        row["valid_end"],
                    ),
                    "target_date": target_date,
                    "asset_id": asset_id,
                    "method_version": PHASE_METHOD_VERSION,
                }
            )
            records.append(row)
        return records

    def _episode_records(
        self,
        target_date: date,
        episodes: list[ExcavationEpisode],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for episode in episodes:
            row = episode.model_dump(mode="json")
            row["target_date"] = target_date
            row["episode_source"] = "PLC_INFERRED"
            records.append(row)
        return records

    def _daily_scope_v2_row(
        self,
        target_date: date,
        old_scope: dict[str, Any],
        daily_regime: dict[str, Any],
    ) -> dict[str, Any]:
        trusted = daily_regime["trusted_daily_plc_range"]
        if trusted is None:
            daily_excavated = None
            forward = None
            local_background = None
            current_chainage = None
        else:
            start = float(trusted["start_chainage"])
            end = float(trusted["end_chainage"])
            excavated_start = (start // CELL_SIZE_M) * CELL_SIZE_M
            excavated_end = _ceil_to_cell(end, CELL_SIZE_M)
            if excavated_end <= excavated_start:
                excavated_end = excavated_start + CELL_SIZE_M
            daily_excavated = _scope(
                "INTERVAL",
                excavated_start,
                excavated_end,
                "trusted_ten_meter_aligned_daily_review_scope",
            )
            forward = _scope(
                "INTERVAL",
                excavated_end,
                excavated_end + LOOKAHEAD_M,
                "trusted_forward_attention_scope",
            )
            local_background = _scope(
                "INTERVAL",
                excavated_start - LOCAL_BACKGROUND_BACK_M,
                excavated_start,
                "trusted_local_background_scope",
            )
            current_chainage = end
        return {
            "daily_scope_reference_id": _stable_id("daily-scope-v2", target_date.isoformat()),
            "target_date": target_date,
            "raw_daily_plc_range": daily_regime["raw_daily_plc_range"],
            "trusted_daily_plc_range": trusted,
            "daily_plc_range": trusted,
            "daily_excavated_scope": daily_excavated,
            "forward_scope": forward,
            "local_background_scope": local_background,
            "current_chainage": current_chainage,
            "spatial_scope_status": daily_regime["spatial_scope_status"],
            "regime_statuses": daily_regime["regime_statuses"],
            "old_applicability_daily_plc_range": old_scope["daily_plc_range"],
            "method_version": STAGE2E_METHOD_VERSION,
        }

    def _episode_regime_rows(
        self,
        target_date: date,
        episodes: list[ExcavationEpisode],
        footprints: list[SpatialFootprint],
        labeled: pd.DataFrame,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        rows: list[dict[str, Any]] = []
        spatial_by_episode: dict[str, dict[str, Any]] = {}
        by_obs = labeled.set_index("observation_id", drop=False)
        footprint_by_episode = {footprint.episode_id: footprint for footprint in footprints}
        for episode in episodes:
            core = by_obs.loc[[ref for ref in episode.core_observation_refs if ref in by_obs.index]]
            footprint = footprint_by_episode[episode.episode_id]
            raw_chainage = pd.to_numeric(core["shield_head_chainage"], errors="coerce").dropna()
            usable_core = core[core["chainage_spatially_usable"]]
            trusted_chainage = pd.to_numeric(
                usable_core["shield_head_chainage"],
                errors="coerce",
            ).dropna()
            statuses = sorted(set(core["chainage_regime_status"].astype(str).to_list()))
            regime_ids = sorted(set(core["chainage_regime_id"].astype(str).to_list()))
            spatial_usable = (
                len(core) > 0 and len(usable_core) == len(core) and not raw_chainage.empty
            )
            final_status, reasons = _final_spatial_status(statuses, spatial_usable)
            trusted_scope = (
                _chainage_scope(
                    float(trusted_chainage.iloc[0]),
                    float(trusted_chainage.iloc[-1]),
                    "trusted_episode_core_chainage_scope",
                )
                if spatial_usable and not trusted_chainage.empty
                else None
            )
            raw_scope = (
                _chainage_scope(
                    float(raw_chainage.iloc[0]),
                    float(raw_chainage.iloc[-1]),
                    "raw_episode_core_chainage_scope",
                )
                if not raw_chainage.empty
                else None
            )
            info = {
                "raw_spatial_scope": raw_scope,
                "trusted_spatial_scope": trusted_scope,
                "spatial_scope_usable": spatial_usable,
                "chainage_regime_status": final_status,
                "chainage_regime_reason_codes": reasons,
            }
            spatial_by_episode[episode.episode_id] = info
            rows.append(
                {
                    "target_date": target_date,
                    "episode_id": episode.episode_id,
                    "raw_start_chainage": raw_scope["start_chainage"] if raw_scope else None,
                    "raw_end_chainage": raw_scope["end_chainage"] if raw_scope else None,
                    "trusted_start_chainage": trusted_scope["start_chainage"]
                    if trusted_scope
                    else None,
                    "trusted_end_chainage": trusted_scope["end_chainage"]
                    if trusted_scope
                    else None,
                    "regime_ids": regime_ids,
                    "regime_status": statuses,
                    "spatial_scope_usable": spatial_usable,
                    "existing_footprint_status": footprint.consistency_status.value,
                    "final_spatial_status": final_status,
                    "reason_codes": reasons,
                }
            )
        return rows, spatial_by_episode

    def _footprint_records(
        self,
        target_date: date,
        footprints: list[SpatialFootprint],
        episode_spatial: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for footprint in footprints:
            row = footprint.model_dump(mode="json")
            spatial = episode_spatial[footprint.episode_id]
            row["target_date"] = target_date
            row["primary_chainage_anchor"] = "shield_head_chainage"
            row["independent_source_count"] = 1 if footprint.source_asset_count else 0
            row["raw_spatial_scope"] = spatial["raw_spatial_scope"]
            row["trusted_spatial_scope"] = spatial["trusted_spatial_scope"]
            row["spatial_scope_usable"] = spatial["spatial_scope_usable"]
            row["chainage_regime_status"] = spatial["chainage_regime_status"]
            row["chainage_regime_reason_codes"] = spatial["chainage_regime_reason_codes"]
            records.append(row)
        return records

    def _response_records(
        self,
        target_date: date,
        responses: list[Any],
        episode_spatial: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for response in responses:
            row = response.model_dump(mode="json")
            spatial = episode_spatial[response.episode_id]
            row["raw_spatial_scope"] = spatial["raw_spatial_scope"]
            row["trusted_spatial_scope"] = spatial["trusted_spatial_scope"]
            row["spatial_scope"] = _evidence_spatial_scope(spatial["trusted_spatial_scope"])
            row["spatial_scope_usable"] = spatial["spatial_scope_usable"]
            row["chainage_regime_status"] = spatial["chainage_regime_status"]
            row["chainage_regime_reason_codes"] = spatial["chainage_regime_reason_codes"]
            row.update(
                {
                    "target_date": target_date,
                    "available_time_basis": "PLC_STREAM_AVAILABLE_AFTER_EPISODE_END",
                    "baseline_method": BaselineMethod.NO_BASELINE.value,
                    "reconstructed_at": self.config.reconstruction_time,
                    "historical_ingestion_time": None,
                    "ingestion_time_known": False,
                    "ingestion_time_basis": "OFFLINE_RECONSTRUCTION_NOT_HISTORICAL",
                }
            )
            records.append(
                OperationalResponseEvidenceRecord.model_validate(row).model_dump(mode="json")
            )
        return records

    def _normalized_manifest_row(
        self,
        target_date: date,
        source_asset_id: str,
        normalized_path: Path,
        frame: pd.DataFrame,
        normalized_sha: str,
    ) -> dict[str, Any]:
        chainage = pd.to_numeric(frame["shield_head_chainage"], errors="coerce")
        timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        return {
            "target_date": target_date,
            "source_asset_id": source_asset_id,
            "normalized_path": normalized_path.relative_to(self.out).as_posix(),
            "row_count": len(frame),
            "valid_timestamp_count": int(timestamps.notna().sum()),
            "valid_chainage_count": int(chainage.notna().sum()),
            "first_timestamp": timestamps.min().isoformat() if timestamps.notna().any() else None,
            "last_timestamp": timestamps.max().isoformat() if timestamps.notna().any() else None,
            "minimum_chainage": _safe_float(chainage.min()) if chainage.notna().any() else None,
            "maximum_chainage": _safe_float(chainage.max()) if chainage.notna().any() else None,
            "normalized_sha256": normalized_sha,
            "normalization_method_version": NORMALIZATION_VERSION,
        }

    def _quality_row(self, target_date: date, quality_report: Any) -> dict[str, Any]:
        channel_missing = {
            channel.canonical_name: channel.missing_rate for channel in quality_report.channels
        }
        return {
            "target_date": target_date,
            "asset_id": quality_report.asset_id,
            "row_count_raw": quality_report.row_count_raw,
            "row_count_normalized": quality_report.row_count_normalized,
            "quality_grade": quality_report.grade.value,
            "reason_codes": quality_report.reason_codes,
            "warnings": quality_report.warnings,
            "timestamp_parse_failed_count": quality_report.time.parse_failed_count,
            "large_gap_count": quality_report.time.large_gap_count,
            "shield_head_chainage_missing_count": quality_report.chainage.missing_count,
            "chainage_reverse_count": quality_report.chainage.reverse_count,
            "chainage_large_jump_count": quality_report.chainage.large_jump_count,
            "channel_missing_rates": channel_missing,
        }

    def _episode_daily_row(
        self,
        target_date: date,
        episodes: list[ExcavationEpisode],
    ) -> dict[str, Any]:
        return {
            "target_date": target_date,
            "episode_count": len(episodes),
            "total_core_duration_seconds": sum(
                episode.core_excavation_duration_seconds for episode in episodes
            ),
            "boundary_status_distribution": Counter(
                episode.boundary_status.value for episode in episodes
            ),
            "quality_grade_distribution": Counter(episode.quality_grade for episode in episodes),
            "zero_advance_episode_count": sum(
                "ZERO_ADVANCE_DURING_EXCAVATION" in episode.quality_flags for episode in episodes
            ),
            "episode_ids": [episode.episode_id for episode in episodes],
        }

    def _scope_audit_row(
        self,
        target_date: date,
        raw_min: float | None,
        raw_max: float | None,
        scope: dict[str, Any],
    ) -> dict[str, Any]:
        daily = cast(dict[str, Any], scope["daily_plc_range"])
        app_start = _safe_float(daily.get("start_chainage"))
        app_end = _safe_float(daily.get("end_chainage"))
        start_diff = _diff(raw_min, app_start)
        end_diff = _diff(raw_max, app_end)
        exact = start_diff == 0.0 and end_diff == 0.0
        return {
            "target_date": target_date,
            "raw_min_chainage": raw_min,
            "raw_max_chainage": raw_max,
            "applicability_daily_start": app_start,
            "applicability_daily_end": app_end,
            "start_difference_m": start_diff,
            "end_difference_m": end_diff,
            "exact_match": str(exact),
            "status": "OK" if exact else "MISMATCH",
            "reason_codes": [] if exact else ["PLC_APPLICABILITY_SCOPE_MISMATCH"],
        }

    def _provenance_rows(
        self,
        target_date: date,
        phase_intervals: list[Any],
        episodes: list[ExcavationEpisode],
        footprints: list[SpatialFootprint],
        responses: list[Any],
        observation_ids: set[str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        episode_ids = {episode.episode_id for episode in episodes}
        for interval in phase_intervals:
            phase_interval_id = _stable_id(
                "phase-ref",
                target_date.isoformat(),
                interval.valid_start.isoformat(),
                interval.valid_end.isoformat(),
                interval.phase.value,
            )
            for ref in interval.observation_refs:
                rows.append(
                    _reference_row(
                        target_date,
                        "PhaseInterval",
                        phase_interval_id,
                        "observation_ref",
                        ref,
                        ref in observation_ids,
                    )
                )
        for episode in episodes:
            for ref in episode.observation_refs:
                rows.append(
                    _reference_row(
                        target_date,
                        "ExcavationEpisode",
                        episode.episode_id,
                        "observation_ref",
                        ref,
                        ref in observation_ids,
                    )
                )
            for ref in episode.core_observation_refs:
                rows.append(
                    _reference_row(
                        target_date,
                        "ExcavationEpisode",
                        episode.episode_id,
                        "core_observation_ref",
                        ref,
                        ref in observation_ids,
                    )
                )
        for footprint in footprints:
            rows.append(
                _reference_row(
                    target_date,
                    "SpatialFootprint",
                    footprint.footprint_id,
                    "episode_id",
                    footprint.episode_id,
                    footprint.episode_id in episode_ids,
                )
            )
        for response in responses:
            rows.append(
                _reference_row(
                    target_date,
                    "ResponseEvidence",
                    response.evidence_id,
                    "episode_id",
                    response.episode_id,
                    response.episode_id in episode_ids,
                )
            )
            for ref in response.core_observation_refs:
                rows.append(
                    _reference_row(
                        target_date,
                        "ResponseEvidence",
                        response.evidence_id,
                        "core_observation_ref",
                        ref,
                        ref in observation_ids,
                    )
                )
        return rows

    def _footprint_audit_rows(
        self,
        target_date: date,
        footprints: list[SpatialFootprint],
        episode_spatial: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows = []
        for footprint in footprints:
            spatial = episode_spatial[footprint.episode_id]
            rows.append(
                {
                    "target_date": target_date,
                    "footprint_id": footprint.footprint_id,
                    "episode_id": footprint.episode_id,
                    "start_chainage": footprint.start_chainage,
                    "end_chainage": footprint.end_chainage,
                    "estimated_advance_m": footprint.estimated_advance_m,
                    "consistency_status": footprint.consistency_status.value,
                    "quality_grade": footprint.quality_grade,
                    "quality_flags": footprint.quality_flags,
                    "supporting_channel_names": footprint.supporting_channel_names,
                    "independent_source_count": 1 if footprint.source_asset_count else 0,
                    "raw_spatial_scope": spatial["raw_spatial_scope"],
                    "trusted_spatial_scope": spatial["trusted_spatial_scope"],
                    "spatial_scope_usable": spatial["spatial_scope_usable"],
                    "chainage_regime_status": spatial["chainage_regime_status"],
                    "chainage_regime_reason_codes": spatial["chainage_regime_reason_codes"],
                }
            )
        return rows

    def _response_audit_rows(self, target_date: date, responses: list[Any]) -> list[dict[str, Any]]:
        rows = response_evidence_summary(responses)
        for row in rows:
            row["target_date"] = target_date
            row["baseline_method"] = BaselineMethod.NO_BASELINE.value
            row["available_time_basis"] = "PLC_STREAM_AVAILABLE_AFTER_EPISODE_END"
            row["historical_ingestion_time_known"] = False
        return rows

    def _stage1_regression_rows(
        self,
        target_date: date,
        phase_intervals: list[Any],
        episodes: list[ExcavationEpisode],
        footprints: list[SpatialFootprint],
        responses: list[Any],
    ) -> list[dict[str, Any]]:
        if target_date.isoformat() not in {"2023-09-15", "2023-12-28", "2023-12-30"}:
            return []
        date_dir = self.stage1_dir / target_date.isoformat()
        if not date_dir.exists():
            return [
                {
                    "target_date": target_date,
                    "check_name": "stage1_reference_exists",
                    "status": "MISSING_REFERENCE",
                    "details": str(date_dir),
                }
            ]
        old_episodes = json.loads((date_dir / "episodes.json").read_text(encoding="utf-8"))
        old_footprints = json.loads(
            (date_dir / "spatial_footprints.json").read_text(encoding="utf-8")
        )
        old_phase_intervals = json.loads(
            (date_dir / "phase_intervals.json").read_text(encoding="utf-8")
        )
        old_response_rows = self._old_stage2e_response_rows(target_date)
        checks = {
            "phase_interval_count": len(old_phase_intervals) == len(phase_intervals),
            "phase_distribution": Counter(item["phase"] for item in old_phase_intervals)
            == Counter(interval.phase.value for interval in phase_intervals),
            "episode_count": len(old_episodes) == len(episodes),
            "episode_ids": [item["episode_id"] for item in old_episodes]
            == [episode.episode_id for episode in episodes],
            "boundary_status": [item["boundary_status"] for item in old_episodes]
            == [episode.boundary_status.value for episode in episodes],
            "episode_quality_grade": [item["quality_grade"] for item in old_episodes]
            == [episode.quality_grade for episode in episodes],
            "episode_quality_reasons": [
                item.get("quality_reason_codes", []) for item in old_episodes
            ]
            == [episode.quality_reason_codes for episode in episodes],
            "footprint_count": len(old_footprints) == len(footprints),
            "footprint_ranges": [
                (item["start_chainage"], item["end_chainage"]) for item in old_footprints
            ]
            == [(footprint.start_chainage, footprint.end_chainage) for footprint in footprints],
            "footprint_consistency_status": [item["consistency_status"] for item in old_footprints]
            == [footprint.consistency_status.value for footprint in footprints],
            "response_count": len(old_response_rows) == len(responses),
            "response_core_refs_match_episode": _response_core_refs_match_episode(
                responses,
                episodes,
            ),
            "response_statistic_hash": _response_statistic_hash(old_response_rows)
            == _response_statistic_hash(
                [response.model_dump(mode="json") for response in responses]
            ),
        }
        return [
            {
                "target_date": target_date,
                "check_name": key,
                "status": "PASS" if ok else "DIFFERENT",
                "details": "",
            }
            for key, ok in checks.items()
        ]

    def _old_stage2e_response_rows(self, target_date: date) -> list[dict[str, Any]]:
        path = self.repo / "artifacts/stage2_plc_operational_freeze/response_evidence.jsonl"
        if not path.exists():
            return []
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("target_date") == target_date.isoformat():
                    rows.append(row)
        return rows

    def _cross_file_candidates(
        self,
        dates: list[date],
        first_last_by_date: dict[date, tuple[ExcavationEpisode | None, ExcavationEpisode | None]],
        spatial_scope_by_episode: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for left_date, right_date in pairwise(dates):
            _, left_episode = first_last_by_date[left_date]
            right_episode, _ = first_last_by_date[right_date]
            if left_episode is None or right_episode is None:
                continue
            if left_episode.boundary_status not in {
                EpisodeBoundaryStatus.RIGHT_CENSORED,
                EpisodeBoundaryStatus.BOTH_CENSORED,
            } or right_episode.boundary_status not in {
                EpisodeBoundaryStatus.LEFT_CENSORED,
                EpisodeBoundaryStatus.BOTH_CENSORED,
            }:
                continue
            left_end = left_episode.excavation_end
            right_start = right_episode.excavation_start
            time_gap = (right_start - left_end).total_seconds()
            left_spatial = spatial_scope_by_episode.get(left_episode.episode_id, {})
            right_spatial = spatial_scope_by_episode.get(right_episode.episode_id, {})
            left_scope = left_spatial.get("trusted_spatial_scope")
            right_scope = right_spatial.get("trusted_spatial_scope")
            chainage_gap: float | None = None
            if time_gap < 0 or time_gap > self.chainage_config.max_cross_file_time_gap_seconds:
                classification = "REJECTED_TIME_GAP"
            else:
                if (
                    not left_spatial.get("spatial_scope_usable")
                    or not right_spatial.get("spatial_scope_usable")
                    or not isinstance(left_scope, dict)
                    or not isinstance(right_scope, dict)
                ):
                    classification = "REJECTED_SPATIAL_UNAVAILABLE"
                else:
                    left_trusted_end = _safe_float(left_scope.get("end_chainage"))
                    right_trusted_start = _safe_float(right_scope.get("start_chainage"))
                    if left_trusted_end is None or right_trusted_start is None:
                        classification = "REJECTED_SPATIAL_UNAVAILABLE"
                    else:
                        chainage_gap = round(right_trusted_start - left_trusted_end, 6)
                        if abs(chainage_gap) > self.chainage_config.max_cross_file_chainage_gap_m:
                            classification = "REJECTED_CHAINAGE_GAP"
                        else:
                            classification = "PLAUSIBLE_CONTINUATION"
            rows.append(
                {
                    "left_date": left_date,
                    "right_date": right_date,
                    "left_episode_id": left_episode.episode_id,
                    "right_episode_id": right_episode.episode_id,
                    "time_gap_seconds": time_gap,
                    "chainage_gap_m": chainage_gap,
                    "left_boundary_status": left_episode.boundary_status.value,
                    "right_boundary_status": right_episode.boundary_status.value,
                    "left_chainage_regime_status": left_spatial.get("chainage_regime_status"),
                    "right_chainage_regime_status": right_spatial.get("chainage_regime_status"),
                    "classification": classification,
                    "possible_continuation": classification == "PLAUSIBLE_CONTINUATION",
                    "decision": "NOT_MERGED_PENDING_REVIEW",
                }
            )
        return rows

    def _hard_checks(
        self,
        *,
        target_dates: TargetDateSet,
        source_assets: list[dict[str, Any]],
        normalized_manifest: list[dict[str, Any]],
        scope_audit_rows: list[dict[str, Any]],
        episode_integrity: list[dict[str, Any]],
        footprint_integrity: list[dict[str, Any]],
        response_integrity: list[dict[str, Any]],
        response_records: list[dict[str, Any]],
        all_observation_ids: set[str],
        all_observation_total_count: int,
        provenance_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        _add_check(
            rows, "TARGET_DATE_COUNT", len(target_dates.dates) == 91, str(len(target_dates.dates))
        )
        _add_check(rows, "SOURCE_ASSET_COUNT", len(source_assets) == 91, str(len(source_assets)))
        _add_check(
            rows,
            "NORMALIZED_DATE_COUNT",
            len(normalized_manifest) == 91,
            str(len(normalized_manifest)),
        )
        _add_check(
            rows,
            "SCOPE_MATCH_91",
            sum(row["exact_match"] == "True" for row in scope_audit_rows) == 91,
            str(sum(row["exact_match"] == "True" for row in scope_audit_rows)),
        )
        _add_check(rows, "EPISODE_INTEGRITY", not episode_integrity, str(len(episode_integrity)))
        _add_check(
            rows, "FOOTPRINT_INTEGRITY", not footprint_integrity, str(len(footprint_integrity))
        )
        _add_check(rows, "RESPONSE_INTEGRITY", not response_integrity, str(len(response_integrity)))
        response_ids = [str(row["evidence_id"]) for row in response_records]
        _add_check(rows, "RESPONSE_ID_UNIQUE", len(response_ids) == len(set(response_ids)), "")
        _add_check(
            rows,
            "OBSERVATION_ID_UNIQUE",
            all_observation_total_count == len(all_observation_ids) == 328217,
            (
                f"normalized_observation_total_count={all_observation_total_count}; "
                f"normalized_observation_unique_id_count={len(all_observation_ids)}"
            ),
        )
        _add_check(
            rows,
            "PROVENANCE_REFERENCES_VALID",
            all(row["status"] == "VALID" for row in provenance_rows),
            (
                f"total={len(provenance_rows)}; "
                f"valid={sum(row['status'] == 'VALID' for row in provenance_rows)}; "
                f"invalid={sum(row['status'] != 'VALID' for row in provenance_rows)}"
            ),
        )
        _add_check(
            rows,
            "NO_BASELINE",
            all(
                row.get("baseline") is None and row.get("deviation") is None
                for row in response_records
            ),
            "",
        )
        _add_check(
            rows,
            "NO_HISTORICAL_INGESTION_TIME",
            all(row.get("ingestion_time_known") is False for row in response_records),
            "",
        )
        return [row for row in rows if row["status"] != "PASS"]

    def _write_outputs(
        self,
        *,
        all_source_assets: list[dict[str, Any]],
        normalized_manifest_rows: list[dict[str, Any]],
        all_phase_intervals: list[dict[str, Any]],
        all_episodes: list[dict[str, Any]],
        all_footprints: list[dict[str, Any]],
        all_responses: list[dict[str, Any]],
        all_scope_refs: list[dict[str, Any]],
        input_audit_rows: list[dict[str, Any]],
        all_channel_rows: list[dict[str, Any]],
        quality_rows: list[dict[str, Any]],
        episode_daily_rows: list[dict[str, Any]],
        episode_integrity: list[dict[str, Any]],
        cross_file_rows: list[dict[str, Any]],
        footprint_audit_rows: list[dict[str, Any]],
        response_audit_rows: list[dict[str, Any]],
        scope_audit_rows: list[dict[str, Any]],
        provenance_rows: list[dict[str, Any]],
        regression_rows: list[dict[str, Any]],
        chainage_observation_rows: list[dict[str, Any]],
        chainage_episode_rows: list[dict[str, Any]],
        chainage_daily_rows: list[dict[str, Any]],
        plc_daily_scope_v2_rows: list[dict[str, Any]],
        hard_check_rows: list[dict[str, Any]],
        pre_protected: list[dict[str, Any]],
        date_results: list[DateBuildResult],
    ) -> None:
        write_jsonl(self.out / "source_assets.jsonl", all_source_assets)
        write_jsonl(self.out / "phase_intervals.jsonl", all_phase_intervals)
        write_jsonl(self.out / "excavation_episodes.jsonl", all_episodes)
        write_jsonl(self.out / "spatial_footprints.jsonl", all_footprints)
        write_jsonl(self.out / "response_evidence.jsonl", all_responses)
        write_jsonl(self.out / "plc_daily_scope_reference.jsonl", all_scope_refs)
        write_csv(
            self.out / "normalized_observation_manifest.csv",
            normalized_manifest_rows,
            _NORMALIZED_MANIFEST_FIELDS,
        )
        write_csv(self.out / "plc_input_asset_audit.csv", input_audit_rows, _INPUT_AUDIT_FIELDS)
        write_csv(self.out / "channel_mapping_audit.csv", all_channel_rows, _CHANNEL_AUDIT_FIELDS)
        write_csv(self.out / "plc_quality_daily_audit.csv", quality_rows, _QUALITY_FIELDS)
        write_csv(self.out / "episode_daily_summary.csv", episode_daily_rows, _EPISODE_DAILY_FIELDS)
        write_csv(self.out / "episode_integrity_audit.csv", episode_integrity, _INTEGRITY_FIELDS)
        write_csv(
            self.out / "cross_file_episode_candidate_audit.csv", cross_file_rows, _CROSS_FILE_FIELDS
        )
        write_csv(
            self.out / "spatial_footprint_audit.csv", footprint_audit_rows, _FOOTPRINT_AUDIT_FIELDS
        )
        write_csv(
            self.out / "response_evidence_audit.csv", response_audit_rows, _RESPONSE_AUDIT_FIELDS
        )
        write_csv(
            self.out / "plc_applicability_scope_consistency_audit.csv",
            scope_audit_rows,
            _SCOPE_AUDIT_FIELDS,
        )
        write_csv(self.out / "provenance_reference_audit.csv", provenance_rows, _PROVENANCE_FIELDS)
        write_csv(
            self.out / "stage1_three_day_regression_audit.csv", regression_rows, _REGRESSION_FIELDS
        )
        write_jsonl(self.out / "plc_daily_scope_v2.jsonl", plc_daily_scope_v2_rows)
        write_csv(
            self.out / "chainage_regime_observation_audit.csv",
            chainage_observation_rows,
            _CHAINAGE_OBSERVATION_FIELDS,
        )
        write_csv(
            self.out / "chainage_regime_episode_audit.csv",
            chainage_episode_rows,
            _CHAINAGE_EPISODE_FIELDS,
        )
        write_csv(
            self.out / "chainage_regime_daily_audit.csv",
            chainage_daily_rows,
            _CHAINAGE_DAILY_FIELDS,
        )
        write_csv(
            self.out / "plc_daily_scope_quality_audit.csv",
            plc_daily_scope_v2_rows,
            _PLC_DAILY_SCOPE_V2_FIELDS,
        )
        write_csv(
            self.out / "operational_freeze_hard_check.csv", hard_check_rows, _HARD_CHECK_FIELDS
        )
        write_csv(self.out / "protected_hash_audit.csv", pre_protected, _PROTECTED_HASH_FIELDS)
        write_json(
            self.out / "schema_manifest.json",
            {
                "schema_version": "stage2e_operational_freeze.v1",
                "objects": {
                    "source_assets": "SourceAsset plus offline reconstruction metadata",
                    "phase_intervals": "PhaseInterval plus deterministic phase_interval_id",
                    "excavation_episodes": "ExcavationEpisode, PLC_INFERRED only",
                    "spatial_footprints": "SpatialFootprint, shield_head_chainage primary anchor",
                    "response_evidence": "ResponseEvidence with baseline/deviation null",
                },
            },
        )
        write_json(
            self.out / "document_parse_outcomes.json",
            {
                "note": (
                    "Not applicable; Stage 2E parses PLC CSV operational data, not PDF documents."
                ),
                "date_results": [result.model_dump(mode="json") for result in date_results],
            },
        )

    def _write_protected_hash_audit(self, rows: list[dict[str, Any]]) -> None:
        write_csv(self.out / "protected_hash_audit.csv", rows, _PROTECTED_HASH_FIELDS)

    def _write_final_manifests(
        self,
        *,
        target_dates: TargetDateSet,
        date_results: list[DateBuildResult],
        source_assets: list[dict[str, Any]],
        phase_intervals: list[dict[str, Any]],
        episodes: list[dict[str, Any]],
        footprints: list[dict[str, Any]],
        responses: list[dict[str, Any]],
        scope_audit_rows: list[dict[str, Any]],
        cross_file_rows: list[dict[str, Any]],
        hard_check_rows: list[dict[str, Any]],
        protected_rows: list[dict[str, Any]],
        provenance_rows: list[dict[str, Any]],
        chainage_episode_rows: list[dict[str, Any]],
    ) -> dict[str, str]:
        source_asset_manifest_hash = _json_rows_hash(source_assets)
        snapshot_sha, source_tree_hash = _write_source_snapshot(
            repo=self.repo,
            output_dir=self.out,
            archive_name="stage2e_source_snapshot.tar.gz",
            hashes_name="stage2e_source_hashes.sha256",
            include_paths=[
                "src/tbm_twin/operational_freeze",
                "src/tbm_twin/evidence/response_builder.py",
                "scripts/build_stage2e_plc_operational_freeze.py",
                "configs/plc_channels.yaml",
                "configs/episode_detection.yaml",
                "configs/response_evidence.yaml",
                "tests/unit/test_chainage_regime.py",
                "tests/unit/test_operational_freeze_ids.py",
                "tests/unit/test_operational_freeze_models.py",
                "tests/unit/test_operational_provenance.py",
                "tests/unit/test_response_no_baseline.py",
                "tests/unit/test_response_reconstruction_time.py",
                "tests/integration/test_stage2e_operational_freeze_fixture.py",
                "pyproject.toml",
            ],
        )
        method = {
            "method_name": STAGE2E_METHOD_NAME,
            "method_version": STAGE2E_METHOD_VERSION,
            "generated_at": self.config.reconstruction_time,
            "git_commit_hash": _git_value(self.repo, ["rev-parse", "--short", "HEAD"]),
            "working_tree_dirty": bool(_git_value(self.repo, ["status", "--short"])),
            "source_date_count": len(target_dates.dates),
            "source_asset_manifest_hash": source_asset_manifest_hash,
            "channel_catalog_hash": sha256_file(
                self.config.resolve(self.config.channel_catalog_path)
            ),
            "episode_config_hash": sha256_file(
                self.config.resolve(self.config.episode_config_path)
            ),
            "response_config_hash": sha256_file(
                self.config.resolve(self.config.response_config_path)
            ),
            "geology_freeze_manifest_hash": sha256_file(self.geology_dir / "freeze_manifest.json"),
            "applicability_manifest_or_file_hash": sha256_file(
                self.applicability_dir / "method_version.json"
            ),
            "baseline_mode": BaselineMethod.NO_BASELINE.value,
            "historical_ingestion_time_available": False,
            "reconstruction_time_basis": "explicit_builder_parameter",
            "source_snapshot_sha256": snapshot_sha,
            "parser_source_tree_hash": source_tree_hash,
        }
        write_json(self.out / "method_version.json", method)
        file_hashes_before_manifest = hash_directory_files(self.out)
        summary = self._summary(
            target_dates=target_dates,
            date_results=date_results,
            source_assets=source_assets,
            phase_intervals=phase_intervals,
            episodes=episodes,
            footprints=footprints,
            responses=responses,
            scope_audit_rows=scope_audit_rows,
            cross_file_rows=cross_file_rows,
            hard_check_rows=hard_check_rows,
            protected_rows=protected_rows,
            output_hashes=file_hashes_before_manifest,
            provenance_rows=provenance_rows,
            chainage_episode_rows=chainage_episode_rows,
            source_snapshot_sha256=snapshot_sha,
            parser_source_tree_hash=source_tree_hash,
        )
        write_json(self.out / "freeze_manifest.json", summary)
        self._write_freeze_report(summary)
        return write_file_hashes(self.out)

    def _summary(
        self,
        *,
        target_dates: TargetDateSet,
        date_results: list[DateBuildResult],
        source_assets: list[dict[str, Any]],
        phase_intervals: list[dict[str, Any]],
        episodes: list[dict[str, Any]],
        footprints: list[dict[str, Any]],
        responses: list[dict[str, Any]],
        scope_audit_rows: list[dict[str, Any]],
        cross_file_rows: list[dict[str, Any]],
        hard_check_rows: list[dict[str, Any]],
        protected_rows: list[dict[str, Any]],
        output_hashes: dict[str, str],
        provenance_rows: list[dict[str, Any]],
        chainage_episode_rows: list[dict[str, Any]],
        source_snapshot_sha256: str,
        parser_source_tree_hash: str,
    ) -> dict[str, Any]:
        phase_counts = Counter(str(row["phase"]) for row in phase_intervals)
        boundary_counts = Counter(str(row["boundary_status"]) for row in episodes)
        episode_quality = Counter(str(row["quality_grade"]) for row in episodes)
        footprint_status = Counter(str(row["consistency_status"]) for row in footprints)
        response_channels = Counter(str(row["channel_name"]) for row in responses)
        response_quality = Counter(str(row["quality_grade"]) for row in responses)
        chainage_status = Counter(str(row["final_spatial_status"]) for row in chainage_episode_rows)
        trusted_unavailable = sum(
            row.get("spatial_scope_usable") is False for row in chainage_episode_rows
        )
        provenance_valid = sum(row["status"] == "VALID" for row in provenance_rows)
        return {
            "method_name": STAGE2E_METHOD_NAME,
            "method_version": STAGE2E_METHOD_VERSION,
            "generated_at": self.config.reconstruction_time,
            "target_date_count": len(target_dates.dates),
            "first_target_date": target_dates.dates[0],
            "last_target_date": target_dates.dates[-1],
            "source_asset_count": len(source_assets),
            "normalized_observation_count": sum(r.normalized_row_count for r in date_results),
            "normalized_observation_total_count": sum(r.normalized_row_count for r in date_results),
            "phase_interval_count": len(phase_intervals),
            "phase_distribution": dict(sorted(phase_counts.items())),
            "episode_count": len(episodes),
            "episode_daily_distribution": {
                r.target_date.isoformat(): r.episode_count for r in date_results
            },
            "boundary_status_distribution": dict(sorted(boundary_counts.items())),
            "episode_quality_distribution": dict(sorted(episode_quality.items())),
            "zero_advance_episode_count": sum(
                "ZERO_ADVANCE_DURING_EXCAVATION" in row.get("quality_flags", []) for row in episodes
            ),
            "cross_file_continuation_candidate_count": len(cross_file_rows),
            "footprint_count": len(footprints),
            "footprint_consistency_distribution": dict(sorted(footprint_status.items())),
            "trusted_spatial_scope_usable_episode_count": len(chainage_episode_rows)
            - trusted_unavailable,
            "trusted_spatial_scope_unavailable_episode_count": trusted_unavailable,
            "chainage_regime_episode_distribution": dict(sorted(chainage_status.items())),
            "trusted_original_regime_episode_count": chainage_status["TRUSTED"],
            "restored_regime_episode_count": chainage_status["RESTORED"],
            "suspect_jump_episode_count": chainage_status["SUSPECT_JUMP"],
            "suspect_shifted_regime_episode_count": chainage_status["SUSPECT_SHIFTED_REGIME"],
            "unresolved_episode_count": chainage_status["UNRESOLVED"],
            "spatially_unusable_episode_count": trusted_unavailable,
            "response_evidence_count": len(responses),
            "response_channel_distribution": dict(sorted(response_channels.items())),
            "response_quality_distribution": dict(sorted(response_quality.items())),
            "scope_exact_match_count": sum(
                row["exact_match"] == "True" for row in scope_audit_rows
            ),
            "core_derived_object_count": len(episodes) + len(footprints) + len(responses),
            "provenance_reference_total": len(provenance_rows),
            "provenance_reference_valid": provenance_valid,
            "provenance_reference_invalid": len(provenance_rows) - provenance_valid,
            "provenance_complete": len(provenance_rows) == provenance_valid,
            "future_baseline_leakage_present": False,
            "baseline_mode": BaselineMethod.NO_BASELINE.value,
            "historical_ingestion_time_fabricated": False,
            "reconstruction_time_is_historical_ingestion_time": False,
            "hard_check_issue_count": len(hard_check_rows),
            "source_snapshot_sha256": source_snapshot_sha256,
            "parser_source_tree_hash": parser_source_tree_hash,
            "protected_hash_unchanged": all(row["unchanged"] for row in protected_rows),
            "formal_builder_entrypoint": (
                "tbm_twin.operational_freeze.OperationalFreezeBuilder.build"
            ),
            "current_git_commit": _git_value(self.repo, ["rev-parse", "--short", "HEAD"]),
            "working_tree_dirty": bool(_git_value(self.repo, ["status", "--short"])),
            "python_version": sys.version,
            "dependency_versions": _dependency_versions(),
            "input_source_asset_hashes": {
                str(row["target_date"]): row["content_hash"] for row in source_assets
            },
            "output_file_hashes": output_hashes,
            "stage3_readiness_candidate": len(hard_check_rows) == 0,
            "stage3_not_run": True,
        }

    def _write_freeze_report(self, summary: dict[str, Any]) -> None:
        lines = [
            "# Stage 2E PLC Operational Evidence Freeze",
            "",
            "This is not Stage 3 and does not construct 10m ConstructionStateVersion cells.",
            "",
            f"- processed PLC dates: {summary['target_date_count']}",
            f"- raw PLC SourceAssets: {summary['source_asset_count']}",
            f"- normalized observations: {summary['normalized_observation_count']}",
            f"- PhaseIntervals: {summary['phase_interval_count']}",
            f"- phase distribution: {summary['phase_distribution']}",
            f"- Episodes: {summary['episode_count']}",
            f"- boundary status distribution: {summary['boundary_status_distribution']}",
            f"- Episode quality distribution: {summary['episode_quality_distribution']}",
            f"- 0m Episodes: {summary['zero_advance_episode_count']}",
            "- cross-file continuation candidates: "
            f"{summary['cross_file_continuation_candidate_count']}",
            f"- Footprints: {summary['footprint_count']}",
            "- Footprint consistency distribution: "
            f"{summary['footprint_consistency_distribution']}",
            "- trusted spatial usable Episodes: "
            f"{summary['trusted_spatial_scope_usable_episode_count']}",
            "- trusted spatial unavailable Episodes: "
            f"{summary['trusted_spatial_scope_unavailable_episode_count']}",
            "- chainage regime Episode distribution: "
            f"{summary['chainage_regime_episode_distribution']}",
            "- trusted original regime Episodes: "
            f"{summary['trusted_original_regime_episode_count']}",
            f"- restored regime Episodes: {summary['restored_regime_episode_count']}",
            f"- suspect jump Episodes: {summary['suspect_jump_episode_count']}",
            f"- suspect shifted regime Episodes: {summary['suspect_shifted_regime_episode_count']}",
            f"- unresolved Episodes: {summary['unresolved_episode_count']}",
            f"- spatially unusable Episodes: {summary['spatially_unusable_episode_count']}",
            f"- ResponseEvidence: {summary['response_evidence_count']}",
            f"- ResponseEvidence channel distribution: {summary['response_channel_distribution']}",
            f"- ResponseEvidence quality distribution: {summary['response_quality_distribution']}",
            "- old Applicability V2 raw PLC scope reproduction: "
            f"{summary['scope_exact_match_count']}/91",
            f"- core derived object count: {summary['core_derived_object_count']}",
            f"- provenance reference total: {summary['provenance_reference_total']}",
            f"- provenance reference valid: {summary['provenance_reference_valid']}",
            f"- provenance reference invalid: {summary['provenance_reference_invalid']}",
            f"- provenance complete: {summary['provenance_complete']}",
            f"- baseline mode: {summary['baseline_mode']}",
            f"- future baseline leakage present: {summary['future_baseline_leakage_present']}",
            "- historical ingestion time fabricated: "
            f"{summary['historical_ingestion_time_fabricated']}",
            f"- protected hash unchanged: {summary['protected_hash_unchanged']}",
            f"- hard check issue count: {summary['hard_check_issue_count']}",
            f"- source snapshot SHA256: {summary['source_snapshot_sha256']}",
            "",
            "ResponseEvidence is operational/mechanical evidence only; "
            "it is not a geological cause.",
            "Episode records are PLC_INFERRED and are not claimed as construction log truth.",
        ]
        (self.out / "freeze_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _env_plc_data_dir() -> Path | None:
    raw = os.environ.get("PLC_DATA_DIR")
    return Path(raw) if raw else None


def _count_csv_data_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def _min_max_chainage(frame: pd.DataFrame) -> tuple[float | None, float | None]:
    series = pd.to_numeric(frame["shield_head_chainage"], errors="coerce")
    if not series.notna().any():
        return None, None
    return _safe_float(series.min()), _safe_float(series.max())


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _diff(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(left - right, 6)


def _ceil_to_cell(value: float, cell_size: float) -> float:
    return math.ceil(value / cell_size) * cell_size


def _scope(kind: str, start: float, end: float, basis: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "start_chainage": round(float(start), 3),
        "end_chainage": round(float(end), 3),
        "basis": basis,
    }


def _chainage_scope(start: float, end: float, basis: str) -> dict[str, Any]:
    kind = "POINT" if start == end else "INTERVAL"
    return _scope(kind, start, end, basis)


def _evidence_spatial_scope(scope: dict[str, Any] | None) -> dict[str, object] | None:
    if scope is None:
        return None
    return {
        "start_chainage": scope.get("start_chainage"),
        "end_chainage": scope.get("end_chainage"),
        "basis": scope.get("basis", "trusted_episode_core_chainage_scope"),
    }


def _final_spatial_status(statuses: list[str], spatial_usable: bool) -> tuple[str, list[str]]:
    if spatial_usable and statuses == ["TRUSTED"]:
        return "TRUSTED", []
    if spatial_usable and statuses == ["RESTORED"]:
        return "RESTORED", ["CHAINAGE_REGIME_RESTORED"]
    if "SUSPECT_JUMP" in statuses:
        return "SUSPECT_JUMP", ["CHAINAGE_REGIME_JUMP"]
    if "SUSPECT_SHIFTED_REGIME" in statuses:
        return "SUSPECT_SHIFTED_REGIME", ["SUSPECT_SHIFTED_REGIME_PENDING_REVIEW"]
    if "UNRESOLVED" in statuses:
        return "UNRESOLVED", ["CHAINAGE_REGIME_UNRESOLVED"]
    return "UNRESOLVED", ["NO_USABLE_CHAINAGE_REGIME"]


def _reference_row(
    target_date: date,
    object_type: str,
    object_id: str,
    reference_field: str,
    referenced_id: str,
    valid: bool,
) -> dict[str, Any]:
    return {
        "target_date": target_date,
        "object_type": object_type,
        "object_id": object_id,
        "reference_field": reference_field,
        "referenced_id": referenced_id,
        "status": "VALID" if valid else "INVALID",
        "reason_codes": [] if valid else ["MISSING_REFERENCED_OBJECT"],
    }


def _response_core_refs_match_episode(
    responses: list[Any],
    episodes: list[ExcavationEpisode],
) -> bool:
    refs_by_episode = {episode.episode_id: episode.core_observation_refs for episode in episodes}
    return all(
        response.core_observation_refs == refs_by_episode.get(response.episode_id, [])
        for response in responses
    )


def _response_statistic_hash(rows: list[dict[str, Any]]) -> str:
    payload = [
        {
            "evidence_id": row["evidence_id"],
            "episode_id": row["episode_id"],
            "channel_name": row["channel_name"],
            "statistics": row["statistics"],
            "core_observation_refs": row["core_observation_refs"],
        }
        for row in sorted(rows, key=lambda item: str(item["evidence_id"]))
    ]
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def _json_rows_hash(rows: list[dict[str, Any]]) -> str:
    return sha256_text(json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str))


def _git_value(repo: Path, args: list[str]) -> str:
    import subprocess

    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)
    return result.stdout.strip()


def _dependency_versions() -> dict[str, str]:
    packages = ["pandas", "pydantic", "pyarrow", "PyYAML"]
    versions: dict[str, str] = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "NOT_INSTALLED"
    return versions


def _write_source_snapshot(
    *,
    repo: Path,
    output_dir: Path,
    archive_name: str,
    hashes_name: str,
    include_paths: list[str],
) -> tuple[str, str]:
    rel_files = _collect_source_snapshot_files(repo, include_paths)
    hashes = {rel: sha256_file(repo / rel) for rel in rel_files}
    hashes_content = "".join(f"{digest}  {rel}\n" for rel, digest in sorted(hashes.items()))
    hashes_path = output_dir / hashes_name
    hashes_path.write_text(hashes_content, encoding="utf-8")
    archive_path = output_dir / archive_name
    with (
        archive_path.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w") as tar,
    ):
        for rel in rel_files:
            path = repo / rel
            info = tar.gettarinfo(path, arcname=rel)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            with path.open("rb") as handle:
                tar.addfile(info, handle)
    return sha256_file(archive_path), sha256_text(hashes_content)


def _collect_source_snapshot_files(repo: Path, include_paths: list[str]) -> list[str]:
    paths = list(include_paths)
    paths.extend(
        rel
        for rel in ["uv.lock", "poetry.lock", "requirements.txt", "requirements-dev.txt"]
        if (repo / rel).exists()
    )
    files: set[str] = set()
    for rel in paths:
        path = repo / rel
        if not path.exists():
            continue
        if path.is_file():
            files.add(rel)
            continue
        for child in path.rglob("*"):
            if child.is_file() and "__pycache__" not in child.parts:
                files.add(child.relative_to(repo).as_posix())
    return sorted(files)


def _add_check(rows: list[dict[str, Any]], check_name: str, passed: bool, details: str) -> None:
    rows.append(
        {
            "check_name": check_name,
            "status": "PASS" if passed else "FAIL",
            "details": details,
        }
    )


_NORMALIZED_MANIFEST_FIELDS = [
    "target_date",
    "source_asset_id",
    "normalized_path",
    "row_count",
    "valid_timestamp_count",
    "valid_chainage_count",
    "first_timestamp",
    "last_timestamp",
    "minimum_chainage",
    "maximum_chainage",
    "normalized_sha256",
    "normalization_method_version",
]
_INPUT_AUDIT_FIELDS = [
    "target_date",
    "raw_filename",
    "resolved_local_path",
    "file_exists",
    "file_size",
    "sha256",
    "encoding",
    "row_count",
    "column_count",
    "source_asset_id",
    "status",
    "warning_codes",
]
_CHANNEL_AUDIT_FIELDS = [
    "target_date",
    "canonical_name",
    "matched_raw_column",
    "match_method",
    "candidate_raw_columns",
    "selection_reason",
    "required",
    "usage_level",
    "unit",
    "unit_verified",
    "dtype",
    "non_null_count",
    "missing_rate",
    "numeric_min",
    "numeric_max",
    "unique_count",
    "warnings",
    "nearby_non_anchor_chainage_columns",
]
_QUALITY_FIELDS = [
    "target_date",
    "asset_id",
    "row_count_raw",
    "row_count_normalized",
    "quality_grade",
    "reason_codes",
    "warnings",
    "timestamp_parse_failed_count",
    "large_gap_count",
    "shield_head_chainage_missing_count",
    "chainage_reverse_count",
    "chainage_large_jump_count",
    "channel_missing_rates",
]
_EPISODE_DAILY_FIELDS = [
    "target_date",
    "episode_count",
    "total_core_duration_seconds",
    "boundary_status_distribution",
    "quality_grade_distribution",
    "zero_advance_episode_count",
    "episode_ids",
]
_INTEGRITY_FIELDS = ["target_date", "episode_id", "issue_code", "details"]
_CROSS_FILE_FIELDS = [
    "left_date",
    "right_date",
    "left_episode_id",
    "right_episode_id",
    "time_gap_seconds",
    "chainage_gap_m",
    "left_boundary_status",
    "right_boundary_status",
    "left_chainage_regime_status",
    "right_chainage_regime_status",
    "classification",
    "possible_continuation",
    "decision",
]
_FOOTPRINT_AUDIT_FIELDS = [
    "target_date",
    "footprint_id",
    "episode_id",
    "start_chainage",
    "end_chainage",
    "estimated_advance_m",
    "consistency_status",
    "quality_grade",
    "quality_flags",
    "supporting_channel_names",
    "independent_source_count",
    "raw_spatial_scope",
    "trusted_spatial_scope",
    "spatial_scope_usable",
    "chainage_regime_status",
    "chainage_regime_reason_codes",
]
_RESPONSE_AUDIT_FIELDS = [
    "target_date",
    "evidence_id",
    "episode_id",
    "channel_name",
    "sample_count",
    "valid_count",
    "missing_rate",
    "mean",
    "median",
    "standard_deviation",
    "p10",
    "p90",
    "minimum",
    "maximum",
    "coefficient_of_variation",
    "quality_grade",
    "measurement_quality",
    "temporal_scope_quality",
    "spatial_scope_quality",
    "quality_flags",
    "unit_confidence",
    "baseline_id",
    "baseline_value",
    "deviation_direction",
    "deviation_strength",
    "baseline_method",
    "available_time_basis",
    "historical_ingestion_time_known",
]
_SCOPE_AUDIT_FIELDS = [
    "target_date",
    "raw_min_chainage",
    "raw_max_chainage",
    "applicability_daily_start",
    "applicability_daily_end",
    "start_difference_m",
    "end_difference_m",
    "exact_match",
    "status",
    "reason_codes",
]
_PROVENANCE_FIELDS = [
    "target_date",
    "object_type",
    "object_id",
    "reference_field",
    "referenced_id",
    "status",
    "reason_codes",
]
_REGRESSION_FIELDS = ["target_date", "check_name", "status", "details"]
_HARD_CHECK_FIELDS = ["check_name", "status", "details"]
_PROTECTED_HASH_FIELDS = [
    "phase",
    "protected_dir",
    "path",
    "expected_sha256",
    "actual_sha256",
    "unchanged",
    "reason",
]
_CHAINAGE_OBSERVATION_FIELDS = [
    "target_date",
    "timestamp",
    "observation_id",
    "raw_shield_head_chainage",
    "previous_raw_chainage",
    "delta_m",
    "regime_id",
    "regime_status",
    "spatially_usable",
    "reason_codes",
]
_CHAINAGE_EPISODE_FIELDS = [
    "target_date",
    "episode_id",
    "raw_start_chainage",
    "raw_end_chainage",
    "trusted_start_chainage",
    "trusted_end_chainage",
    "regime_ids",
    "regime_status",
    "spatial_scope_usable",
    "existing_footprint_status",
    "final_spatial_status",
    "reason_codes",
]
_CHAINAGE_DAILY_FIELDS = [
    "target_date",
    "raw_daily_plc_range",
    "trusted_daily_plc_range",
    "spatial_scope_status",
    "regime_statuses",
    "usable_observation_count",
    "unusable_observation_count",
]
_PLC_DAILY_SCOPE_V2_FIELDS = [
    "daily_scope_reference_id",
    "target_date",
    "raw_daily_plc_range",
    "trusted_daily_plc_range",
    "daily_plc_range",
    "daily_excavated_scope",
    "forward_scope",
    "local_background_scope",
    "current_chainage",
    "spatial_scope_status",
    "regime_statuses",
    "old_applicability_daily_plc_range",
    "method_version",
]
