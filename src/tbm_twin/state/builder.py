"""Builder for Stage 3A initial daily construction state snapshots."""

from __future__ import annotations

import gzip
import re
import shutil
import tarfile
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from tbm_twin.state.grid import generate_cells_for_scopes, split_scope_to_cells
from tbm_twin.state.io import (
    read_json,
    read_jsonl,
    sha256_file,
    stable_id,
    verify_hash_manifest,
    write_csv,
    write_file_hashes,
    write_json,
    write_jsonl,
)
from tbm_twin.state.linking import (
    ResponseCellPiece,
    map_trusted_point_response_to_cell,
    split_assignment_to_role_cells,
    split_trusted_response_to_daily_cells,
)
from tbm_twin.state.models import (
    CellScopeRole,
    ConstructionStateConfig,
    DailyConstructionState,
    InitialConstructionStateVersion,
    Stage3AStateConfig,
    StateGeologicalEvidenceLink,
    StateResponseEvidenceLink,
)
from tbm_twin.state.validation import count_by, duplicate_ids, hard_check_rows

_AUDIT_FIELDNAMES: dict[str, list[str]] = {
    "stage3a_hard_check.csv": ["check_name", "status", "details"],
    "stage3a_v1_1_promotion_audit.csv": [
        "audit_type",
        "object_key",
        "field_name",
        "candidate_value",
        "formal_value",
        "status",
        "details",
    ],
    "stage3a_version_identity_audit.csv": [
        "metric",
        "value",
        "status",
        "details",
    ],
    "formal_stage3a_path_audit.csv": [
        "path",
        "reference",
        "status",
        "details",
    ],
}

_FORMAL_STAGE3A_DIR = Path("artifacts/stage3a_initial_epistemic_state_v1_1")
_CANDIDATE_STAGE3A_DIR = Path("artifacts/stage3a_initial_epistemic_state_v1_1_candidate")
_OLD_STAGE3A_DIR = Path("artifacts/stage3a_initial_epistemic_state_v1")
_FORMAL_METHOD_VERSION = "stage3a_initial_epistemic_state_v1_1_point_response_complete"


class Stage3AStateBuilder:
    """Build Stage 3A state artifacts from formal Stage 2 frozen inputs."""

    def __init__(self, config: Stage3AStateConfig) -> None:
        self.config = config
        self.repo = config.repo_root
        self.out = config.output_dir
        self.geology_dir = config.resolve(config.geology_freeze_dir)
        self.applicability_dir = config.resolve(config.applicability_dir)
        self.operational_dir = config.resolve(config.operational_freeze_dir)
        self.state_config = self._load_state_config()

    def build(self) -> dict[str, Any]:
        """Build all Stage 3A outputs."""

        self._prepare_output_dir()
        protected_hash_rows = self._verify_inputs()
        source_hashes = self._source_hashes()
        data = self._load_inputs()
        self._assert_formal_inputs(data)

        cells = generate_cells_for_scopes(
            self._trusted_scope_union(data["daily_scopes"]),
            self.state_config,
        )
        cells_by_index = {cell.cell_index: cell for cell in cells}
        cells_by_id = {cell.cell_id: cell for cell in cells}

        daily_states: list[dict[str, Any]] = []
        versions: list[dict[str, Any]] = []
        geo_links: list[dict[str, Any]] = []
        response_links: list[dict[str, Any]] = []
        assertion_links: list[dict[str, Any]] = []
        unlocated_clauses: list[dict[str, Any]] = []
        unlocated_operational: list[dict[str, Any]] = []
        daily_located_point_operational: list[dict[str, Any]] = []

        cell_grid_audit = self._cell_grid_audit(cells)
        daily_state_audit: list[dict[str, Any]] = []
        cell_scope_role_audit: list[dict[str, Any]] = []
        episode_daily_link_audit: list[dict[str, Any]] = []
        response_cell_link_audit: list[dict[str, Any]] = []
        response_state_coverage_audit: list[dict[str, Any]] = []
        response_multicell_link_audit: list[dict[str, Any]] = []
        geological_assignment_cell_link_audit: list[dict[str, Any]] = []
        point_boundary_policy_audit: list[dict[str, Any]] = []
        interval_overlap_conservation_audit: list[dict[str, Any]] = []
        state_epistemic_integrity_audit: list[dict[str, Any]] = []
        fixed_state_case_audit: list[dict[str, Any]] = []

        version_accumulators: dict[str, dict[str, set[str]]] = {}
        versions_by_date_cell: dict[tuple[str, str], dict[str, Any]] = {}

        for daily_scope in data["daily_scopes"]:
            target_date = str(daily_scope["target_date"])
            daily_state = self._daily_state(
                daily_scope,
                data=data,
                source_hashes=source_hashes,
            )
            daily_states.append(daily_state)
            daily_state_audit.append(self._daily_state_audit_row(daily_state))
            episode_daily_link_audit.extend(
                self._episode_daily_audit_rows(
                    daily_state,
                    data["episodes_by_date"].get(target_date, []),
                )
            )
            unlocated_clauses.extend(
                self._unlocated_clause_rows(
                    daily_state,
                    data["clause_assignments_by_date"].get(target_date, []),
                    source_hashes,
                )
            )
            if daily_scope["spatial_scope_status"] == "UNAVAILABLE":
                unavailable_responses = data["responses_by_date"].get(target_date, [])
                unlocated_operational.extend(
                    self._unlocated_operational_rows(
                        daily_state,
                        unavailable_responses,
                        data["footprint_by_episode"],
                        source_hashes,
                    )
                )
                response_state_coverage_audit.extend(
                    self._unlocated_response_coverage_rows(unavailable_responses)
                )
                continue

            cell_roles = self._cell_roles_for_day(
                daily_scope,
                cells_by_index,
                conflict_rows=cell_scope_role_audit,
            )
            cell_scope_role_audit.extend(
                self._cell_scope_role_rows(
                    target_date,
                    daily_state["daily_state_id"],
                    cell_roles,
                    cells_by_id,
                )
            )
            for cell_id, role in sorted(cell_roles.items()):
                version = self._initial_version(
                    daily_state,
                    cells_by_id[cell_id],
                    role,
                    source_hashes,
                )
                versions.append(version)
                versions_by_date_cell[(target_date, cell_id)] = version
                version_accumulators[version["state_version_id"]] = (
                    self._empty_version_accumulator()
                )

            response_links.extend(
                self._response_links_for_day(
                    daily_state=daily_state,
                    responses=data["responses_by_date"].get(target_date, []),
                    footprint_by_episode=data["footprint_by_episode"],
                    cell_roles=cell_roles,
                    cells_by_index=cells_by_index,
                    versions_by_date_cell=versions_by_date_cell,
                    accumulators=version_accumulators,
                    audit_rows=response_cell_link_audit,
                    unlocated_rows=unlocated_operational,
                    daily_located_point_rows=daily_located_point_operational,
                    coverage_rows=response_state_coverage_audit,
                    multicell_rows=response_multicell_link_audit,
                    source_hashes=source_hashes,
                )
            )
            geo_links.extend(
                self._geological_links_for_day(
                    daily_state=daily_state,
                    assignments=data["primary_assignments_by_date"].get(target_date, []),
                    cell_roles=cell_roles,
                    cells_by_index=cells_by_index,
                    versions_by_date_cell=versions_by_date_cell,
                    accumulators=version_accumulators,
                    audit_rows=geological_assignment_cell_link_audit,
                    point_audit_rows=point_boundary_policy_audit,
                    interval_audit_rows=interval_overlap_conservation_audit,
                    epistemic_audit_rows=state_epistemic_integrity_audit,
                    source_hashes=source_hashes,
                )
            )
            assertion_links.extend(
                self._assertion_trace_links_for_day(
                    daily_state=daily_state,
                    assignments=data["assertion_assignments_by_date"].get(target_date, []),
                    cell_roles=cell_roles,
                    cells_by_index=cells_by_index,
                    versions_by_date_cell=versions_by_date_cell,
                    source_hashes=source_hashes,
                )
            )
        versions = self._finalize_versions(versions, version_accumulators)
        state_reference_integrity_audit = self._reference_integrity_audit(
            cells=cells,
            daily_states=daily_states,
            versions=versions,
            geo_links=geo_links,
            response_links=response_links,
            assertion_links=assertion_links,
            data=data,
        )
        fixed_state_case_audit.extend(
            self._fixed_case_audit(
                data,
                daily_states,
                versions,
                geo_links,
                response_links,
                unlocated_operational,
                daily_located_point_operational,
            )
        )
        hard_checks = self._hard_checks(
            data=data,
            cells=cells,
            daily_states=daily_states,
            versions=versions,
            geo_links=geo_links,
            response_links=response_links,
            assertion_links=assertion_links,
            unlocated_clauses=unlocated_clauses,
            unlocated_operational=unlocated_operational,
            daily_located_point_operational=daily_located_point_operational,
            state_reference_integrity_audit=state_reference_integrity_audit,
            protected_hash_rows=protected_hash_rows,
            response_state_coverage_audit=response_state_coverage_audit,
            cell_scope_role_audit=cell_scope_role_audit,
            point_boundary_policy_audit=point_boundary_policy_audit,
            interval_overlap_conservation_audit=interval_overlap_conservation_audit,
            state_epistemic_integrity_audit=state_epistemic_integrity_audit,
        )

        self._write_outputs(
            cells=[cell.model_dump(mode="json") for cell in cells],
            daily_states=daily_states,
            versions=versions,
            geo_links=geo_links,
            response_links=response_links,
            assertion_links=assertion_links,
            unlocated_clauses=unlocated_clauses,
            unlocated_operational=unlocated_operational,
            daily_located_point_operational=daily_located_point_operational,
            audits={
                "cell_grid_audit.csv": cell_grid_audit,
                "daily_state_audit.csv": daily_state_audit,
                "cell_scope_role_audit.csv": cell_scope_role_audit,
                "episode_daily_link_audit.csv": episode_daily_link_audit,
                "response_cell_link_audit.csv": response_cell_link_audit,
                "response_state_coverage_audit.csv": response_state_coverage_audit,
                "response_multicell_link_audit.csv": response_multicell_link_audit,
                "geological_assignment_cell_link_audit.csv": geological_assignment_cell_link_audit,
                "point_boundary_policy_audit.csv": point_boundary_policy_audit,
                "interval_overlap_conservation_audit.csv": interval_overlap_conservation_audit,
                "state_epistemic_integrity_audit.csv": state_epistemic_integrity_audit,
                "state_reference_integrity_audit.csv": state_reference_integrity_audit,
                "fixed_state_case_audit.csv": fixed_state_case_audit,
                "stage3a_hard_check.csv": hard_checks,
            },
            data=data,
            source_hashes=source_hashes,
            protected_hash_rows=protected_hash_rows,
            hard_checks=hard_checks,
        )
        if hard_checks:
            msg = f"Stage 3A hard checks failed: {len(hard_checks)}"
            raise RuntimeError(msg)
        return {
            "cell_count": len(cells),
            "daily_state_count": len(daily_states),
            "state_version_count": len(versions),
            "geological_link_count": len(geo_links),
            "response_link_count": len(response_links),
            "unlocated_operational_count": len(unlocated_operational),
            "daily_located_point_operational_count": len(daily_located_point_operational),
            "hard_check_count": len(hard_checks),
        }

    def _load_state_config(self) -> ConstructionStateConfig:
        path = self.config.resolve(self.config.construction_state_config_path)
        return ConstructionStateConfig.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8"))
        )

    def _prepare_output_dir(self) -> None:
        if self.out.exists() and any(self.out.iterdir()):
            if not self.config.overwrite:
                msg = f"Output directory already exists and is not empty: {self.out}"
                raise FileExistsError(msg)
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True, exist_ok=True)

    def _verify_inputs(self) -> list[dict[str, Any]]:
        rows = []
        for label, directory in [
            ("geology", self.geology_dir),
            ("applicability", self.applicability_dir),
            ("operational", self.operational_dir),
        ]:
            for row in verify_hash_manifest(directory):
                row["source"] = label
                rows.append(row)
        return rows

    def _source_hashes(self) -> dict[str, str]:
        return {
            "geology": sha256_file(self.geology_dir / "freeze_manifest.json"),
            "applicability": sha256_file(self.applicability_dir / "freeze_manifest.json"),
            "operational": sha256_file(self.operational_dir / "freeze_manifest.json"),
        }

    def _load_inputs(self) -> dict[str, Any]:
        daily_scopes = read_jsonl(self.operational_dir / "plc_daily_scope_v2.jsonl")
        episodes = read_jsonl(self.operational_dir / "excavation_episodes.jsonl")
        phase_intervals = read_jsonl(self.operational_dir / "phase_intervals.jsonl")
        source_assets = read_jsonl(self.operational_dir / "source_assets.jsonl")
        footprints = read_jsonl(self.operational_dir / "spatial_footprints.jsonl")
        responses = read_jsonl(self.operational_dir / "response_evidence.jsonl")
        geological_documents = read_jsonl(self.geology_dir / "geological_documents.jsonl")
        primary_evidence = read_jsonl(self.geology_dir / "primary_geological_evidence.jsonl")
        source_spans = read_jsonl(self.geology_dir / "source_spans.jsonl")
        primary_assignments = read_jsonl(
            self.applicability_dir / "evidence_applicability_assignments.jsonl"
        )
        assertion_assignments = read_jsonl(
            self.applicability_dir / "assertion_applicability_assignments.jsonl"
        )
        clause_assignments = read_jsonl(
            self.applicability_dir / "clause_applicability_assignments.jsonl"
        )
        data: dict[str, Any] = {
            "daily_scopes": sorted(daily_scopes, key=lambda row: row["target_date"]),
            "episodes": episodes,
            "phase_intervals": phase_intervals,
            "source_assets": source_assets,
            "footprints": footprints,
            "responses": responses,
            "geological_documents": geological_documents,
            "primary_evidence": primary_evidence,
            "source_spans": source_spans,
            "primary_assignments": primary_assignments,
            "assertion_assignments": assertion_assignments,
            "clause_assignments": clause_assignments,
            "geology_manifest": read_json(self.geology_dir / "freeze_manifest.json"),
            "applicability_manifest": read_json(self.applicability_dir / "freeze_manifest.json"),
            "operational_manifest": read_json(self.operational_dir / "freeze_manifest.json"),
        }
        for key in ["episodes", "phase_intervals", "source_assets", "responses"]:
            data[f"{key}_by_date"] = self._group_by_date(data[key])
        data["footprint_by_episode"] = {row["episode_id"]: row for row in footprints}
        data["geological_document_by_id"] = {
            row["document_id"]: row for row in geological_documents
        }
        data["primary_evidence_by_id"] = _primary_evidence_id_index(primary_evidence)
        data["source_span_by_id"] = {row["span_id"]: row for row in source_spans}
        data["primary_assignment_by_id"] = {
            row["assignment_id"]: row for row in primary_assignments
        }
        data["responses_by_episode"] = self._group_by(responses, "episode_id")
        data["primary_assignments_by_date"] = self._group_by_date(primary_assignments)
        data["assertion_assignments_by_date"] = self._group_by_date(assertion_assignments)
        data["clause_assignments_by_date"] = self._group_by_date(clause_assignments)
        return data

    def _assert_formal_inputs(self, data: dict[str, Any]) -> None:
        dates = {row["target_date"] for row in data["daily_scopes"]}
        assignment_dates = {row["target_date"] for row in data["primary_assignments"]}
        episode_dates = {row["target_date"] for row in data["episodes"]}
        if len(dates) != 91 or dates != assignment_dates or not episode_dates <= dates:
            msg = "Stage 3A date sets do not match formal Stage 2 freezes"
            raise ValueError(msg)
        if len(data["primary_assignments"]) != 59969:
            raise ValueError("Applicability V2.1 primary assignment count mismatch")
        if self.applicability_dir.name != "stage2d_applicability_v2_1":
            raise ValueError("Stage 3A requires formal Applicability V2.1 input")
        if self.operational_dir.name != "stage2_plc_operational_freeze_v2":
            raise ValueError("Stage 3A requires formal PLC Operational Freeze V2 input")
        if self.state_config.state_method_version != _FORMAL_METHOD_VERSION:
            raise ValueError("Stage 3A requires formal v1.1 point-response-complete method")

    def _trusted_scope_union(self, daily_scopes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scopes = []
        for row in daily_scopes:
            for key in ["daily_excavated_scope", "forward_scope", "local_background_scope"]:
                if row.get(key):
                    scopes.append(row[key])
        return scopes

    def _daily_state(
        self,
        daily_scope: dict[str, Any],
        *,
        data: dict[str, Any],
        source_hashes: dict[str, str],
    ) -> dict[str, Any]:
        target_date = str(daily_scope["target_date"])
        target_local_date = date.fromisoformat(target_date)
        episodes = data["episodes_by_date"].get(target_date, [])
        phase_intervals = data["phase_intervals_by_date"].get(target_date, [])
        source_assets = data["source_assets_by_date"].get(target_date, [])
        responses = data["responses_by_date"].get(target_date, [])
        usable_episode_ids = []
        unusable_episode_ids = []
        for episode in episodes:
            footprint = data["footprint_by_episode"].get(episode["episode_id"])
            if footprint and footprint["spatial_scope_usable"]:
                usable_episode_ids.append(episode["episode_id"])
            else:
                unusable_episode_ids.append(episode["episode_id"])
        daily_state = DailyConstructionState(
            daily_state_id="daily_state_"
            + stable_id(target_date, self.state_config.state_method_version),
            target_date=target_local_date,
            daily_scope_reference_id=str(daily_scope["daily_scope_reference_id"]),
            spatial_scope_status=str(daily_scope["spatial_scope_status"]),
            regime_statuses=list(daily_scope.get("regime_statuses", [])),
            raw_daily_plc_range=daily_scope.get("raw_daily_plc_range"),
            trusted_daily_plc_range=daily_scope.get("trusted_daily_plc_range"),
            daily_excavated_scope=daily_scope.get("daily_excavated_scope"),
            forward_scope=daily_scope.get("forward_scope"),
            local_background_scope=daily_scope.get("local_background_scope"),
            current_chainage=daily_scope.get("current_chainage"),
            raw_plc_range_span_m=_scope_span(daily_scope.get("raw_daily_plc_range")),
            trusted_plc_range_span_m=_scope_span(daily_scope.get("trusted_daily_plc_range")),
            source_asset_ids=[row["asset_id"] for row in source_assets],
            phase_interval_ids=[row["phase_interval_id"] for row in phase_intervals],
            episode_ids=[row["episode_id"] for row in episodes],
            spatially_usable_episode_ids=usable_episode_ids,
            spatially_unusable_episode_ids=unusable_episode_ids,
            response_evidence_ids=[row["evidence_id"] for row in responses],
            knowledge_as_of_local_date=target_local_date,
            knowledge_precision="DAY",
            knowledge_cutoff_basis="FROZEN_APPLICABILITY_TARGET_DATE_END_OF_DAY_VIEW",
            source_stage2e_manifest_hash=source_hashes["operational"],
            source_applicability_manifest_hash=source_hashes["applicability"],
            state_method_version=self.state_config.state_method_version,
        )
        return daily_state.model_dump(mode="json")

    def _cell_roles_for_day(
        self,
        daily_scope: dict[str, Any],
        cells_by_index: dict[int, Any],
        *,
        conflict_rows: list[dict[str, Any]],
    ) -> dict[str, CellScopeRole]:
        roles: dict[str, CellScopeRole] = {}
        for key, role in [
            ("daily_excavated_scope", CellScopeRole.DAILY_REVIEW_CELL),
            ("forward_scope", CellScopeRole.FORWARD_ATTENTION_CELL),
            ("local_background_scope", CellScopeRole.LOCAL_BACKGROUND_CELL),
        ]:
            scope = daily_scope.get(key)
            if not scope:
                continue
            for cell, _, _, _ in split_scope_to_cells(
                scope,
                cells_by_index,
                origin=self.state_config.grid_origin_m,
                cell_size=self.state_config.cell_size_m,
            ):
                existing_role = roles.get(cell.cell_id)
                if existing_role is not None and existing_role != role:
                    conflict_rows.append(
                        {
                            "target_date": daily_scope["target_date"],
                            "cell_id": cell.cell_id,
                            "cell_index": cell.cell_index,
                            "scope_key": key,
                            "existing_cell_scope_role": existing_role.value,
                            "conflicting_cell_scope_role": role.value,
                            "status": "SCOPE_ROLE_CONFLICT",
                        }
                    )
                roles.setdefault(cell.cell_id, role)
        return roles

    def _initial_version(
        self,
        daily_state: dict[str, Any],
        cell: Any,
        role: CellScopeRole,
        source_hashes: dict[str, str],
    ) -> dict[str, Any]:
        state_version_id = "state_version_" + stable_id(
            str(daily_state["daily_state_id"]),
            cell.cell_id,
            "1",
            self.state_config.state_method_version,
        )
        version = InitialConstructionStateVersion(
            state_version_id=state_version_id,
            daily_state_id=str(daily_state["daily_state_id"]),
            cell_id=cell.cell_id,
            target_date=daily_state["target_date"],
            valid_date=daily_state["target_date"],
            valid_time_precision="DAY",
            knowledge_as_of_local_date=daily_state["target_date"],
            knowledge_precision="DAY",
            historical_transaction_time=None,
            historical_transaction_time_known=False,
            transaction_time_basis="HISTORICAL_DATABASE_TRANSACTION_TIME_UNAVAILABLE",
            reconstructed_at=self.config.generated_at,
            version_number=1,
            supersedes_version_id=None,
            is_current_version=True,
            cell_scope_role=role,
            episode_ids=[],
            response_evidence_ids=[],
            daily_review_evidence_ids=[],
            forward_attention_evidence_ids=[],
            local_background_evidence_ids=[],
            observed_geological_evidence_ids=[],
            forecast_geological_evidence_ids=[],
            background_geological_evidence_ids=[],
            source_assignment_ids=[],
            geological_link_ids=[],
            response_link_ids=[],
            state_quality_flags=[],
            state_reason_codes=[],
            source_geology_manifest_hash=source_hashes["geology"],
            source_applicability_manifest_hash=source_hashes["applicability"],
            source_operational_manifest_hash=source_hashes["operational"],
            state_method_version=self.state_config.state_method_version,
        )
        return version.model_dump(mode="json")

    def _response_links_for_day(
        self,
        *,
        daily_state: dict[str, Any],
        responses: list[dict[str, Any]],
        footprint_by_episode: dict[str, dict[str, Any]],
        cell_roles: dict[str, CellScopeRole],
        cells_by_index: dict[int, Any],
        versions_by_date_cell: dict[tuple[str, str], dict[str, Any]],
        accumulators: dict[str, dict[str, set[str]]],
        audit_rows: list[dict[str, Any]],
        unlocated_rows: list[dict[str, Any]],
        daily_located_point_rows: list[dict[str, Any]],
        coverage_rows: list[dict[str, Any]],
        multicell_rows: list[dict[str, Any]],
        source_hashes: dict[str, str],
    ) -> list[dict[str, Any]]:
        links: list[dict[str, Any]] = []
        for response in responses:
            footprint = footprint_by_episode[response["episode_id"]]
            trusted_scope = response.get("trusted_spatial_scope")
            if not response["spatial_scope_usable"] or not trusted_scope:
                unlocated_rows.append(
                    self._unlocated_operational_row(daily_state, response, footprint, source_hashes)
                )
                coverage_rows.append(
                    self._response_coverage_row(
                        response,
                        cell_link_count=0,
                        located_point_daily_event_count=0,
                        unlocated_event_count=1,
                        coverage_class="SPATIALLY_UNLOCATED",
                    )
                )
                continue
            pieces = split_trusted_response_to_daily_cells(
                trusted_scope,
                cells_by_index=cells_by_index,
                cell_roles=cell_roles,
                config=self.state_config,
            )
            if trusted_scope.get("kind") == "POINT" and not pieces:
                point_piece = map_trusted_point_response_to_cell(
                    trusted_scope,
                    cells_by_index=cells_by_index,
                    cell_roles=cell_roles,
                    config=self.state_config,
                )
                if point_piece is not None:
                    daily_located_point_rows.append(
                        self._daily_located_point_operational_row(
                            daily_state=daily_state,
                            response=response,
                            footprint=footprint,
                            point_piece=point_piece,
                            source_hashes=source_hashes,
                        )
                    )
                    coverage_rows.append(
                        self._response_coverage_row(
                            response,
                            cell_link_count=0,
                            located_point_daily_event_count=1,
                            unlocated_event_count=0,
                            coverage_class="LOCATED_POINT_DAILY_ONLY",
                        )
                    )
                    continue
            response_link_ids: list[str] = []
            linked_cell_ids: list[str] = []
            for piece in pieces:
                version = versions_by_date_cell[
                    (str(daily_state["target_date"]), piece.cell.cell_id)
                ]
                link_id = "state_response_link_" + stable_id(
                    version["state_version_id"],
                    response["evidence_id"],
                    str(piece.start),
                    str(piece.end),
                    self.state_config.state_method_version,
                )
                valid_time = response.get("valid_time") or {}
                link = StateResponseEvidenceLink(
                    link_id=link_id,
                    state_version_id=version["state_version_id"],
                    daily_state_id=str(daily_state["daily_state_id"]),
                    cell_id=piece.cell.cell_id,
                    target_date=daily_state["target_date"],
                    episode_id=response["episode_id"],
                    footprint_id=footprint["footprint_id"],
                    response_evidence_id=response["evidence_id"],
                    channel_name=response["channel_name"],
                    valid_time_start=valid_time.get("start"),
                    valid_time_end=valid_time.get("end"),
                    available_time=response.get("available_time"),
                    trusted_overlap_start=piece.start,
                    trusted_overlap_end=piece.end,
                    trusted_overlap_length_m=piece.length,
                    trusted_overlap_kind=piece.trusted_overlap_kind,
                    spatial_relation=piece.spatial_relation,
                    response_stat_scope="EPISODE_LEVEL_SHARED",
                    spatial_scope_usable=True,
                    chainage_regime_status=response["chainage_regime_status"],
                    response_quality_grade=response["quality_grade"],
                    response_quality_flags=response.get("quality_flags", []),
                    source_asset_ids=response.get("source_asset_ids", []),
                    core_observation_refs=response.get("core_observation_refs", []),
                    link_reason_codes=[
                        "TRUSTED_RESPONSE_SCOPE_OVERLAPS_DAILY_REVIEW_CELL"
                        if piece.trusted_overlap_kind == "INTERVAL"
                        else "TRUSTED_POINT_SCOPE_IN_DAILY_REVIEW_CELL"
                    ],
                    source_operational_manifest_hash=source_hashes["operational"],
                    link_method_version=self.state_config.state_method_version,
                ).model_dump(mode="json")
                links.append(link)
                response_link_ids.append(link_id)
                linked_cell_ids.append(piece.cell.cell_id)
                acc = accumulators[version["state_version_id"]]
                acc["response_link_ids"].add(link_id)
                acc["response_evidence_ids"].add(response["evidence_id"])
                acc["episode_ids"].add(response["episode_id"])
                audit_rows.append(
                    {
                        "target_date": daily_state["target_date"],
                        "response_evidence_id": response["evidence_id"],
                        "cell_id": piece.cell.cell_id,
                        "trusted_overlap_kind": piece.trusted_overlap_kind,
                        "spatial_relation": piece.spatial_relation,
                        "overlap_length_m": piece.length,
                        "status": "LINKED",
                    }
                )
            if response_link_ids:
                coverage_rows.append(
                    self._response_coverage_row(
                        response,
                        cell_link_count=len(response_link_ids),
                        located_point_daily_event_count=0,
                        unlocated_event_count=0,
                        coverage_class="CELL_LINKED",
                    )
                )
                multicell_rows.append(
                    {
                        "target_date": daily_state["target_date"],
                        "episode_id": response["episode_id"],
                        "response_evidence_id": response["evidence_id"],
                        "trusted_scope_kind": trusted_scope.get("kind"),
                        "linked_cell_count": len(response_link_ids),
                        "linked_cell_ids": linked_cell_ids,
                        "response_link_ids": response_link_ids,
                        "response_stat_scope": "EPISODE_LEVEL_SHARED",
                        "status": "MULTICELL" if len(response_link_ids) > 1 else "SINGLE_CELL",
                    }
                )
            elif trusted_scope.get("kind") != "POINT":
                coverage_rows.append(
                    self._response_coverage_row(
                        response,
                        cell_link_count=0,
                        located_point_daily_event_count=0,
                        unlocated_event_count=0,
                        coverage_class="UNCLASSIFIED",
                    )
                )
        return links

    def _geological_links_for_day(
        self,
        *,
        daily_state: dict[str, Any],
        assignments: list[dict[str, Any]],
        cell_roles: dict[str, CellScopeRole],
        cells_by_index: dict[int, Any],
        versions_by_date_cell: dict[tuple[str, str], dict[str, Any]],
        accumulators: dict[str, dict[str, set[str]]],
        audit_rows: list[dict[str, Any]],
        point_audit_rows: list[dict[str, Any]],
        interval_audit_rows: list[dict[str, Any]],
        epistemic_audit_rows: list[dict[str, Any]],
        source_hashes: dict[str, str],
    ) -> list[dict[str, Any]]:
        links: list[dict[str, Any]] = []
        for assignment in assignments:
            if assignment["applicability_role"] == "NOT_APPLICABLE":
                continue
            pieces = split_assignment_to_role_cells(
                assignment,
                cells_by_index=cells_by_index,
                cell_roles=cell_roles,
                config=self.state_config,
            )
            total = round(sum(piece[3] for piece in pieces), 6)
            expected = round(float(assignment.get("overlap_length_m") or 0.0), 6)
            interval_audit_rows.append(
                {
                    "target_date": daily_state["target_date"],
                    "assignment_id": assignment["assignment_id"],
                    "overlap_kind": (assignment.get("overlap_scope") or {}).get("kind"),
                    "expected_overlap_length_m": expected,
                    "linked_overlap_length_m": total,
                    "status": "PASS" if abs(total - expected) <= 0.001 else "MISMATCH",
                }
            )
            if (assignment.get("overlap_scope") or {}).get("kind") == "POINT":
                point_audit_rows.append(
                    {
                        "target_date": daily_state["target_date"],
                        "assignment_id": assignment["assignment_id"],
                        "cell_link_count": len(pieces),
                        "status": "PASS" if len(pieces) == 1 else "DUPLICATE_OR_MISSING",
                    }
                )
            for cell, start, end, length in pieces:
                version = versions_by_date_cell[(str(daily_state["target_date"]), cell.cell_id)]
                link_id = "state_geology_link_" + stable_id(
                    version["state_version_id"],
                    assignment["assignment_id"],
                    str(start),
                    str(end),
                    self.state_config.state_method_version,
                )
                link = StateGeologicalEvidenceLink(
                    link_id=link_id,
                    state_version_id=version["state_version_id"],
                    daily_state_id=str(daily_state["daily_state_id"]),
                    cell_id=cell.cell_id,
                    target_date=daily_state["target_date"],
                    assignment_id=assignment["assignment_id"],
                    evidence_id=assignment["evidence_id"],
                    document_id=assignment["document_id"],
                    asset_id=assignment["asset_id"],
                    source_type=assignment["source_type"],
                    evidence_type=assignment["evidence_type"],
                    epistemic_status=assignment["epistemic_status"],
                    applicability_role=assignment["applicability_role"],
                    overlap_kind=assignment["overlap_scope"]["kind"],
                    overlap_start=start,
                    overlap_end=end,
                    overlap_length_m=length,
                    source_span_ids=assignment.get("source_span_ids", []),
                    assignment_reason_codes=assignment.get("reason_codes", []),
                    link_reason_codes=["APPLICABILITY_OVERLAP_SCOPE_SPLIT_TO_MATCHING_CELL_ROLE"],
                    source_geology_manifest_hash=source_hashes["geology"],
                    source_applicability_manifest_hash=source_hashes["applicability"],
                    link_method_version=self.state_config.state_method_version,
                ).model_dump(mode="json")
                links.append(link)
                acc = accumulators[version["state_version_id"]]
                acc["geological_link_ids"].add(link_id)
                acc["source_assignment_ids"].add(assignment["assignment_id"])
                self._add_geo_evidence_to_accumulator(acc, assignment)
                audit_rows.append(
                    {
                        "target_date": daily_state["target_date"],
                        "assignment_id": assignment["assignment_id"],
                        "cell_id": cell.cell_id,
                        "applicability_role": assignment["applicability_role"],
                        "cell_scope_role": cell_roles[cell.cell_id].value,
                        "status": "LINKED",
                    }
                )
                epistemic_audit_rows.append(
                    {
                        "target_date": daily_state["target_date"],
                        "assignment_id": assignment["assignment_id"],
                        "evidence_id": assignment["evidence_id"],
                        "epistemic_status": assignment["epistemic_status"],
                        "applicability_role": assignment["applicability_role"],
                        "status": "PASS",
                    }
                )
        return links

    def _assertion_trace_links_for_day(
        self,
        *,
        daily_state: dict[str, Any],
        assignments: list[dict[str, Any]],
        cell_roles: dict[str, CellScopeRole],
        cells_by_index: dict[int, Any],
        versions_by_date_cell: dict[tuple[str, str], dict[str, Any]],
        source_hashes: dict[str, str],
    ) -> list[dict[str, Any]]:
        rows = []
        for assignment in assignments:
            if assignment["applicability_role"] == "NOT_APPLICABLE":
                continue
            pieces = split_assignment_to_role_cells(
                assignment,
                cells_by_index=cells_by_index,
                cell_roles=cell_roles,
                config=self.state_config,
            )
            for cell, start, end, length in pieces:
                version = versions_by_date_cell[(str(daily_state["target_date"]), cell.cell_id)]
                rows.append(
                    {
                        "trace_link_id": "state_assertion_trace_"
                        + stable_id(
                            version["state_version_id"],
                            assignment["assignment_id"],
                            str(start),
                            str(end),
                        ),
                        "state_version_id": version["state_version_id"],
                        "daily_state_id": daily_state["daily_state_id"],
                        "cell_id": cell.cell_id,
                        "target_date": daily_state["target_date"],
                        "assignment_id": assignment["assignment_id"],
                        "assertion_id": assignment.get("assertion_id"),
                        "assertion_type": assignment.get("assertion_type"),
                        "evidence_id": assignment["evidence_id"],
                        "applicability_role": assignment["applicability_role"],
                        "epistemic_status": assignment["epistemic_status"],
                        "overlap_start": start,
                        "overlap_end": end,
                        "overlap_length_m": length,
                        "source_applicability_manifest_hash": source_hashes["applicability"],
                        "trace_method_version": self.state_config.state_method_version,
                    }
                )
        return rows

    def _unlocated_clause_rows(
        self,
        daily_state: dict[str, Any],
        assignments: list[dict[str, Any]],
        source_hashes: dict[str, str],
    ) -> list[dict[str, Any]]:
        rows = []
        for assignment in assignments:
            rows.append(
                {
                    "trace_id": "daily_unlocated_clause_"
                    + stable_id(str(daily_state["daily_state_id"]), assignment["assignment_id"]),
                    "daily_state_id": daily_state["daily_state_id"],
                    "target_date": daily_state["target_date"],
                    "assignment_id": assignment["assignment_id"],
                    "clause_id": assignment["clause_id"],
                    "document_id": assignment["document_id"],
                    "source_type": assignment["source_type"],
                    "statement_role": assignment.get("statement_role"),
                    "applicability_role": assignment["applicability_role"],
                    "reason_codes": assignment.get("reason_codes", []),
                    "source_span_ids": assignment.get("source_span_ids", []),
                    "source_applicability_manifest_hash": source_hashes["applicability"],
                    "trace_method_version": self.state_config.state_method_version,
                }
            )
        return rows

    def _unlocated_operational_rows(
        self,
        daily_state: dict[str, Any],
        responses: list[dict[str, Any]],
        footprint_by_episode: dict[str, dict[str, Any]],
        source_hashes: dict[str, str],
    ) -> list[dict[str, Any]]:
        return [
            self._unlocated_operational_row(
                daily_state,
                response,
                footprint_by_episode[response["episode_id"]],
                source_hashes,
            )
            for response in responses
        ]

    def _unlocated_response_coverage_rows(
        self,
        responses: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            self._response_coverage_row(
                response,
                cell_link_count=0,
                located_point_daily_event_count=0,
                unlocated_event_count=1,
                coverage_class="SPATIALLY_UNLOCATED",
            )
            for response in responses
        ]

    def _unlocated_operational_row(
        self,
        daily_state: dict[str, Any],
        response: dict[str, Any],
        footprint: dict[str, Any],
        source_hashes: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "unlocated_event_id": "daily_unlocated_operational_"
            + stable_id(str(daily_state["daily_state_id"]), response["evidence_id"]),
            "daily_state_id": daily_state["daily_state_id"],
            "target_date": daily_state["target_date"],
            "episode_id": response["episode_id"],
            "footprint_id": footprint["footprint_id"],
            "response_evidence_id": response["evidence_id"],
            "channel_name": response["channel_name"],
            "spatial_scope_usable": response["spatial_scope_usable"],
            "chainage_regime_status": response["chainage_regime_status"],
            "reason_codes": ["PLC_SPATIAL_SCOPE_UNAVAILABLE"],
            "source_operational_manifest_hash": source_hashes["operational"],
            "trace_method_version": self.state_config.state_method_version,
        }

    def _daily_located_point_operational_row(
        self,
        *,
        daily_state: dict[str, Any],
        response: dict[str, Any],
        footprint: dict[str, Any],
        point_piece: ResponseCellPiece,
        source_hashes: dict[str, str],
    ) -> dict[str, Any]:
        reason_codes = ["POINT_CELL_ROLE_NOT_DAILY_REVIEW"]
        if _point_at_daily_lower_boundary(
            point_piece.start, daily_state.get("daily_excavated_scope")
        ):
            reason_codes.insert(0, "POINT_AT_DAILY_REVIEW_LOWER_BOUNDARY")
        return {
            "event_id": "daily_located_point_operational_"
            + stable_id(str(daily_state["daily_state_id"]), response["evidence_id"]),
            "daily_state_id": daily_state["daily_state_id"],
            "target_date": daily_state["target_date"],
            "episode_id": response["episode_id"],
            "footprint_id": footprint["footprint_id"],
            "response_evidence_id": response["evidence_id"],
            "channel_name": response["channel_name"],
            "point_chainage": point_piece.start,
            "mapped_cell_id": point_piece.cell.cell_id,
            "mapped_cell_role": point_piece.mapped_cell_role.value
            if point_piece.mapped_cell_role
            else None,
            "daily_excavated_scope": daily_state.get("daily_excavated_scope"),
            "classification": "LOCATED_POINT_NOT_ASSIGNED_TO_DAILY_REVIEW_CELL",
            "reason_codes": reason_codes,
            "source_operational_manifest_hash": source_hashes["operational"],
        }

    def _response_coverage_row(
        self,
        response: dict[str, Any],
        *,
        cell_link_count: int,
        located_point_daily_event_count: int,
        unlocated_event_count: int,
        coverage_class: str,
    ) -> dict[str, Any]:
        trusted_scope = response.get("trusted_spatial_scope") or {}
        class_hit_count = sum(
            [
                coverage_class == "CELL_LINKED",
                coverage_class == "LOCATED_POINT_DAILY_ONLY",
                coverage_class == "SPATIALLY_UNLOCATED",
            ]
        )
        return {
            "response_evidence_id": response["evidence_id"],
            "episode_id": response["episode_id"],
            "target_date": response["target_date"],
            "trusted_scope_kind": trusted_scope.get("kind"),
            "trusted_scope_start": trusted_scope.get("start_chainage"),
            "trusted_scope_end": trusted_scope.get("end_chainage"),
            "spatial_scope_usable": response["spatial_scope_usable"],
            "cell_link_count": cell_link_count,
            "located_point_daily_event_count": located_point_daily_event_count,
            "unlocated_event_count": unlocated_event_count,
            "coverage_class": coverage_class,
            "status": "PASS"
            if class_hit_count == 1
            and (
                cell_link_count > 0
                or located_point_daily_event_count == 1
                or unlocated_event_count == 1
            )
            else "FAIL",
        }

    def _finalize_versions(
        self,
        versions: list[dict[str, Any]],
        accumulators: dict[str, dict[str, set[str]]],
    ) -> list[dict[str, Any]]:
        finalized = []
        for version in versions:
            acc = accumulators[version["state_version_id"]]
            row = dict(version)
            for key, values in acc.items():
                row[key] = sorted(values)
            finalized.append(row)
        return finalized

    def _empty_version_accumulator(self) -> dict[str, set[str]]:
        return {
            "episode_ids": set(),
            "response_evidence_ids": set(),
            "daily_review_evidence_ids": set(),
            "forward_attention_evidence_ids": set(),
            "local_background_evidence_ids": set(),
            "observed_geological_evidence_ids": set(),
            "forecast_geological_evidence_ids": set(),
            "background_geological_evidence_ids": set(),
            "source_assignment_ids": set(),
            "geological_link_ids": set(),
            "response_link_ids": set(),
        }

    def _add_geo_evidence_to_accumulator(
        self,
        acc: dict[str, set[str]],
        assignment: dict[str, Any],
    ) -> None:
        role_key = {
            "DAILY_REVIEW": "daily_review_evidence_ids",
            "FORWARD_ATTENTION": "forward_attention_evidence_ids",
            "LOCAL_BACKGROUND": "local_background_evidence_ids",
        }[assignment["applicability_role"]]
        acc[role_key].add(assignment["evidence_id"])
        epistemic_key = {
            "OBSERVED": "observed_geological_evidence_ids",
            "FORECAST": "forecast_geological_evidence_ids",
            "BACKGROUND": "background_geological_evidence_ids",
        }.get(assignment["epistemic_status"])
        if epistemic_key:
            acc[epistemic_key].add(assignment["evidence_id"])

    def _write_outputs(
        self,
        *,
        cells: list[dict[str, Any]],
        daily_states: list[dict[str, Any]],
        versions: list[dict[str, Any]],
        geo_links: list[dict[str, Any]],
        response_links: list[dict[str, Any]],
        assertion_links: list[dict[str, Any]],
        unlocated_clauses: list[dict[str, Any]],
        unlocated_operational: list[dict[str, Any]],
        daily_located_point_operational: list[dict[str, Any]],
        audits: dict[str, list[dict[str, Any]]],
        data: dict[str, Any],
        source_hashes: dict[str, str],
        protected_hash_rows: list[dict[str, Any]],
        hard_checks: list[dict[str, Any]],
    ) -> None:
        write_jsonl(self.out / "construction_state_cells.jsonl", cells)
        write_jsonl(self.out / "daily_construction_states.jsonl", daily_states)
        write_jsonl(self.out / "initial_construction_state_versions.jsonl", versions)
        write_jsonl(self.out / "state_geological_evidence_links.jsonl", geo_links)
        write_jsonl(self.out / "state_response_evidence_links.jsonl", response_links)
        write_jsonl(self.out / "state_assertion_trace_links.jsonl", assertion_links)
        write_jsonl(self.out / "daily_unlocated_clause_trace.jsonl", unlocated_clauses)
        write_jsonl(self.out / "daily_unlocated_operational_events.jsonl", unlocated_operational)
        write_jsonl(
            self.out / "daily_located_point_operational_events.jsonl",
            daily_located_point_operational,
        )
        for filename, rows in audits.items():
            write_csv(self.out / filename, rows, _AUDIT_FIELDNAMES.get(filename))
        write_csv(self.out / "stage2_freeze_hash_audit.csv", protected_hash_rows)
        write_json(self.out / "schema_manifest.json", self._schema_manifest())
        snapshot_sha, source_tree_hash = self._write_source_snapshot()
        method = self._method_version(
            source_hashes,
            snapshot_sha=snapshot_sha,
            source_tree_hash=source_tree_hash,
        )
        write_json(self.out / "method_version.json", method)
        summary = self._freeze_manifest(
            cells=cells,
            daily_states=daily_states,
            versions=versions,
            geo_links=geo_links,
            response_links=response_links,
            assertion_links=assertion_links,
            unlocated_clauses=unlocated_clauses,
            unlocated_operational=unlocated_operational,
            daily_located_point_operational=daily_located_point_operational,
            data=data,
            source_hashes=source_hashes,
            hard_checks=hard_checks,
            snapshot_sha=snapshot_sha,
            source_tree_hash=source_tree_hash,
        )
        write_json(self.out / "freeze_manifest.json", summary)
        self._write_report(summary)
        self._write_formal_promotion_artifacts()
        write_file_hashes(self.out)

    def _schema_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": "stage3a_initial_epistemic_state.v1.1",
            "objects": [
                "ConstructionStateCell",
                "DailyConstructionState",
                "InitialConstructionStateVersion",
                "StateGeologicalEvidenceLink",
                "StateResponseEvidenceLink",
                "DailyLocatedPointOperationalEvent",
            ],
            "interval_convention": "cell=(start,end]; interval evidence uses positive overlap; "
            "point response uses POINT_IN_CELL with zero overlap length",
        }

    def _method_version(
        self,
        source_hashes: dict[str, str],
        *,
        snapshot_sha: str,
        source_tree_hash: str,
    ) -> dict[str, Any]:
        return {
            "method_version": self.state_config.state_method_version,
            "schema_version": "stage3a_initial_epistemic_state.v1.1",
            "generated_at": self.config.generated_at.isoformat(),
            "geology_freeze_dir": _repo_relative(self.repo, self.geology_dir),
            "applicability_dir": _repo_relative(self.repo, self.applicability_dir),
            "operational_freeze_dir": _repo_relative(self.repo, self.operational_dir),
            "source_geology_manifest_hash": source_hashes["geology"],
            "source_applicability_manifest_hash": source_hashes["applicability"],
            "source_operational_manifest_hash": source_hashes["operational"],
            "historical_transaction_time_known": False,
            "transaction_time_basis": "HISTORICAL_DATABASE_TRANSACTION_TIME_UNAVAILABLE",
            "source_snapshot_sha256": snapshot_sha,
            "source_tree_hash": source_tree_hash,
            "llm_used": False,
            "stage3b_not_run": True,
        }

    def _freeze_manifest(
        self,
        *,
        cells: list[dict[str, Any]],
        daily_states: list[dict[str, Any]],
        versions: list[dict[str, Any]],
        geo_links: list[dict[str, Any]],
        response_links: list[dict[str, Any]],
        assertion_links: list[dict[str, Any]],
        unlocated_clauses: list[dict[str, Any]],
        unlocated_operational: list[dict[str, Any]],
        daily_located_point_operational: list[dict[str, Any]],
        data: dict[str, Any],
        source_hashes: dict[str, str],
        hard_checks: list[dict[str, Any]],
        snapshot_sha: str,
        source_tree_hash: str,
    ) -> dict[str, Any]:
        return {
            "method_version": self.state_config.state_method_version,
            "schema_version": "stage3a_initial_epistemic_state.v1.1",
            "cell_count": len(cells),
            "daily_state_count": len(daily_states),
            "initial_state_version_count": len(versions),
            "cell_role_distribution": count_by(versions, "cell_scope_role"),
            "daily_cell_count_distribution": _daily_cell_count_distribution(
                daily_states,
                versions,
            ),
            "geological_link_count": len(geo_links),
            "geological_link_role_distribution": count_by(geo_links, "applicability_role"),
            "geological_link_epistemic_distribution": count_by(geo_links, "epistemic_status"),
            "response_link_count": len(response_links),
            "response_link_channel_distribution": count_by(response_links, "channel_name"),
            "assertion_trace_link_count": len(assertion_links),
            "unlocated_clause_trace_count": len(unlocated_clauses),
            "unlocated_operational_event_count": len(unlocated_operational),
            "daily_located_point_operational_event_count": len(daily_located_point_operational),
            "response_coverage_distribution": _response_coverage_distribution(
                response_links,
                unlocated_operational,
                daily_located_point_operational,
            ),
            "trusted_episode_scope_distribution": _trusted_episode_kind_distribution(
                data["footprints"]
            ),
            "trusted_response_scope_distribution": _trusted_response_kind_distribution(
                data["responses"]
            ),
            "spatially_unusable_episode_count": sum(
                len(row["spatially_unusable_episode_ids"]) for row in daily_states
            ),
            "spatially_unusable_response_evidence_count": len(unlocated_operational),
            "input_episode_count": len(data["episodes"]),
            "input_response_evidence_count": len(data["responses"]),
            "input_primary_assignment_count": len(data["primary_assignments"]),
            "source_geology_manifest_hash": source_hashes["geology"],
            "source_applicability_manifest_hash": source_hashes["applicability"],
            "source_operational_manifest_hash": source_hashes["operational"],
            "source_snapshot_sha256": snapshot_sha,
            "source_tree_hash": source_tree_hash,
            "hard_check_issue_count": len(hard_checks),
        }

    def _write_report(self, summary: dict[str, Any]) -> None:
        lines = [
            "# Stage 3A Initial Epistemic State",
            "",
            "This build creates initial day-end state snapshots only. It does not implement "
            "revision lineage, RAI, GRS, GRCI, Claim, LLM, or reports.",
            "",
            f"- unique cells: {summary['cell_count']}",
            f"- DailyConstructionState: {summary['daily_state_count']}",
            f"- InitialConstructionStateVersion: {summary['initial_state_version_count']}",
            f"- Cell role distribution: {summary['cell_role_distribution']}",
            f"- Daily cell count distribution: {summary['daily_cell_count_distribution']}",
            f"- Geological Links: {summary['geological_link_count']}",
            f"- Geological Link role distribution: {summary['geological_link_role_distribution']}",
            "- Geological Link epistemic distribution: "
            f"{summary['geological_link_epistemic_distribution']}",
            f"- Response Links: {summary['response_link_count']}",
            "- Response Link channel distribution: "
            f"{summary['response_link_channel_distribution']}",
            f"- Unlocated operational events: {summary['unlocated_operational_event_count']}",
            "- Daily located POINT operational events: "
            f"{summary['daily_located_point_operational_event_count']}",
            f"- Response coverage distribution: {summary['response_coverage_distribution']}",
            "- Trusted Episode scope distribution: "
            f"{summary['trusted_episode_scope_distribution']}",
            "- Trusted Response scope distribution: "
            f"{summary['trusted_response_scope_distribution']}",
            f"- Spatially unusable Episodes: {summary['spatially_unusable_episode_count']}",
            "- Spatially unusable ResponseEvidence: "
            f"{summary['spatially_unusable_response_evidence_count']}",
            f"- Unlocated clause traces: {summary['unlocated_clause_trace_count']}",
            f"- hard check issue count: {summary['hard_check_issue_count']}",
            "",
            "- Scope role conflicts: 0 when hard checks pass.",
            "- Point boundary duplicate links: 0 when hard checks pass.",
            "- Interval overlap conservation failures: 0 when hard checks pass.",
            "- Future leakage: 0 when hard checks pass.",
            "- Raw suspect PLC scope used for state cells: 0 by construction; cells are "
            "generated only from plc_daily_scope_v2 trusted scopes.",
            "- Stage 3B readiness: this artifact is ready for review before Stage 3B; "
            "it does not implement revision lineage.",
            "",
            "FORECAST evidence remains FORECAST when it enters DAILY_REVIEW cells.",
            "ResponseEvidence is linked as mechanical evidence only and is not "
            "interpreted as geology.",
        ]
        (self.out / "stage3a_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_source_snapshot(self) -> tuple[str, str]:
        rel_files = _collect_stage3a_source_files(self.repo)
        archive_path = self.out / "stage3a_source_snapshot.tar.gz"
        tree_digest = _hash_source_tree(self.repo, rel_files)
        with (
            archive_path.open("wb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gzipped,
            tarfile.open(fileobj=gzipped, mode="w") as archive,
        ):
            for rel in rel_files:
                path = self.repo / rel
                info = archive.gettarinfo(path, arcname=rel)
                info.mtime = 0
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
        source_hashes = {rel: sha256_file(self.repo / rel) for rel in rel_files}
        content = "".join(f"{digest}  {rel}\n" for rel, digest in sorted(source_hashes.items()))
        (self.out / "stage3a_source_hashes.sha256").write_text(content, encoding="utf-8")
        return sha256_file(archive_path), tree_digest

    def _write_formal_promotion_artifacts(self) -> None:
        if _repo_relative(self.repo, self.out) != _FORMAL_STAGE3A_DIR.as_posix():
            return
        candidate = self.repo / _CANDIDATE_STAGE3A_DIR
        old_v1 = self.repo / _OLD_STAGE3A_DIR
        promotion_rows, promotion_summary = _build_promotion_audit(candidate, self.out)
        identity_rows = _build_identity_audit(old_v1, self.out)
        path_rows = _build_formal_path_audit(self.repo)
        write_csv(
            self.out / "stage3a_v1_1_promotion_audit.csv",
            promotion_rows,
            _AUDIT_FIELDNAMES["stage3a_v1_1_promotion_audit.csv"],
        )
        write_json(self.out / "stage3a_v1_1_promotion_summary.json", promotion_summary)
        write_csv(
            self.out / "stage3a_version_identity_audit.csv",
            identity_rows,
            _AUDIT_FIELDNAMES["stage3a_version_identity_audit.csv"],
        )
        write_csv(
            self.out / "formal_stage3a_path_audit.csv",
            path_rows,
            _AUDIT_FIELDNAMES["formal_stage3a_path_audit.csv"],
        )
        write_csv(
            self.repo / "formal_stage3a_path_audit.csv",
            path_rows,
            _AUDIT_FIELDNAMES["formal_stage3a_path_audit.csv"],
        )
        _write_old_v1_superseded_marker(old_v1)

    def _hard_checks(
        self,
        *,
        data: dict[str, Any],
        cells: list[Any],
        daily_states: list[dict[str, Any]],
        versions: list[dict[str, Any]],
        geo_links: list[dict[str, Any]],
        response_links: list[dict[str, Any]],
        assertion_links: list[dict[str, Any]],
        unlocated_clauses: list[dict[str, Any]],
        unlocated_operational: list[dict[str, Any]],
        daily_located_point_operational: list[dict[str, Any]],
        state_reference_integrity_audit: list[dict[str, Any]],
        protected_hash_rows: list[dict[str, Any]],
        response_state_coverage_audit: list[dict[str, Any]],
        cell_scope_role_audit: list[dict[str, Any]],
        point_boundary_policy_audit: list[dict[str, Any]],
        interval_overlap_conservation_audit: list[dict[str, Any]],
        state_epistemic_integrity_audit: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        daily_by_date = {row["target_date"]: row for row in daily_states}
        version_by_id = {row["state_version_id"]: row for row in versions}
        all_daily_episode_ids = [
            episode_id for row in daily_states for episode_id in row["episode_ids"]
        ]
        all_daily_response_ids = [
            evidence_id for row in daily_states for evidence_id in row["response_evidence_ids"]
        ]
        unavailable_response_ids = {
            row["evidence_id"] for row in data["responses"] if not row["spatial_scope_usable"]
        }
        linked_response_ids = {row["response_evidence_id"] for row in response_links}
        linked_response_counts: dict[str, int] = defaultdict(int)
        for row in response_links:
            linked_response_counts[row["response_evidence_id"]] += 1
        coverage_ids = [row["response_evidence_id"] for row in response_state_coverage_audit]
        trusted_point_response_ids = {
            row["evidence_id"]
            for row in data["responses"]
            if row["spatial_scope_usable"]
            and (row.get("trusted_spatial_scope") or {}).get("kind") == "POINT"
        }
        trusted_point_link_counts = {
            response_id: linked_response_counts.get(response_id, 0)
            for response_id in trusted_point_response_ids
        }
        unlocated_response_ids = {row["response_evidence_id"] for row in unlocated_operational}
        located_point_daily_ids = {
            row["response_evidence_id"] for row in daily_located_point_operational
        }
        silent_unlinked_response_ids = {row["evidence_id"] for row in data["responses"]} - set(
            coverage_ids
        )
        non_not_assignment_ids = {
            row["assignment_id"]
            for row in data["primary_assignments"]
            if row["applicability_role"] != "NOT_APPLICABLE"
        }
        linked_assignment_ids = {row["assignment_id"] for row in geo_links}
        expected_cell_role = {
            "DAILY_REVIEW": "DAILY_REVIEW_CELL",
            "FORWARD_ATTENTION": "FORWARD_ATTENTION_CELL",
            "LOCAL_BACKGROUND": "LOCAL_BACKGROUND_CELL",
        }
        geological_role_mismatches = [
            row["link_id"]
            for row in geo_links
            if version_by_id[row["state_version_id"]]["cell_scope_role"]
            != expected_cell_role[row["applicability_role"]]
        ]
        response_role_mismatches = [
            row["link_id"]
            for row in response_links
            if version_by_id[row["state_version_id"]]["cell_scope_role"] != "DAILY_REVIEW_CELL"
        ]
        future_leakage_assignments = [
            row["assignment_id"]
            for row in data["primary_assignments"]
            if row["applicability_role"] != "NOT_APPLICABLE"
            and row.get("available_local_date")
            and str(row["available_local_date"]) > str(row["target_date"])
        ]
        observed_face_forward_links = [
            row["link_id"]
            for row in geo_links
            if row["epistemic_status"] == "OBSERVED"
            and row["evidence_type"] == "FACE_OBSERVATION"
            and row["applicability_role"] == "FORWARD_ATTENTION"
        ]
        duplicate_all_ids = duplicate_ids(
            [cell.cell_id for cell in cells],
            [row["daily_state_id"] for row in daily_states],
            [row["state_version_id"] for row in versions],
            [row["link_id"] for row in geo_links],
            [row["link_id"] for row in response_links],
            [row["trace_link_id"] for row in assertion_links],
        )
        checks = {
            "DAILY_STATE_COUNT_91": len(daily_states) == 91,
            "EPISODES_ALL_LINK_ONE_DAILY_STATE": (
                sorted(all_daily_episode_ids)
                == sorted(row["episode_id"] for row in data["episodes"]),
                f"{len(all_daily_episode_ids)} vs {len(data['episodes'])}",
            ),
            "RESPONSES_ALL_IN_DAILY_STATE": (
                sorted(all_daily_response_ids)
                == sorted(row["evidence_id"] for row in data["responses"]),
                f"{len(all_daily_response_ids)} vs {len(data['responses'])}",
            ),
            "UNUSABLE_RESPONSE_NOT_CELL_LINKED": not (
                unavailable_response_ids & linked_response_ids
            ),
            "RESPONSE_COVERAGE_ALL_5595": (
                len(response_state_coverage_audit) == len(data["responses"])
                and len(set(coverage_ids)) == len(data["responses"]),
                f"{len(response_state_coverage_audit)} rows, {len(set(coverage_ids))} unique",
            ),
            "RESPONSE_COVERAGE_ROWS_PASS": all(
                row["status"] == "PASS" for row in response_state_coverage_audit
            ),
            "RESPONSE_SILENT_UNLINKED_ZERO": not silent_unlinked_response_ids,
            "TRUSTED_POINT_NOT_SPATIALLY_UNLOCATED": not (
                trusted_point_response_ids & unlocated_response_ids
            ),
            "POINT_CELL_LINK_UNIQUE": all(
                count in {0, 1} for count in trusted_point_link_counts.values()
            ),
            "POINT_DAILY_ONLY_NOT_CELL_LINKED": not (located_point_daily_ids & linked_response_ids),
            "POINT_DAILY_ONLY_NOT_UNLOCATED": not (
                located_point_daily_ids & unlocated_response_ids
            ),
            "SPATIALLY_UNUSABLE_RESPONSE_COUNT_75": len(unavailable_response_ids) == 75,
            "GEO_LINK_ASSIGNMENTS_FROM_NON_NOT": linked_assignment_ids <= non_not_assignment_ids,
            "GEOLOGICAL_LINK_ROLE_MATCHES_CELL_ROLE": not geological_role_mismatches,
            "RESPONSE_LINKS_ONLY_DAILY_REVIEW_CELLS": not response_role_mismatches,
            "NO_SCOPE_ROLE_CONFLICTS": not any(
                row["status"] == "SCOPE_ROLE_CONFLICT" for row in cell_scope_role_audit
            ),
            "NO_ASSERTION_PRIMARY_LINKS": all(
                row["evidence_type"] != "REPORT_ASSERTION" for row in geo_links
            ),
            "UNLOCATED_CLAUSES_NOT_SPATIALIZED": len(unlocated_clauses)
            == len(data["clause_assignments"]),
            "POINT_EVIDENCE_NO_DUPLICATE_CELL": all(
                row["status"] == "PASS" for row in point_boundary_policy_audit
            ),
            "INTERVAL_OVERLAP_CONSERVED": all(
                row["status"] == "PASS" for row in interval_overlap_conservation_audit
            ),
            "EPISTEMIC_STATUS_PRESERVED": all(
                row["status"] == "PASS" for row in state_epistemic_integrity_audit
            ),
            "OBSERVED_FACE_POINT_NOT_FORWARD_ATTENTION": not observed_face_forward_links,
            "NO_FUTURE_LEAKAGE": not future_leakage_assignments,
            "NOV_06_NO_SPATIAL_STATE": not any(
                row["target_date"] == "2023-11-06" for row in versions
            )
            and daily_by_date["2023-11-06"]["episode_ids"],
            "NO_HISTORICAL_TRANSACTION_TIME_FABRICATED": all(
                row["historical_transaction_time"] is None
                and row["historical_transaction_time_known"] is False
                for row in versions
            ),
            "GLOBAL_IDS_UNIQUE": not duplicate_all_ids,
            "REFERENCES_CLOSED": all(
                row["status"] == "PASS" for row in state_reference_integrity_audit
            ),
            "STAGE2_FREEZE_HASHES_UNCHANGED": all(row["valid"] for row in protected_hash_rows),
        }
        return hard_check_rows(checks)

    def _reference_integrity_audit(
        self,
        *,
        cells: list[Any],
        daily_states: list[dict[str, Any]],
        versions: list[dict[str, Any]],
        geo_links: list[dict[str, Any]],
        response_links: list[dict[str, Any]],
        assertion_links: list[dict[str, Any]],
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        cell_ids = {cell.cell_id for cell in cells}
        daily_ids = {row["daily_state_id"] for row in daily_states}
        version_ids = {row["state_version_id"] for row in versions}
        assignment_ids = {row["assignment_id"] for row in data["primary_assignments"]}
        assignment_by_id = data["primary_assignment_by_id"]
        primary_evidence_by_id = data["primary_evidence_by_id"]
        document_by_id = data["geological_document_by_id"]
        source_span_ids = set(data["source_span_by_id"])
        response_ids = {row["evidence_id"] for row in data["responses"]}
        episode_ids = {row["episode_id"] for row in data["episodes"]}
        footprint_ids = {row["footprint_id"] for row in data["footprints"]}
        rows = []

        def add_ref(
            source_type: str,
            source_id: str,
            field_name: str,
            ref_id: str,
            valid: bool,
        ) -> None:
            rows.append(_ref_row(source_type, source_id, field_name, ref_id, valid))

        for version in versions:
            add_ref(
                "StateVersion",
                version["state_version_id"],
                "cell_id",
                version["cell_id"],
                version["cell_id"] in cell_ids,
            )
            add_ref(
                "StateVersion",
                version["state_version_id"],
                "daily_state_id",
                version["daily_state_id"],
                version["daily_state_id"] in daily_ids,
            )
        for link in geo_links:
            add_ref(
                "GeologicalLink",
                link["link_id"],
                "state_version_id",
                link["state_version_id"],
                link["state_version_id"] in version_ids,
            )
            add_ref(
                "GeologicalLink",
                link["link_id"],
                "assignment_id",
                link["assignment_id"],
                link["assignment_id"] in assignment_ids,
            )
            assignment = assignment_by_id.get(link["assignment_id"])
            evidence = primary_evidence_by_id.get(link["evidence_id"])
            document = document_by_id.get(link["document_id"])
            add_ref(
                "GeologicalLink",
                link["link_id"],
                "evidence_id",
                link["evidence_id"],
                evidence is not None,
            )
            add_ref(
                "GeologicalLink",
                link["link_id"],
                "document_id",
                link["document_id"],
                document is not None,
            )
            add_ref(
                "GeologicalLink",
                link["link_id"],
                "assignment_evidence_id",
                link["evidence_id"],
                assignment is not None and assignment["evidence_id"] == link["evidence_id"],
            )
            add_ref(
                "GeologicalLink",
                link["link_id"],
                "evidence_document_id",
                link["document_id"],
                evidence is not None and evidence["document_id"] == link["document_id"],
            )
            add_ref(
                "GeologicalLink",
                link["link_id"],
                "asset_id",
                link["asset_id"],
                evidence is not None
                and document is not None
                and evidence["asset_id"] == link["asset_id"]
                and document["asset_id"] == link["asset_id"],
            )
            add_ref(
                "GeologicalLink",
                link["link_id"],
                "epistemic_status",
                link["epistemic_status"],
                evidence is not None and evidence["epistemic_status"] == link["epistemic_status"],
            )
            add_ref(
                "GeologicalLink",
                link["link_id"],
                "evidence_type",
                link["evidence_type"],
                evidence is not None and evidence["evidence_type"] == link["evidence_type"],
            )
            for span_id in link["source_span_ids"]:
                add_ref(
                    "GeologicalLink",
                    link["link_id"],
                    "source_span_id",
                    span_id,
                    span_id in source_span_ids,
                )
        for link in response_links:
            add_ref(
                "ResponseLink",
                link["link_id"],
                "state_version_id",
                link["state_version_id"],
                link["state_version_id"] in version_ids,
            )
            add_ref(
                "ResponseLink",
                link["link_id"],
                "response_evidence_id",
                link["response_evidence_id"],
                link["response_evidence_id"] in response_ids,
            )
            add_ref(
                "ResponseLink",
                link["link_id"],
                "episode_id",
                link["episode_id"],
                link["episode_id"] in episode_ids,
            )
            add_ref(
                "ResponseLink",
                link["link_id"],
                "footprint_id",
                link["footprint_id"],
                link["footprint_id"] in footprint_ids,
            )
        for link in assertion_links:
            add_ref(
                "AssertionTraceLink",
                link["trace_link_id"],
                "state_version_id",
                link["state_version_id"],
                link["state_version_id"] in version_ids,
            )
        return rows

    def _fixed_case_audit(
        self,
        data: dict[str, Any],
        daily_states: list[dict[str, Any]],
        versions: list[dict[str, Any]],
        geo_links: list[dict[str, Any]],
        response_links: list[dict[str, Any]],
        unlocated_operational: list[dict[str, Any]],
        daily_located_point_operational: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows = []
        by_date_versions = self._group_by(versions, "target_date")
        by_date_geo = self._group_by(geo_links, "target_date")
        by_date_response = self._group_by(response_links, "target_date")
        by_date_daily = {row["target_date"]: row for row in daily_states}
        links_by_evidence = self._group_by(geo_links, "evidence_id")
        response_links_by_response = self._group_by(response_links, "response_evidence_id")
        episode_by_id = {row["episode_id"]: row for row in data["episodes"]}
        rows.append(
            _case(
                "2023_09_15_DAILY_STATE",
                "PASS" if "2023-09-15" in by_date_daily else "FAIL",
            )
        )
        rows.append(
            _case(
                "2023_11_05_NO_DYK1014_018_8_DAILY_REVIEW",
                "PASS"
                if not any(
                    row["applicability_role"] == "DAILY_REVIEW"
                    and row["overlap_start"] <= 1014018.8 <= row["overlap_end"]
                    for row in by_date_geo.get("2023-11-05", [])
                )
                else "FAIL",
            )
        )
        rows.append(
            _case(
                "2023_11_06_DAILY_STATE_EXISTS",
                "PASS" if "2023-11-06" in by_date_daily else "FAIL",
            )
        )
        rows.append(
            _case(
                "2023_11_06_NO_STATE_VERSIONS",
                "PASS" if not by_date_versions.get("2023-11-06") else "FAIL",
            )
        )
        rows.append(
            _case(
                "2023_11_06_NO_GEO_LINKS",
                "PASS" if not by_date_geo.get("2023-11-06") else "FAIL",
            )
        )
        rows.append(
            _case(
                "2023_11_06_NO_RESPONSE_LINKS",
                "PASS" if not by_date_response.get("2023-11-06") else "FAIL",
            )
        )
        rows.append(
            _case(
                "2023_11_09_RESTORED_LINKS",
                "PASS"
                if by_date_versions.get("2023-11-09") and by_date_response.get("2023-11-09")
                else "FAIL",
            )
        )
        rows.append(
            _case(
                "UNLOCATED_OPERATIONAL_PRESENT",
                "PASS" if len(unlocated_operational) > 0 else "FAIL",
            )
        )
        forecast_dual_role = any(
            any(
                row["epistemic_status"] == "FORECAST"
                and row["applicability_role"] == "FORWARD_ATTENTION"
                for row in rows_by_evidence
            )
            and any(
                row["epistemic_status"] == "FORECAST"
                and row["applicability_role"] == "DAILY_REVIEW"
                for row in rows_by_evidence
            )
            for rows_by_evidence in links_by_evidence.values()
        )
        rows.append(
            _case(
                "REAL_FORECAST_FORWARD_AND_DAILY_REVIEW",
                "PASS" if forecast_dual_role else "FAIL",
            )
        )
        current_interval_evidence = [
            row
            for row in data["primary_evidence"]
            if row["evidence_type"] == "FACE_OBSERVATION"
            and row["epistemic_status"] == "OBSERVED"
            and (row.get("spatial_scope") or {}).get("kind") == "INTERVAL"
            and abs(float(row["spatial_scope"]["start_chainage"]) - 1015610.0) <= 0.001
            and abs(float(row["spatial_scope"]["end_chainage"]) - 1015625.0) <= 0.001
        ]
        current_cell_count, current_length = _interval_grid_split_summary(1015610.0, 1015625.0)
        rows.append(
            _case(
                "DYK1015_610_625_CURRENT_EXCAVATED_INTERVAL_SPLIT",
                "PASS"
                if current_interval_evidence
                and current_cell_count >= 2
                and abs(current_length - 15.0) <= 0.001
                else "FAIL",
            )
        )
        boundary_point_link_counts: dict[str, int] = defaultdict(int)
        for row in response_links:
            if (
                row["trusted_overlap_kind"] == "POINT"
                and abs(row["trusted_overlap_start"] % self.state_config.cell_size_m) <= 0.001
            ):
                boundary_point_link_counts[row["response_evidence_id"]] += 1
        rows.append(
            _case(
                "REAL_POINT_RESPONSE_ON_10M_BOUNDARY_UNIQUE_LOWER_CELL",
                "PASS"
                if boundary_point_link_counts
                and all(count == 1 for count in boundary_point_link_counts.values())
                else "FAIL",
            )
        )
        hsp_segments = [
            row
            for row in data["primary_evidence"]
            if row["source_type"] == "SONIC_FORECAST"
            and row["evidence_type"] == "FORECAST_SEGMENT"
            and row["filename"].startswith("DyK1016+998.00_")
        ]
        hsp_bounds = sorted(
            (
                float(row["spatial_scope"]["start_chainage"]),
                float(row["spatial_scope"]["end_chainage"]),
            )
            for row in hsp_segments
        )
        rows.append(
            _case(
                "DYK1016_998_TO_DYK1017_098_HSP_CONTINUOUS_CELL_SPLIT",
                "PASS"
                if hsp_bounds
                == [
                    (1016998.0, 1017055.0),
                    (1017055.0, 1017090.0),
                    (1017090.0, 1017098.0),
                ]
                else "FAIL",
            )
        )
        zero_advance_point_linked = any(
            response_links_by_response.get(response["evidence_id"])
            and "ZERO_ADVANCE_DURING_EXCAVATION"
            in episode_by_id[response["episode_id"]].get("quality_flags", [])
            and (response.get("trusted_spatial_scope") or {}).get("kind") == "POINT"
            for response in data["responses"]
        )
        rows.append(
            _case(
                "ZERO_ADVANCE_POINT_EPISODE_LINKED_TO_DAILY_REVIEW_CELL",
                "PASS" if zero_advance_point_linked else "FAIL",
            )
        )
        boundary_daily_only = any(
            "POINT_AT_DAILY_REVIEW_LOWER_BOUNDARY" in row["reason_codes"]
            and row["response_evidence_id"] not in response_links_by_response
            for row in daily_located_point_operational
        )
        rows.append(
            _case(
                "LOWER_BOUNDARY_POINT_DAILY_ONLY_NOT_WRONG_CELL_ROLE",
                "PASS" if boundary_daily_only else "FAIL",
            )
        )
        return rows

    def _cell_grid_audit(self, cells: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "cell_id": cell.cell_id,
                "cell_index": cell.cell_index,
                "spatial_start": cell.spatial_start,
                "spatial_end": cell.spatial_end,
                "cell_size_m": cell.cell_size_m,
                "status": "PASS"
                if round(cell.spatial_end - cell.spatial_start, 6) == cell.cell_size_m
                else "FAIL",
            }
            for cell in cells
        ]

    def _daily_state_audit_row(self, daily_state: dict[str, Any]) -> dict[str, Any]:
        return {
            "target_date": daily_state["target_date"],
            "daily_state_id": daily_state["daily_state_id"],
            "spatial_scope_status": daily_state["spatial_scope_status"],
            "episode_count": len(daily_state["episode_ids"]),
            "response_evidence_count": len(daily_state["response_evidence_ids"]),
            "spatially_unusable_episode_count": len(daily_state["spatially_unusable_episode_ids"]),
        }

    def _cell_scope_role_rows(
        self,
        target_date: str,
        daily_state_id: str,
        cell_roles: dict[str, CellScopeRole],
        cells_by_id: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            {
                "target_date": target_date,
                "daily_state_id": daily_state_id,
                "cell_id": cell_id,
                "cell_index": cells_by_id[cell_id].cell_index,
                "cell_scope_role": role.value,
                "status": "PASS",
            }
            for cell_id, role in sorted(cell_roles.items())
        ]

    def _episode_daily_audit_rows(
        self,
        daily_state: dict[str, Any],
        episodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "target_date": daily_state["target_date"],
                "daily_state_id": daily_state["daily_state_id"],
                "episode_id": episode["episode_id"],
                "episode_source": episode.get("episode_source"),
                "status": "PASS" if episode.get("episode_source") == "PLC_INFERRED" else "FAIL",
            }
            for episode in episodes
        ]

    def _group_by_date(self, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        return self._group_by(rows, "target_date")

    def _group_by(self, rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            out[str(row[key])].append(row)
        return out


def _scope_span(scope: dict[str, Any] | None) -> float | None:
    if not scope:
        return None
    return round(float(scope["end_chainage"]) - float(scope["start_chainage"]), 6)


def _point_at_daily_lower_boundary(point: float, scope: dict[str, Any] | None) -> bool:
    if not scope:
        return False
    return abs(point - float(scope["start_chainage"])) <= 0.001


def _response_coverage_distribution(
    response_links: list[dict[str, Any]],
    unlocated_operational: list[dict[str, Any]],
    daily_located_point_operational: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "CELL_LINKED": len({row["response_evidence_id"] for row in response_links}),
        "LOCATED_POINT_DAILY_ONLY": len(
            {row["response_evidence_id"] for row in daily_located_point_operational}
        ),
        "SPATIALLY_UNLOCATED": len({row["response_evidence_id"] for row in unlocated_operational}),
    }


def _trusted_response_kind_distribution(responses: list[dict[str, Any]]) -> dict[str, int]:
    distribution: dict[str, int] = defaultdict(int)
    for response in responses:
        if not response["spatial_scope_usable"]:
            distribution["SPATIALLY_UNLOCATED"] += 1
            continue
        scope = response.get("trusted_spatial_scope") or {}
        distribution[str(scope.get("kind", "UNKNOWN"))] += 1
    return dict(sorted(distribution.items()))


def _trusted_episode_kind_distribution(footprints: list[dict[str, Any]]) -> dict[str, int]:
    distribution: dict[str, int] = defaultdict(int)
    for footprint in footprints:
        if not footprint["spatial_scope_usable"]:
            distribution["SPATIALLY_UNLOCATED"] += 1
            continue
        scope = footprint.get("trusted_spatial_scope") or {}
        distribution[str(scope.get("kind", "UNKNOWN"))] += 1
    return dict(sorted(distribution.items()))


def _primary_evidence_id_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        index[row["evidence_id"]] = row
        index[row["evidence_uid"]] = row
    return index


def _interval_grid_split_summary(
    start: float,
    end: float,
    cell_size: float = 10.0,
) -> tuple[int, float]:
    first = int(start // cell_size)
    last = int((end + cell_size - 0.000001) // cell_size) - 1
    lengths = []
    for index in range(first, last + 1):
        cell_start = index * cell_size
        cell_end = cell_start + cell_size
        length = min(end, cell_end) - max(start, cell_start)
        if length > 0:
            lengths.append(round(length, 6))
    return len(lengths), round(sum(lengths), 6)


def _collect_stage3a_source_files(repo: Path) -> list[str]:
    include_files: set[str] = {
        "configs/construction_state.yaml",
        "scripts/build_stage3a_initial_state.py",
        "pyproject.toml",
    }
    for lock_name in ["uv.lock", "poetry.lock", "pdm.lock", "requirements.lock"]:
        if (repo / lock_name).exists():
            include_files.add(lock_name)
    for root in [
        repo / "src/tbm_twin/state",
        repo / "tests/unit",
        repo / "tests/integration",
    ]:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            rel = path.relative_to(repo).as_posix()
            if root.name in {"unit", "integration"} and "state" not in path.name:
                continue
            include_files.add(rel)
    return sorted(rel for rel in include_files if (repo / rel).is_file())


def _hash_source_tree(repo: Path, rel_files: list[str]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for rel in rel_files:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(repo / rel).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _build_promotion_audit(
    candidate_dir: Path,
    formal_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(
        audit_type: str,
        object_key: str,
        field_name: str,
        candidate_value: Any,
        formal_value: Any,
        details: str = "",
    ) -> None:
        rows.append(
            {
                "audit_type": audit_type,
                "object_key": object_key,
                "field_name": field_name,
                "candidate_value": candidate_value,
                "formal_value": formal_value,
                "status": "PASS" if candidate_value == formal_value else "FAIL",
                "details": details,
            }
        )

    candidate_manifest = read_json(candidate_dir / "freeze_manifest.json")
    formal_manifest = read_json(formal_dir / "freeze_manifest.json")
    for field in [
        "cell_count",
        "daily_state_count",
        "initial_state_version_count",
        "geological_link_count",
        "response_link_count",
        "response_coverage_distribution",
        "geological_link_role_distribution",
        "geological_link_epistemic_distribution",
        "unlocated_operational_event_count",
        "daily_located_point_operational_event_count",
    ]:
        add(
            "manifest_semantic_count",
            "freeze_manifest",
            field,
            candidate_manifest[field],
            formal_manifest[field],
        )
    add(
        "manifest_semantic_count",
        "silent_unlinked",
        "response_evidence_count_covered",
        5595,
        sum(formal_manifest["response_coverage_distribution"].values()),
    )

    candidate_cells = _key_by(
        read_jsonl(candidate_dir / "construction_state_cells.jsonl"),
        "cell_id",
    )
    formal_cells = _key_by(read_jsonl(formal_dir / "construction_state_cells.jsonl"), "cell_id")
    add("cell_identity", "all_cells", "cell_id_set", sorted(candidate_cells), sorted(formal_cells))
    for cell_id, candidate_cell in candidate_cells.items():
        formal_cell = formal_cells.get(cell_id)
        add(
            "cell_geometry",
            cell_id,
            "geometry",
            _cell_geometry(candidate_cell),
            _cell_geometry(formal_cell) if formal_cell else None,
        )

    candidate_versions = _state_version_semantic_map(candidate_dir)
    formal_versions = _state_version_semantic_map(formal_dir)
    add(
        "state_version_semantic",
        "all_versions",
        "semantic_key_set",
        sorted(candidate_versions),
        sorted(formal_versions),
    )
    for key, candidate_value in candidate_versions.items():
        add(
            "state_version_semantic",
            key,
            "semantic_content",
            candidate_value,
            formal_versions.get(key),
        )
    semantic_difference_count = sum(1 for row in rows if row["status"] != "PASS")
    summary = {
        "candidate_dir": candidate_dir.as_posix(),
        "formal_dir": formal_dir.as_posix(),
        "semantic_difference_count": semantic_difference_count,
        "cell_count": formal_manifest["cell_count"],
        "daily_state_count": formal_manifest["daily_state_count"],
        "initial_state_version_count": formal_manifest["initial_state_version_count"],
        "geological_link_count": formal_manifest["geological_link_count"],
        "response_link_count": formal_manifest["response_link_count"],
        "response_coverage_distribution": formal_manifest["response_coverage_distribution"],
        "geological_link_role_distribution": formal_manifest["geological_link_role_distribution"],
        "geological_link_epistemic_distribution": formal_manifest[
            "geological_link_epistemic_distribution"
        ],
    }
    return rows, summary


def _build_identity_audit(old_v1_dir: Path, formal_dir: Path) -> list[dict[str, Any]]:
    old_versions = read_jsonl(old_v1_dir / "initial_construction_state_versions.jsonl")
    formal_versions = read_jsonl(formal_dir / "initial_construction_state_versions.jsonl")
    old_by_id = _key_by(old_versions, "state_version_id")
    formal_by_id = _key_by(formal_versions, "state_version_id")
    same_ids = sorted(set(old_by_id) & set(formal_by_id))
    changed_same_ids = [
        version_id
        for version_id in same_ids
        if _canonical_version_identity_content(old_by_id[version_id])
        != _canonical_version_identity_content(formal_by_id[version_id])
    ]
    formal_link_ids = _formal_link_ids(formal_dir)
    duplicate_formal_links = _duplicates(formal_link_ids)
    return [
        _identity_row("old_v1_state_version_count", len(old_versions), True),
        _identity_row("new_v1_1_state_version_count", len(formal_versions), True),
        _identity_row("same_state_version_id_count", len(same_ids), True),
        _identity_row(
            "same_state_version_id_with_changed_content_count",
            len(changed_same_ids),
            len(changed_same_ids) == 0,
            ",".join(changed_same_ids[:10]),
        ),
        _identity_row(
            "new_state_version_id_unique",
            len(set(formal_by_id)) == len(formal_versions),
            len(set(formal_by_id)) == len(formal_versions),
        ),
        _identity_row(
            "new_link_id_unique",
            len(duplicate_formal_links) == 0,
            len(duplicate_formal_links) == 0,
            ",".join(duplicate_formal_links[:10]),
        ),
    ]


def _build_formal_path_audit(repo: Path) -> list[dict[str, Any]]:
    rows = []
    files = [
        "README.md",
        "docs/architecture.md",
        "docs/STAGE2_FROZEN_PIPELINE.md",
    ]
    formal = _FORMAL_STAGE3A_DIR.as_posix()
    forbidden = [
        _OLD_STAGE3A_DIR.as_posix(),
        _CANDIDATE_STAGE3A_DIR.as_posix(),
    ]
    for rel in files:
        text = (repo / rel).read_text(encoding="utf-8")
        lines = text.splitlines()
        rows.append(
            {
                "path": rel,
                "reference": formal,
                "status": "PASS" if formal in text else "FAIL",
                "details": "formal Stage3A path must be documented",
            }
        )
        for item in forbidden:
            unsafe_lines = [
                line.strip()
                for index, line in enumerate(lines)
                if _line_contains_path(line, item)
                and not _line_marks_stage3a_path_forbidden(
                    f"{lines[index - 1] if index else ''} {line}"
                )
            ]
            rows.append(
                {
                    "path": rel,
                    "reference": item,
                    "status": "PASS" if not unsafe_lines else "FAIL",
                    "details": " | ".join(unsafe_lines[:3]),
                }
            )
    return rows


def _write_old_v1_superseded_marker(old_v1_dir: Path) -> None:
    if not old_v1_dir.exists():
        return
    marker = (
        "# SUPERSEDED_BY_STAGE3A_V1_1\n\n"
        "Status: POINT_RESPONSE_INCOMPLETE\n\n"
        "Do not use this Stage 3A v1 artifact as Stage 3B input. "
        "Use artifacts/stage3a_initial_epistemic_state_v1_1/ instead.\n"
    )
    (old_v1_dir / "SUPERSEDED_BY_STAGE3A_V1_1.md").write_text(marker, encoding="utf-8")


def _key_by(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row[key]): row for row in rows}


def _cell_geometry(cell: dict[str, Any] | None) -> dict[str, Any] | None:
    if cell is None:
        return None
    return {
        "alignment_id": cell["alignment_id"],
        "cell_index": cell["cell_index"],
        "spatial_start": cell["spatial_start"],
        "spatial_end": cell["spatial_end"],
        "cell_size_m": cell["cell_size_m"],
        "grid_origin_m": cell["grid_origin_m"],
        "chainage_direction": cell["chainage_direction"],
        "interval_convention": cell["interval_convention"],
        "point_boundary_policy": cell["point_boundary_policy"],
    }


def _state_version_semantic_map(directory: Path) -> dict[str, dict[str, Any]]:
    versions = read_jsonl(directory / "initial_construction_state_versions.jsonl")
    fields = [
        "target_date",
        "cell_id",
        "cell_scope_role",
        "episode_ids",
        "response_evidence_ids",
        "daily_review_evidence_ids",
        "forward_attention_evidence_ids",
        "local_background_evidence_ids",
        "observed_geological_evidence_ids",
        "forecast_geological_evidence_ids",
        "background_geological_evidence_ids",
        "source_assignment_ids",
    ]
    return {
        f"{row['target_date']}|{row['cell_id']}": {
            field: sorted(row[field]) if isinstance(row[field], list) else row[field]
            for field in fields
        }
        for row in versions
    }


def _canonical_version_identity_content(row: dict[str, Any]) -> dict[str, Any]:
    ignored = {
        "state_version_id",
        "daily_state_id",
        "reconstructed_at",
        "state_method_version",
        "source_geology_manifest_hash",
        "source_applicability_manifest_hash",
        "source_operational_manifest_hash",
    }
    return {
        key: sorted(value) if isinstance(value, list) else value
        for key, value in row.items()
        if key not in ignored
    }


def _formal_link_ids(formal_dir: Path) -> list[str]:
    link_ids: list[str] = []
    for filename, key in [
        ("state_geological_evidence_links.jsonl", "link_id"),
        ("state_response_evidence_links.jsonl", "link_id"),
        ("state_assertion_trace_links.jsonl", "trace_link_id"),
        ("daily_unlocated_clause_trace.jsonl", "trace_id"),
        ("daily_unlocated_operational_events.jsonl", "unlocated_event_id"),
        ("daily_located_point_operational_events.jsonl", "event_id"),
    ]:
        link_ids.extend(row[key] for row in read_jsonl(formal_dir / filename))
    return link_ids


def _duplicates(values: list[str]) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return sorted(value for value, count in counts.items() if count > 1)


def _identity_row(metric: str, value: Any, passed: bool, details: str = "") -> dict[str, Any]:
    return {
        "metric": metric,
        "value": value,
        "status": "PASS" if passed else "FAIL",
        "details": details,
    }


def _line_marks_stage3a_path_forbidden(line: str) -> bool:
    markers = [
        "禁止",
        "不得",
        "不要",
        "Do not",
        "do not",
        "SUPERSEDED",
        "superseded",
        "candidate",
        "旧",
        "禁止Stage3B读取",
    ]
    return any(marker in line for marker in markers)


def _line_contains_path(line: str, path: str) -> bool:
    pattern = re.escape(path) + r"(?=[/`'\"\s]|$)"
    return re.search(pattern, line) is not None


def _daily_cell_count_distribution(
    daily_states: list[dict[str, Any]],
    versions: list[dict[str, Any]],
) -> dict[str, int]:
    counts_by_date = {str(row["target_date"]): 0 for row in daily_states}
    for version in versions:
        counts_by_date[str(version["target_date"])] += 1
    distribution: dict[str, int] = defaultdict(int)
    for cell_count in counts_by_date.values():
        distribution[str(cell_count)] += 1
    return dict(sorted(distribution.items(), key=lambda item: int(item[0])))


def _repo_relative(repo: Path, path: Path) -> str:
    return path.relative_to(repo).as_posix() if path.is_relative_to(repo) else path.as_posix()


def _ref_row(
    object_type: str,
    object_id: str,
    reference_field: str,
    referenced_id: str,
    valid: bool,
) -> dict[str, Any]:
    return {
        "object_type": object_type,
        "object_id": object_id,
        "reference_field": reference_field,
        "referenced_id": referenced_id,
        "status": "PASS" if valid else "FAIL",
    }


def _case(case_id: str, status: str) -> dict[str, str]:
    return {"case_id": case_id, "status": status}
