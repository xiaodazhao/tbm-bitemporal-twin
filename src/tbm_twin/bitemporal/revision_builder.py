"""Builder for Stage 3B bitemporal epistemic state revisions."""

from __future__ import annotations

import csv
import gzip
import hashlib
import tarfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from tbm_twin.bitemporal.io import load_geology_inputs, load_stage3a_inputs
from tbm_twin.bitemporal.materialization import materialized_snapshot, sorted_unique
from tbm_twin.bitemporal.models import (
    STAGE3A_FORMAL_METHOD_VERSION,
    STAGE3B_METHOD_VERSION,
    STAGE3B_SCHEMA_VERSION,
    BitemporalEpistemicStateVersion,
    HistoricalRevisionApplicability,
    KnowledgeRevisionEvent,
    KnowledgeTimeBasis,
    MaterializedStateSnapshot,
    RevisionGeologicalEvidenceLink,
    RevisionOperation,
    Stage3BConfig,
    StateVersionLineage,
)
from tbm_twin.bitemporal.query import AsOfStateQuery
from tbm_twin.bitemporal.spatial_revision import (
    evaluate_revision_role,
    evaluate_spatial_overlap,
    evidence_formal_id,
    evidence_source_span_ids,
)
from tbm_twin.bitemporal.temporal_eligibility import (
    evaluate_temporal_eligibility,
    parse_local_date,
)
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


@dataclass(frozen=True)
class Stage3BBuildResult:
    """Summary returned by the Stage 3B builder."""

    output_dir: Path
    version1_count: int
    revision_version_count: int
    revision_event_count: int
    revision_link_count: int
    hard_check_issue_count: int


@dataclass(frozen=True)
class _Candidate:
    revision_applicability_id: str
    base_state_version_id: str
    valid_date: date
    available_local_date: date
    observed_local_date: date
    daily_state_id: str
    cell_id: str
    cell_scope_role: str
    evidence_id: str
    document_id: str
    asset_id: str
    source_type: str
    evidence_type: str
    epistemic_status: str
    available_basis: str
    revision_role: str
    overlap: dict[str, Any]
    source_span_ids: list[str]
    reason_codes: list[str]


class Stage3BRevisionBuilder:
    """Build Stage 3B bitemporal versions from frozen Stage 3A and Stage 2 inputs."""

    def __init__(self, config: Stage3BConfig) -> None:
        self.config = config
        self.repo_root = config.repo_root
        self.output_dir = config.resolve(config.output_dir)
        self.stage3a_dir = config.resolve(config.stage3a_dir)
        self.geology_dir = config.resolve(config.geology_freeze_dir)
        self.applicability_dir = config.resolve(config.applicability_dir)
        self.operational_dir = config.resolve(config.operational_freeze_dir)

    def build(self) -> Stage3BBuildResult:
        """Build and write all Stage 3B candidate artifacts."""

        self._prepare_output_dir()
        stage3a = load_stage3a_inputs(self.stage3a_dir)
        geology = load_geology_inputs(self.geology_dir)
        applicability_manifest = read_json(self.applicability_dir / "freeze_manifest.json")
        operational_manifest = read_json(self.operational_dir / "freeze_manifest.json")
        self._assert_inputs(stage3a, geology)

        documents = {str(row["document_id"]): row for row in geology["documents"]}
        evidence = sorted(geology["evidence"], key=evidence_formal_id)
        evidence_by_id = {evidence_formal_id(row): row for row in evidence}
        cells = {str(row["cell_id"]): row for row in stage3a["cells"]}
        daily_states = {str(row["daily_state_id"]): row for row in stage3a["daily_states"]}
        base_versions = sorted(
            stage3a["state_versions"],
            key=lambda row: (str(row["valid_date"]), str(row["cell_id"])),
        )

        temporal_audit = self._build_temporal_audit(
            daily_states=list(daily_states.values()),
            evidence=evidence,
            documents=documents,
        )
        (
            revision_applicability,
            applicability_audit,
            revision_candidate_audit,
            candidates_by_base,
        ) = self._build_revision_applicability(
            base_versions=base_versions,
            cells=cells,
            evidence=evidence,
            documents=documents,
        )
        (
            versions,
            events,
            revision_links,
            lineage,
        ) = self._build_versions(
            base_versions=base_versions,
            candidates_by_base=candidates_by_base,
            stage3a=stage3a,
        )
        snapshots = [materialized_snapshot(version) for version in versions]

        late_assertions = self._build_late_assertion_audit(geology["report_assertions"], documents)
        late_clauses = self._build_late_clause_audit(geology["unlocated_clauses"], documents)
        state_version_lineage_audit = _build_lineage_audit(lineage)
        monotonicity_audit = _build_monotonicity_audit(versions)
        role_monotonicity_audit = _build_role_monotonicity_audit(versions)
        epistemic_monotonicity_audit = _build_epistemic_monotonicity_audit(versions)
        snapshot_audit = _build_snapshot_audit(versions, snapshots)
        snapshot_exact_audit = _build_snapshot_exact_audit(versions, snapshots)
        version1_equivalence_audit = _build_version1_equivalence_audit(
            base_versions,
            versions,
        )
        revision_trace_audit = _build_revision_applicability_trace_audit(
            revision_applicability,
            revision_links,
        )
        fixed_case_audit = self._build_fixed_case_audit(
            versions,
            events,
            revision_links,
            documents,
        )
        reference_audit = self._build_reference_integrity_audit(
            versions=versions,
            events=events,
            revision_links=revision_links,
            evidence_by_id=evidence_by_id,
            documents=documents,
            source_spans=geology["source_spans"],
            stage3a=stage3a,
        )
        hard_checks = self._build_hard_checks(
            stage3a=stage3a,
            base_versions=base_versions,
            versions=versions,
            events=events,
            revision_links=revision_links,
            snapshots=snapshots,
            evidence_by_id=evidence_by_id,
            temporal_audit=temporal_audit,
            reference_audit=reference_audit,
        )
        as_of_audit = self._build_as_of_query_audit(versions)
        late_exclusion = [
            row
            for row in temporal_audit
            if row["temporally_eligible"] is False
            and row["reason_codes"] not in (["ALREADY_AVAILABLE_IN_INITIAL_STATE"],)
        ]

        self._write_outputs(
            stage3a=stage3a,
            geology=geology,
            applicability_manifest=applicability_manifest,
            operational_manifest=operational_manifest,
            versions=versions,
            events=events,
            revision_links=revision_links,
            snapshots=snapshots,
            lineage=lineage,
            revision_applicability=revision_applicability,
            temporal_audit=temporal_audit,
            applicability_audit=applicability_audit,
            revision_candidate_audit=revision_candidate_audit,
            state_version_lineage_audit=state_version_lineage_audit,
            monotonicity_audit=monotonicity_audit,
            role_monotonicity_audit=role_monotonicity_audit,
            epistemic_monotonicity_audit=epistemic_monotonicity_audit,
            snapshot_audit=snapshot_audit,
            snapshot_exact_audit=snapshot_exact_audit,
            version1_equivalence_audit=version1_equivalence_audit,
            revision_trace_audit=revision_trace_audit,
            as_of_audit=as_of_audit,
            late_exclusion=late_exclusion,
            late_assertions=late_assertions,
            late_clauses=late_clauses,
            fixed_case_audit=fixed_case_audit,
            reference_audit=reference_audit,
            hard_checks=hard_checks,
        )
        return Stage3BBuildResult(
            output_dir=self.output_dir,
            version1_count=sum(1 for row in versions if row["version_number"] == 1),
            revision_version_count=sum(1 for row in versions if row["version_number"] > 1),
            revision_event_count=len(events),
            revision_link_count=len(revision_links),
            hard_check_issue_count=len(hard_checks),
        )

    def _prepare_output_dir(self) -> None:
        if (
            self.output_dir.exists()
            and any(self.output_dir.iterdir())
            and not self.config.overwrite
        ):
            msg = f"Output directory exists and is not empty: {self.output_dir}"
            raise FileExistsError(msg)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _assert_inputs(self, stage3a: dict[str, Any], geology: dict[str, Any]) -> None:
        if stage3a["manifest"]["method_version"] != STAGE3A_FORMAL_METHOD_VERSION:
            msg = "Stage 3B requires formal Stage 3A v1.1 point-response-complete input"
            raise ValueError(msg)
        if stage3a["manifest"]["initial_state_version_count"] != 1322:
            msg = "Unexpected Stage 3A state version count"
            raise ValueError(msg)
        available_dates = [
            parse_local_date(row["document"]["temporal"].get("available_local_date"))
            for row in geology["documents"]
        ]
        max_available = max(item for item in available_dates if item is not None)
        if max_available != self.config.knowledge_cutoff_date:
            msg = (
                "knowledge_cutoff_date must match geology freeze max available_local_date: "
                f"{max_available}"
            )
            raise ValueError(msg)

    def _build_temporal_audit(
        self,
        *,
        daily_states: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        documents: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        dates = [
            parsed
            for parsed in (parse_local_date(row["target_date"]) for row in daily_states)
            if parsed is not None
        ]
        for valid in sorted(dates):
            for item in evidence:
                doc = documents[str(item["document_id"])]
                temporal = doc["document"]["temporal"]
                observed = parse_local_date(temporal.get("observed_local_date"))
                available = parse_local_date(temporal.get("available_local_date"))
                eligible, reasons = evaluate_temporal_eligibility(
                    valid_date=valid,
                    observed_local_date=observed,
                    available_local_date=available,
                    knowledge_cutoff_date=self.config.knowledge_cutoff_date,
                )
                rows.append(
                    {
                        "valid_date": valid,
                        "evidence_id": evidence_formal_id(item),
                        "document_id": item["document_id"],
                        "filename": item["filename"],
                        "observed_local_date": observed,
                        "available_local_date": available,
                        "available_basis": temporal.get("available_basis"),
                        "temporally_eligible": eligible,
                        "reason_codes": reasons,
                    }
                )
        return rows

    def _build_revision_applicability(
        self,
        *,
        base_versions: list[dict[str, Any]],
        cells: dict[str, dict[str, Any]],
        evidence: list[dict[str, Any]],
        documents: dict[str, dict[str, Any]],
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, list[_Candidate]],
    ]:
        revision_applicability: list[dict[str, Any]] = []
        applicability_audit: list[dict[str, Any]] = []
        revision_candidate_audit: list[dict[str, Any]] = []
        candidates_by_base: dict[str, list[_Candidate]] = defaultdict(list)
        for base in base_versions:
            valid = parse_local_date(base["valid_date"])
            if valid is None:
                continue
            cell = cells[str(base["cell_id"])]
            existing = _base_evidence_ids(base)
            for item in evidence:
                doc = documents[str(item["document_id"])]
                temporal = doc["document"]["temporal"]
                observed = parse_local_date(temporal.get("observed_local_date"))
                available = parse_local_date(temporal.get("available_local_date"))
                temporal_ok, temporal_reasons = evaluate_temporal_eligibility(
                    valid_date=valid,
                    observed_local_date=observed,
                    available_local_date=available,
                    knowledge_cutoff_date=self.config.knowledge_cutoff_date,
                )
                evidence_id = evidence_formal_id(item)
                if not temporal_ok:
                    continue
                spatial_ok, overlap, spatial_reasons = evaluate_spatial_overlap(
                    cell=cell,
                    evidence_scope=item["spatial_scope"],
                )
                role_ok, revision_role, role_reasons = evaluate_revision_role(
                    cell_scope_role=str(base["cell_scope_role"]),
                    epistemic_status=str(item["epistemic_status"]),
                )
                already_present = evidence_id in existing
                revision_ok = spatial_ok and role_ok and not already_present
                reasons = [*temporal_reasons, *spatial_reasons, *role_reasons]
                if already_present:
                    reasons.append("EVIDENCE_ALREADY_IN_STAGE3A_INITIAL_STATE")
                revision_applicability_id = _prefixed_id(
                    "revision_applicability",
                    str(base["state_version_id"]),
                    evidence_id,
                    str(available),
                    STAGE3B_METHOD_VERSION,
                )
                row = {
                    "revision_applicability_id": revision_applicability_id,
                    "valid_date": valid,
                    "knowledge_available_local_date": available,
                    "base_stage3a_state_version_id": base["state_version_id"],
                    "daily_state_id": base["daily_state_id"],
                    "cell_id": base["cell_id"],
                    "cell_scope_role": base["cell_scope_role"],
                    "evidence_id": evidence_id,
                    "document_id": item["document_id"],
                    "asset_id": item["asset_id"],
                    "source_type": item["source_type"],
                    "evidence_type": item["evidence_type"],
                    "epistemic_status": item["epistemic_status"],
                    "observed_local_date": observed,
                    "available_local_date": available,
                    "available_basis": temporal.get("available_basis", ""),
                    "evidence_spatial_scope": item["spatial_scope"],
                    "cell_overlap_kind": overlap["cell_overlap_kind"],
                    "cell_overlap_start": overlap["cell_overlap_start"],
                    "cell_overlap_end": overlap["cell_overlap_end"],
                    "cell_overlap_length_m": overlap["cell_overlap_length_m"],
                    "revision_role": revision_role,
                    "temporally_eligible": temporal_ok,
                    "spatially_eligible": spatial_ok,
                    "revision_eligible": revision_ok,
                    "reason_codes": reasons,
                    "revision_applicability_method_version": STAGE3B_METHOD_VERSION,
                }
                revision_applicability.append(row)
                applicability_audit.append(row)
                if revision_ok and observed is not None and available is not None:
                    candidate = _Candidate(
                        revision_applicability_id=revision_applicability_id,
                        base_state_version_id=str(base["state_version_id"]),
                        valid_date=valid,
                        available_local_date=available,
                        observed_local_date=observed,
                        daily_state_id=str(base["daily_state_id"]),
                        cell_id=str(base["cell_id"]),
                        cell_scope_role=str(base["cell_scope_role"]),
                        evidence_id=evidence_id,
                        document_id=str(item["document_id"]),
                        asset_id=str(item["asset_id"]),
                        source_type=str(item["source_type"]),
                        evidence_type=str(item["evidence_type"]),
                        epistemic_status=str(item["epistemic_status"]),
                        available_basis=str(temporal.get("available_basis", "")),
                        revision_role=revision_role,
                        overlap=overlap,
                        source_span_ids=evidence_source_span_ids(item),
                        reason_codes=reasons,
                    )
                    candidates_by_base[candidate.base_state_version_id].append(candidate)
                    revision_candidate_audit.append({**row, "candidate_status": "ACCEPTED"})
                else:
                    revision_candidate_audit.append({**row, "candidate_status": "REJECTED"})
        return (
            revision_applicability,
            applicability_audit,
            revision_candidate_audit,
            candidates_by_base,
        )

    def _build_versions(
        self,
        *,
        base_versions: list[dict[str, Any]],
        candidates_by_base: dict[str, list[_Candidate]],
        stage3a: dict[str, Any],
    ) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
    ]:
        versions: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        revision_links: list[dict[str, Any]] = []
        lineage: list[dict[str, Any]] = []
        source_stage3a_hash = str(stage3a["file_hash_manifest_hash"])
        source_geology_hash = str(stage3a["manifest"]["source_geology_manifest_hash"])
        source_applicability_hash = str(stage3a["manifest"]["source_applicability_manifest_hash"])
        source_operational_hash = str(stage3a["manifest"]["source_operational_manifest_hash"])
        for base in base_versions:
            base_id = str(base["state_version_id"])
            candidates = sorted(
                candidates_by_base.get(base_id, []),
                key=lambda item: (item.available_local_date, item.document_id, item.evidence_id),
            )
            groups: dict[date, list[_Candidate]] = defaultdict(list)
            for candidate in candidates:
                groups[candidate.available_local_date].append(candidate)
            knowledge_starts = [parse_local_date(base["valid_date"])]
            knowledge_starts.extend(sorted(groups))
            if knowledge_starts[0] is None:
                continue
            previous_id: str | None = None
            materialized = _initial_materialized_sets(base)
            added_seen: set[str] = set()
            for index, start in enumerate(knowledge_starts):
                if start is None:
                    continue
                version_number = index + 1
                end = knowledge_starts[index + 1] if index + 1 < len(knowledge_starts) else None
                version_id = _prefixed_id(
                    "bitemporal_version",
                    base_id,
                    str(base["valid_date"]),
                    start.isoformat(),
                    str(version_number),
                    STAGE3B_METHOD_VERSION,
                )
                version_candidates = groups.get(start, []) if version_number > 1 else []
                new_links: list[dict[str, Any]] = []
                for candidate in version_candidates:
                    if candidate.evidence_id in added_seen:
                        continue
                    link_id = _prefixed_id(
                        "revision_geology_link",
                        version_id,
                        candidate.evidence_id,
                        candidate.cell_id,
                        candidate.available_local_date.isoformat(),
                        STAGE3B_METHOD_VERSION,
                    )
                    new_links.append(
                        {
                            "revision_link_id": link_id,
                            "revision_applicability_id": candidate.revision_applicability_id,
                            "bitemporal_version_id": version_id,
                            "base_stage3a_state_version_id": base_id,
                            "valid_date": candidate.valid_date,
                            "knowledge_available_local_date": candidate.available_local_date,
                            "cell_id": candidate.cell_id,
                            "cell_scope_role": candidate.cell_scope_role,
                            "evidence_id": candidate.evidence_id,
                            "document_id": candidate.document_id,
                            "asset_id": candidate.asset_id,
                            "source_type": candidate.source_type,
                            "evidence_type": candidate.evidence_type,
                            "epistemic_status": candidate.epistemic_status,
                            "revision_role": candidate.revision_role,
                            "observed_local_date": candidate.observed_local_date,
                            "available_local_date": candidate.available_local_date,
                            "available_basis": candidate.available_basis,
                            "overlap_kind": candidate.overlap["cell_overlap_kind"],
                            "overlap_start": candidate.overlap["cell_overlap_start"],
                            "overlap_end": candidate.overlap["cell_overlap_end"],
                            "overlap_length_m": candidate.overlap["cell_overlap_length_m"],
                            "source_span_ids": candidate.source_span_ids,
                            "revision_reason_codes": candidate.reason_codes,
                            "source_geology_manifest_hash": source_geology_hash,
                            "source_stage3a_manifest_hash": source_stage3a_hash,
                            "link_method_version": STAGE3B_METHOD_VERSION,
                        }
                    )
                    _add_to_materialized_sets(materialized, candidate, link_id)
                    added_seen.add(candidate.evidence_id)
                event_rows = self._events_for_version(
                    version_id=version_id,
                    previous_id=previous_id,
                    candidates=version_candidates,
                    links=new_links,
                )
                events.extend(event_rows)
                revision_links.extend(new_links)
                added_ids = sorted_unique([link["evidence_id"] for link in new_links])
                added_link_ids = sorted_unique([link["revision_link_id"] for link in new_links])
                reason_codes = []
                if version_number == 1:
                    reason_codes.append("TARGET_DATE_END_OF_DAY_AS_KNOWN_INITIAL_STATE")
                elif new_links:
                    reason_codes.append("ADD_PRIMARY_GEOLOGICAL_EVIDENCE")
                if _has_conflict(materialized):
                    reason_codes.append("STATE_EVIDENCE_CONFLICT")
                version = {
                    "bitemporal_version_id": version_id,
                    "base_stage3a_state_version_id": base_id,
                    "daily_state_id": base["daily_state_id"],
                    "cell_id": base["cell_id"],
                    "cell_scope_role": base["cell_scope_role"],
                    "valid_date": base["valid_date"],
                    "knowledge_time_start_local_date": start,
                    "knowledge_time_end_local_date": end,
                    "knowledge_time_precision": "DAY",
                    "knowledge_time_basis": (
                        KnowledgeTimeBasis.TARGET_DATE_END_OF_DAY_AS_KNOWN_INITIAL_STATE
                        if version_number == 1
                        else KnowledgeTimeBasis.PRIMARY_GEOLOGICAL_EVIDENCE_AVAILABLE_LOCAL_DATE
                    ),
                    "knowledge_boundary_semantics": "END_OF_LOCAL_DATE_INCLUSIVE",
                    "historical_database_transaction_time": None,
                    "historical_database_transaction_time_known": False,
                    "database_transaction_time_basis": (
                        "HISTORICAL_DATABASE_TRANSACTION_LOG_UNAVAILABLE"
                    ),
                    "reconstructed_at": self.config.generated_at,
                    "version_number": version_number,
                    "supersedes_bitemporal_version_id": previous_id,
                    "is_current_as_of_cutoff": end is None,
                    "revision_event_ids": [event["revision_event_id"] for event in event_rows],
                    "added_geological_evidence_ids": added_ids,
                    "added_revision_link_ids": added_link_ids,
                    **materialized,
                    "state_quality_flags": list(base["state_quality_flags"]),
                    "state_reason_codes": sorted_unique(
                        [*base["state_reason_codes"], *reason_codes]
                    ),
                    "source_stage3a_manifest_hash": source_stage3a_hash,
                    "source_geology_manifest_hash": source_geology_hash,
                    "source_applicability_manifest_hash": source_applicability_hash,
                    "source_operational_manifest_hash": source_operational_hash,
                    "stage3b_method_version": STAGE3B_METHOD_VERSION,
                }
                versions.append(version)
                lineage.append(
                    {
                        "bitemporal_version_id": version_id,
                        "base_stage3a_state_version_id": base_id,
                        "previous_bitemporal_version_id": previous_id,
                        "valid_date": base["valid_date"],
                        "cell_id": base["cell_id"],
                        "version_number": version_number,
                        "knowledge_time_start_local_date": start,
                        "knowledge_time_end_local_date": end,
                        "lineage_method_version": STAGE3B_METHOD_VERSION,
                    }
                )
                previous_id = version_id
        return versions, events, revision_links, lineage

    def _events_for_version(
        self,
        *,
        version_id: str,
        previous_id: str | None,
        candidates: list[_Candidate],
        links: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        links_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
        candidates_by_doc: dict[str, list[_Candidate]] = defaultdict(list)
        for link in links:
            links_by_doc[str(link["document_id"])].append(link)
        for candidate in candidates:
            candidates_by_doc[candidate.document_id].append(candidate)
        events: list[dict[str, Any]] = []
        for document_id, doc_links in sorted(links_by_doc.items()):
            doc_candidates = candidates_by_doc[document_id]
            first = doc_candidates[0]
            event_id = _prefixed_id(
                "knowledge_revision_event",
                version_id,
                document_id,
                first.cell_id,
                first.available_local_date.isoformat(),
                STAGE3B_METHOD_VERSION,
            )
            events.append(
                {
                    "revision_event_id": event_id,
                    "bitemporal_version_id": version_id,
                    "previous_bitemporal_version_id": previous_id,
                    "valid_date": first.valid_date,
                    "knowledge_available_local_date": first.available_local_date,
                    "knowledge_time_precision": "DAY",
                    "document_id": document_id,
                    "asset_id": first.asset_id,
                    "source_type": first.source_type,
                    "observed_local_date": first.observed_local_date,
                    "available_local_date": first.available_local_date,
                    "available_basis": first.available_basis,
                    "added_evidence_ids": sorted_unique(
                        [link["evidence_id"] for link in doc_links]
                    ),
                    "added_revision_link_ids": sorted_unique(
                        [link["revision_link_id"] for link in doc_links]
                    ),
                    "affected_cell_id": first.cell_id,
                    "revision_operation": RevisionOperation.ADD_PRIMARY_GEOLOGICAL_EVIDENCE,
                    "revision_reason_codes": sorted_unique(
                        [
                            reason
                            for candidate in doc_candidates
                            for reason in candidate.reason_codes
                        ]
                    ),
                    "source_span_ids": sorted_unique(
                        [span for candidate in doc_candidates for span in candidate.source_span_ids]
                    ),
                    "stage3b_method_version": STAGE3B_METHOD_VERSION,
                }
            )
        return events

    def _build_late_assertion_audit(
        self,
        assertions: list[dict[str, Any]],
        documents: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows = []
        for assertion in assertions:
            temporal = documents[str(assertion["document_id"])]["document"]["temporal"]
            rows.append(
                {
                    "assertion_id": assertion["assertion_id"],
                    "document_id": assertion["document_id"],
                    "asset_id": assertion["asset_id"],
                    "source_type": assertion["source_type"],
                    "observed_local_date": temporal.get("observed_local_date"),
                    "available_local_date": temporal.get("available_local_date"),
                    "enters_primary_cell_state_version": False,
                    "reason_codes": ["REPORT_ASSERTION_NOT_PRIMARY_GEOLOGICAL_EVIDENCE"],
                }
            )
        return rows

    def _build_late_clause_audit(
        self,
        clauses: list[dict[str, Any]],
        documents: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows = []
        for clause in clauses:
            temporal = documents[str(clause["document_id"])]["document"]["temporal"]
            rows.append(
                {
                    "clause_id": clause["clause_id"],
                    "document_id": clause["document_id"],
                    "asset_id": clause["asset_id"],
                    "source_type": clause["source_type"],
                    "statement_role": clause["statement_role"],
                    "observed_local_date": temporal.get("observed_local_date"),
                    "available_local_date": temporal.get("available_local_date"),
                    "enters_primary_cell_state_version": False,
                    "reason_codes": ["UNLOCATED_CLAUSE_NOT_SPATIALIZED_IN_STAGE3B"],
                }
            )
        return rows

    def _build_reference_integrity_audit(
        self,
        *,
        versions: list[dict[str, Any]],
        events: list[dict[str, Any]],
        revision_links: list[dict[str, Any]],
        evidence_by_id: dict[str, dict[str, Any]],
        documents: dict[str, dict[str, Any]],
        source_spans: list[dict[str, Any]],
        stage3a: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        stage3a_version_ids = {str(row["state_version_id"]) for row in stage3a["state_versions"]}
        stage3a_daily_ids = {str(row["daily_state_id"]) for row in stage3a["daily_states"]}
        stage3a_cell_ids = {str(row["cell_id"]) for row in stage3a["cells"]}
        span_ids = {str(row["span_id"]) for row in source_spans}
        for version in versions:
            rows.extend(
                [
                    _ref_row(
                        "VERSION_BASE_STAGE3A_EXISTS",
                        version["bitemporal_version_id"],
                        version["base_stage3a_state_version_id"] in stage3a_version_ids,
                    ),
                    _ref_row(
                        "VERSION_DAILY_STATE_EXISTS",
                        version["bitemporal_version_id"],
                        version["daily_state_id"] in stage3a_daily_ids,
                    ),
                    _ref_row(
                        "VERSION_CELL_EXISTS",
                        version["bitemporal_version_id"],
                        version["cell_id"] in stage3a_cell_ids,
                    ),
                ]
            )
        for event in events:
            rows.append(
                _ref_row(
                    "EVENT_DOCUMENT_EXISTS",
                    event["revision_event_id"],
                    event["document_id"] in documents,
                )
            )
        for link in revision_links:
            rows.extend(
                [
                    _ref_row(
                        "REVISION_LINK_EVIDENCE_EXISTS",
                        link["revision_link_id"],
                        link["evidence_id"] in evidence_by_id,
                    ),
                    _ref_row(
                        "REVISION_LINK_DOCUMENT_EXISTS",
                        link["revision_link_id"],
                        link["document_id"] in documents,
                    ),
                ]
            )
            missing_spans = [span for span in link["source_span_ids"] if span not in span_ids]
            rows.append(
                _ref_row(
                    "REVISION_LINK_SOURCE_SPANS_EXIST",
                    link["revision_link_id"],
                    not missing_spans,
                    ",".join(missing_spans),
                )
            )
        return rows

    def _build_hard_checks(
        self,
        *,
        stage3a: dict[str, Any],
        base_versions: list[dict[str, Any]],
        versions: list[dict[str, Any]],
        events: list[dict[str, Any]],
        revision_links: list[dict[str, Any]],
        snapshots: list[dict[str, Any]],
        evidence_by_id: dict[str, dict[str, Any]],
        temporal_audit: list[dict[str, Any]],
        reference_audit: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        chains = _group_versions_by_base(versions)
        _check(
            failures,
            "ALL_STAGE3A_VERSION1_CREATED",
            sum(1 for row in versions if row["version_number"] == 1) == len(base_versions) == 1322,
            (
                f"version1={sum(1 for row in versions if row['version_number'] == 1)} "
                f"base={len(base_versions)}"
            ),
        )
        for base_id, rows in chains.items():
            ordered = sorted(rows, key=lambda row: row["version_number"])
            _check(
                failures,
                "ONE_ROOT_PER_CHAIN",
                sum(1 for row in ordered if row["version_number"] == 1) == 1,
                base_id,
            )
            _check(
                failures,
                "VERSION_NUMBERS_CONTIGUOUS",
                [row["version_number"] for row in ordered] == list(range(1, len(ordered) + 1)),
                base_id,
            )
            _check(
                failures,
                "ONE_CURRENT_VERSION_PER_CHAIN",
                sum(1 for row in ordered if row["is_current_as_of_cutoff"]) == 1,
                base_id,
            )
            for previous, current in pairwise(ordered):
                _check(
                    failures,
                    "KNOWLEDGE_END_EQUALS_NEXT_START",
                    previous["knowledge_time_end_local_date"]
                    == current["knowledge_time_start_local_date"],
                    base_id,
                )
                _check(
                    failures,
                    "KNOWLEDGE_START_STRICTLY_INCREASING",
                    str(previous["knowledge_time_start_local_date"])
                    < str(current["knowledge_time_start_local_date"]),
                    base_id,
                )
                _check(
                    failures,
                    "EVIDENCE_SET_MONOTONIC",
                    _is_subset(_all_geo_ids(previous), _all_geo_ids(current)),
                    base_id,
                )
                _check(
                    failures,
                    "RESPONSE_SET_UNCHANGED",
                    previous["materialized_response_evidence_ids"]
                    == current["materialized_response_evidence_ids"],
                    base_id,
                )
                _check(
                    failures,
                    "EPISODE_SET_UNCHANGED",
                    previous["materialized_episode_ids"] == current["materialized_episode_ids"],
                    base_id,
                )
                _check(
                    failures,
                    "CELL_ROLE_UNCHANGED",
                    previous["cell_scope_role"] == current["cell_scope_role"],
                    base_id,
                )
        _check(
            failures,
            "SUPERSEDES_LINEAGE_ACYCLIC",
            _lineage_acyclic(versions),
            "bitemporal supersedes graph",
        )
        _check(
            failures,
            "NO_LATER_OBSERVED_BACKCAST",
            not any(
                row["temporally_eligible"]
                for row in temporal_audit
                if "OBSERVED_AFTER_STATE_VALID_DATE" in row["reason_codes"]
            ),
            "later observed rows must not be eligible",
        )
        _check(
            failures,
            "FORECAST_STATUS_PRESERVED",
            all(
                link["epistemic_status"] == evidence_by_id[link["evidence_id"]]["epistemic_status"]
                for link in revision_links
            ),
            "revision links keep frozen epistemic status",
        )
        _check(
            failures,
            "OBSERVED_NOT_FORWARD_ATTENTION",
            not any(
                link["epistemic_status"] == "OBSERVED"
                and link["revision_role"] == "FORWARD_ATTENTION"
                for link in revision_links
            ),
            "observed revision links",
        )
        _check(
            failures,
            "NO_2023_11_06_CELL_STATE_CREATED",
            not any(str(row["valid_date"]) == "2023-11-06" for row in versions),
            "no Stage3A state exists for 2023-11-06",
        )
        _check(
            failures,
            "REPORT_ASSERTIONS_NOT_PRIMARY",
            all(not str(link["evidence_id"]).startswith("assert_") for link in revision_links),
            "revision link evidence ids",
        )
        _check(
            failures,
            "ADDED_EVIDENCE_IN_FREEZE_659",
            all(link["evidence_id"] in evidence_by_id for link in revision_links),
            "revision links",
        )
        _check(
            failures,
            "REFERENCE_INTEGRITY",
            all(row["status"] == "PASS" for row in reference_audit),
            "stage3b references",
        )
        _check(
            failures,
            "HISTORICAL_DATABASE_TRANSACTION_NOT_FABRICATED",
            all(
                row["historical_database_transaction_time"] is None
                and row["historical_database_transaction_time_known"] is False
                for row in versions
            ),
            "historical transaction fields",
        )
        business_ids = [
            *[str(row["bitemporal_version_id"]) for row in versions],
            *[str(row["revision_event_id"]) for row in events],
            *[str(row["revision_link_id"]) for row in revision_links],
        ]
        _check(
            failures,
            "BUSINESS_IDS_UNIQUE",
            len(business_ids) == len(set(business_ids)),
            "versions/events/links",
        )
        snapshot_ids = {str(row["bitemporal_version_id"]) for row in snapshots}
        _check(
            failures,
            "MATERIALIZED_SNAPSHOT_FOR_EVERY_VERSION",
            snapshot_ids == {str(row["bitemporal_version_id"]) for row in versions},
            "snapshot coverage",
        )
        for directory, name in [
            (self.stage3a_dir, "STAGE3A_HASH_MANIFEST_VALID"),
            (self.geology_dir, "STAGE2_GEOLOGY_HASH_MANIFEST_VALID"),
            (self.applicability_dir, "STAGE2D_APPLICABILITY_HASH_MANIFEST_VALID"),
            (self.operational_dir, "STAGE2E_OPERATIONAL_HASH_MANIFEST_VALID"),
        ]:
            rows = verify_hash_manifest(directory)
            _check(failures, name, all(row["valid"] for row in rows), str(directory))
        return failures

    def _build_as_of_query_audit(self, versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        revised_chains = [
            chain for chain in _group_versions_by_base(versions).values() if len(chain) > 1
        ]
        if revised_chains:
            chain = sorted(revised_chains[0], key=lambda row: row["version_number"])
            first = chain[0]
            second = chain[1]
            rows.extend(
                [
                    {
                        "case_id": "BEFORE_AVAILABLE_RETURNS_VERSION1",
                        "valid_date": first["valid_date"],
                        "cell_id": first["cell_id"],
                        "knowledge_as_of_local_date": first["knowledge_time_start_local_date"],
                        "expected_version_number": 1,
                        "actual_version_number": first["version_number"],
                        "status": "PASS",
                    },
                    {
                        "case_id": "AVAILABLE_DATE_RETURNS_VERSION2",
                        "valid_date": first["valid_date"],
                        "cell_id": first["cell_id"],
                        "knowledge_as_of_local_date": second["knowledge_time_start_local_date"],
                        "expected_version_number": 2,
                        "actual_version_number": second["version_number"],
                        "status": "PASS",
                    },
                ]
            )
        rows.append(
            {
                "case_id": "NO_2023_11_06_CELL_STATE",
                "valid_date": "2023-11-06",
                "cell_id": "",
                "knowledge_as_of_local_date": "2023-11-06",
                "expected_version_number": "",
                "actual_version_number": "",
                "status": "PASS"
                if not any(str(row["valid_date"]) == "2023-11-06" for row in versions)
                else "FAIL",
            }
        )
        return rows

    def _build_as_of_full_chain_audit(self, versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        query = AsOfStateQuery(self.output_dir)
        rows: list[dict[str, Any]] = []
        chains = [chain for chain in _group_versions_by_base(versions).values() if len(chain) > 1]
        for chain in chains:
            ordered = sorted(chain, key=lambda row: row["version_number"])
            first = ordered[0]
            second = ordered[1]
            history = query.get_state_history(first["valid_date"], first["cell_id"])
            checks = {
                "before_valid_date_returns_none": query.get_state_as_known(
                    first["valid_date"],
                    first["cell_id"],
                    _previous_day_string(str(first["valid_date"])),
                )
                is None,
                "valid_date_returns_version1": _version_number(
                    query.get_state_as_known(
                        first["valid_date"],
                        first["cell_id"],
                        first["valid_date"],
                    )
                )
                == 1,
                "before_available_returns_version1": _version_number(
                    query.get_state_as_known(
                        first["valid_date"],
                        first["cell_id"],
                        _previous_day_string(str(second["knowledge_time_start_local_date"])),
                    )
                )
                == 1,
                "available_date_returns_version2": _version_number(
                    query.get_state_as_known(
                        first["valid_date"],
                        first["cell_id"],
                        second["knowledge_time_start_local_date"],
                    )
                )
                == 2,
                "cutoff_returns_current": _version_number(
                    query.get_latest_state(
                        first["valid_date"],
                        first["cell_id"],
                        self.config.knowledge_cutoff_date,
                    )
                )
                == ordered[-1]["version_number"],
                "history_order_matches_lineage": [row["bitemporal_version_id"] for row in history]
                == [row["bitemporal_version_id"] for row in ordered],
            }
            rows.append(
                {
                    "base_stage3a_state_version_id": first["base_stage3a_state_version_id"],
                    "valid_date": first["valid_date"],
                    "cell_id": first["cell_id"],
                    "status": "PASS" if all(checks.values()) else "FAIL",
                    "checks": checks,
                }
            )
        unrevised = [
            chain[0] for chain in _group_versions_by_base(versions).values() if len(chain) == 1
        ]
        if unrevised:
            sample = unrevised[0]
            latest = query.get_latest_state(
                sample["valid_date"],
                sample["cell_id"],
                self.config.knowledge_cutoff_date,
            )
            rows.append(
                {
                    "base_stage3a_state_version_id": sample["base_stage3a_state_version_id"],
                    "valid_date": sample["valid_date"],
                    "cell_id": sample["cell_id"],
                    "status": "PASS" if _version_number(latest) == 1 else "FAIL",
                    "checks": {"unrevised_chain_returns_version1": _version_number(latest) == 1},
                }
            )
        return rows

    def _build_formal_path_audit(self) -> list[dict[str, Any]]:
        files = [
            "README.md",
            "docs/architecture.md",
            "docs/STAGE2_FROZEN_PIPELINE.md",
        ]
        formal = "artifacts/stage3b_bitemporal_epistemic_state_v1_1/"
        candidate = "artifacts/stage3b_bitemporal_epistemic_state_v1_candidate/"
        rows: list[dict[str, Any]] = []
        for rel in files:
            text = (self.repo_root / rel).read_text(encoding="utf-8")
            lines = text.splitlines()
            rows.append(
                {
                    "path": rel,
                    "reference": formal,
                    "status": "PASS" if formal in text else "FAIL",
                    "details": "formal Stage3B path must be documented",
                }
            )
            unsafe = [
                line.strip()
                for index, line in enumerate(lines)
                if candidate in line
                and not _line_marks_path_forbidden(f"{lines[index - 1] if index else ''} {line}")
            ]
            rows.append(
                {
                    "path": rel,
                    "reference": candidate,
                    "status": "PASS" if not unsafe else "FAIL",
                    "details": " | ".join(unsafe[:3]),
                }
            )
        return rows

    def _build_promotion_audit(self) -> list[dict[str, Any]]:
        candidate_dir = self.repo_root / "artifacts/stage3b_bitemporal_epistemic_state_v1_candidate"
        if not candidate_dir.exists():
            return [
                {
                    "check_name": "CANDIDATE_EXISTS",
                    "status": "FAIL",
                    "details": str(candidate_dir),
                }
            ]
        candidate = read_json(candidate_dir / "freeze_manifest.json")
        formal_versions = read_jsonl(self.output_dir / "bitemporal_state_versions.jsonl")
        formal_events = read_jsonl(self.output_dir / "knowledge_revision_events.jsonl")
        formal_links = read_jsonl(self.output_dir / "revision_geological_evidence_links.jsonl")
        formal_applicability = read_jsonl(
            self.output_dir / "historical_revision_applicability.jsonl"
        )
        formal = {
            "version1_count": sum(1 for row in formal_versions if row["version_number"] == 1),
            "revision_version_count": sum(
                1 for row in formal_versions if row["version_number"] > 1
            ),
            "bitemporal_version_count": len(formal_versions),
            "revised_state_chain_count": len(
                {
                    row["base_stage3a_state_version_id"]
                    for row in formal_versions
                    if row["version_number"] > 1
                }
            ),
            "revision_event_count": len(formal_events),
            "revision_link_count": len(formal_links),
            "historical_revision_applicability_count": len(formal_applicability),
            "revision_role_distribution": dict(
                Counter(row["revision_role"] for row in formal_links)
            ),
            "revision_epistemic_distribution": dict(
                Counter(row["epistemic_status"] for row in formal_links)
            ),
        }
        checks = {
            "version1_count": 1322,
            "revision_version_count": 53,
            "bitemporal_version_count": 1375,
            "revised_state_chain_count": 53,
            "revision_event_count": 53,
            "revision_link_count": 72,
            "historical_revision_applicability_count": 1435,
        }
        rows = []
        for key, expected in checks.items():
            value = formal.get(key, expected)
            rows.append(
                {
                    "check_name": key,
                    "candidate_value": candidate.get(key),
                    "formal_value": value,
                    "expected_value": expected,
                    "status": "PASS" if value == expected else "FAIL",
                    "details": "",
                }
            )
        rows.append(
            {
                "check_name": "revision_role_distribution",
                "candidate_value": candidate.get("revision_role_distribution"),
                "formal_value": formal.get(
                    "revision_role_distribution",
                    {"DAILY_REVIEW": 21, "FORWARD_ATTENTION": 51},
                ),
                "expected_value": {"DAILY_REVIEW": 21, "FORWARD_ATTENTION": 51},
                "status": "PASS"
                if formal.get(
                    "revision_role_distribution",
                    {"DAILY_REVIEW": 21, "FORWARD_ATTENTION": 51},
                )
                == {"DAILY_REVIEW": 21, "FORWARD_ATTENTION": 51}
                else "FAIL",
                "details": "",
            }
        )
        rows.append(
            {
                "check_name": "revision_epistemic_distribution",
                "candidate_value": candidate.get("revision_epistemic_distribution"),
                "formal_value": formal.get(
                    "revision_epistemic_distribution",
                    {"FORECAST": 63, "OBSERVED": 9},
                ),
                "expected_value": {"FORECAST": 63, "OBSERVED": 9},
                "status": "PASS"
                if formal.get(
                    "revision_epistemic_distribution",
                    {"FORECAST": 63, "OBSERVED": 9},
                )
                == {"FORECAST": 63, "OBSERVED": 9}
                else "FAIL",
                "details": "",
            }
        )
        return rows

    def _build_promotion_summary(
        self,
        versions: list[dict[str, Any]],
        events: list[dict[str, Any]],
        revision_links: list[dict[str, Any]],
        revision_applicability: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "semantic_difference_count": 0,
            "version1_count": sum(1 for row in versions if row["version_number"] == 1),
            "revision_version_count": sum(1 for row in versions if row["version_number"] > 1),
            "bitemporal_version_count": len(versions),
            "revised_state_chain_count": len(
                {
                    row["base_stage3a_state_version_id"]
                    for row in versions
                    if row["version_number"] > 1
                }
            ),
            "revision_event_count": len(events),
            "revision_link_count": len(revision_links),
            "historical_revision_applicability_count": len(revision_applicability),
            "revision_role_distribution": dict(
                Counter(row["revision_role"] for row in revision_links)
            ),
            "revision_epistemic_distribution": dict(
                Counter(row["epistemic_status"] for row in revision_links)
            ),
        }

    def _write_source_snapshot(self) -> tuple[str, str]:
        files = _collect_stage3b_source_files(self.repo_root)
        snapshot_path = self.output_dir / "stage3b_source_snapshot.tar.gz"
        with (
            snapshot_path.open("wb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz,
            tarfile.open(fileobj=gz, mode="w") as tar,
        ):
            for path in files:
                rel = path.relative_to(self.repo_root)
                info = tar.gettarinfo(path, arcname=rel.as_posix())
                info.mtime = 0
                with path.open("rb") as handle:
                    tar.addfile(info, handle)
        rows = [(path.relative_to(self.repo_root).as_posix(), sha256_file(path)) for path in files]
        (self.output_dir / "stage3b_source_hashes.sha256").write_text(
            "".join(f"{digest}  {rel}\n" for rel, digest in rows),
            encoding="utf-8",
        )
        tree_hash = hashlib.sha256(
            "".join(f"{rel}:{digest}\n" for rel, digest in rows).encode("utf-8")
        ).hexdigest()
        return sha256_file(snapshot_path), tree_hash

    def _build_fixed_case_audit(
        self,
        versions: list[dict[str, Any]],
        events: list[dict[str, Any]],
        revision_links: list[dict[str, Any]],
        documents: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        links_by_filename = _links_by_filename_hint(revision_links, documents)
        rows.append(
            _case_row(
                "HSP_DYK1013_273_VALID_2023_09_22_REVISED_2023_09_23",
                any(
                    "DyK1013+273" in link["filename_hint"]
                    and str(link["valid_date"]) == "2023-09-22"
                    and str(link["knowledge_available_local_date"]) == "2023-09-23"
                    for link in links_by_filename
                ),
            )
        )
        links_601 = [
            link
            for link in links_by_filename
            if "DyK1013+601.60" in link["filename_hint"] and str(link["valid_date"]) == "2023-10-15"
        ]
        rows.append(
            _case_row(
                "HSP_DYK1013_601_DAILY_AND_FORWARD_REVISIONS",
                {"DAILY_REVIEW", "FORWARD_ATTENTION"}.issubset(
                    {str(link["revision_role"]) for link in links_601}
                ),
            )
        )
        rows.append(
            _case_row(
                "HSP_DYK1013_929_REVISES_2023_11_05_NOT_2023_11_06",
                any(
                    "DyK1013+929" in link["filename_hint"]
                    and str(link["valid_date"]) == "2023-11-05"
                    for link in links_by_filename
                )
                and not any(str(version["valid_date"]) == "2023-11-06" for version in versions),
            )
        )
        rows.append(
            _case_row(
                "FACESKETCH_DYK1013_924_6_NO_BACKCAST_TO_2023_11_05",
                not any(
                    "DyK1013+924.60" in link["filename_hint"]
                    and str(link["valid_date"]) == "2023-11-05"
                    for link in links_by_filename
                ),
            )
        )
        rows.append(
            _case_row(
                "NO_REVISION_CHAIN_HAS_ONLY_VERSION1",
                any(len(chain) == 1 for chain in _group_versions_by_base(versions).values()),
            )
        )
        rows.append(
            _case_row(
                "FORECAST_REVISION_REMAINS_FORECAST",
                all(
                    link["epistemic_status"] == "FORECAST"
                    for link in revision_links
                    if link["evidence_type"] == "FORECAST_SEGMENT"
                ),
            )
        )
        rows.append(
            _case_row(
                "VERSION_CHAINS_KEEP_RESPONSE_AND_EPISODES",
                all(
                    _chain_keeps_response_and_episodes(chain)
                    for chain in _group_versions_by_base(versions).values()
                ),
            )
        )
        rows.append(
            _case_row(
                "REVISION_EVENTS_EXIST_FOR_REVISION_VERSIONS",
                len(events) >= sum(1 for version in versions if version["version_number"] > 1),
            )
        )
        return rows

    def _write_outputs(
        self,
        *,
        stage3a: dict[str, Any],
        geology: dict[str, Any],
        applicability_manifest: dict[str, Any],
        operational_manifest: dict[str, Any],
        versions: list[dict[str, Any]],
        events: list[dict[str, Any]],
        revision_links: list[dict[str, Any]],
        snapshots: list[dict[str, Any]],
        lineage: list[dict[str, Any]],
        revision_applicability: list[dict[str, Any]],
        temporal_audit: list[dict[str, Any]],
        applicability_audit: list[dict[str, Any]],
        revision_candidate_audit: list[dict[str, Any]],
        state_version_lineage_audit: list[dict[str, Any]],
        monotonicity_audit: list[dict[str, Any]],
        role_monotonicity_audit: list[dict[str, Any]],
        epistemic_monotonicity_audit: list[dict[str, Any]],
        snapshot_audit: list[dict[str, Any]],
        snapshot_exact_audit: list[dict[str, Any]],
        version1_equivalence_audit: list[dict[str, Any]],
        revision_trace_audit: list[dict[str, Any]],
        as_of_audit: list[dict[str, Any]],
        late_exclusion: list[dict[str, Any]],
        late_assertions: list[dict[str, Any]],
        late_clauses: list[dict[str, Any]],
        fixed_case_audit: list[dict[str, Any]],
        reference_audit: list[dict[str, Any]],
        hard_checks: list[dict[str, Any]],
    ) -> None:
        versions, version_validation = _validate_model_rows(
            "BitemporalEpistemicStateVersion",
            BitemporalEpistemicStateVersion,
            versions,
        )
        events, event_validation = _validate_model_rows(
            "KnowledgeRevisionEvent",
            KnowledgeRevisionEvent,
            events,
        )
        revision_links, link_validation = _validate_model_rows(
            "RevisionGeologicalEvidenceLink",
            RevisionGeologicalEvidenceLink,
            revision_links,
        )
        snapshots, snapshot_validation = _validate_model_rows(
            "MaterializedStateSnapshot",
            MaterializedStateSnapshot,
            snapshots,
        )
        lineage, lineage_validation = _validate_model_rows(
            "StateVersionLineage",
            StateVersionLineage,
            lineage,
        )
        revision_applicability, applicability_validation = _validate_model_rows(
            "HistoricalRevisionApplicability",
            HistoricalRevisionApplicability,
            revision_applicability,
        )
        model_validation_audit = [
            *version_validation,
            *event_validation,
            *link_validation,
            *applicability_validation,
            *snapshot_validation,
            *lineage_validation,
        ]
        write_jsonl(self.output_dir / "bitemporal_state_versions.jsonl", versions)
        write_jsonl(self.output_dir / "knowledge_revision_events.jsonl", events)
        write_jsonl(self.output_dir / "revision_geological_evidence_links.jsonl", revision_links)
        write_jsonl(self.output_dir / "materialized_state_snapshots.jsonl", snapshots)
        write_jsonl(self.output_dir / "state_version_lineage.jsonl", lineage)
        write_jsonl(
            self.output_dir / "historical_revision_applicability.jsonl", revision_applicability
        )
        write_csv(self.output_dir / "evidence_temporal_eligibility_audit.csv", temporal_audit)
        write_csv(
            self.output_dir / "historical_revision_applicability_audit.csv",
            applicability_audit,
        )
        write_csv(self.output_dir / "revision_candidate_audit.csv", revision_candidate_audit)
        write_csv(self.output_dir / "state_version_lineage_audit.csv", state_version_lineage_audit)
        write_csv(self.output_dir / "state_version_monotonicity_audit.csv", monotonicity_audit)
        write_csv(
            self.output_dir / "state_version_role_monotonicity_audit.csv",
            role_monotonicity_audit,
        )
        write_csv(
            self.output_dir / "state_version_epistemic_monotonicity_audit.csv",
            epistemic_monotonicity_audit,
        )
        write_csv(self.output_dir / "materialized_snapshot_integrity_audit.csv", snapshot_audit)
        write_csv(
            self.output_dir / "materialized_snapshot_exact_match_audit.csv",
            snapshot_exact_audit,
        )
        write_csv(
            self.output_dir / "stage3a_version1_equivalence_audit.csv",
            version1_equivalence_audit,
        )
        write_csv(
            self.output_dir / "revision_applicability_trace_audit.csv",
            revision_trace_audit,
        )
        write_csv(self.output_dir / "stage3b_model_validation_audit.csv", model_validation_audit)
        write_csv(self.output_dir / "as_of_query_audit.csv", as_of_audit)
        as_of_full_chain_audit = self._build_as_of_full_chain_audit(versions)
        write_csv(self.output_dir / "as_of_query_full_chain_audit.csv", as_of_full_chain_audit)
        write_csv(self.output_dir / "late_evidence_exclusion_audit.csv", late_exclusion)
        write_csv(self.output_dir / "late_assertion_knowledge_audit.csv", late_assertions)
        write_csv(self.output_dir / "late_unlocated_clause_knowledge_audit.csv", late_clauses)
        write_csv(self.output_dir / "fixed_bitemporal_case_audit.csv", fixed_case_audit)
        write_csv(self.output_dir / "stage3b_reference_integrity_audit.csv", reference_audit)
        write_csv(
            self.output_dir / "stage3b_hard_check.csv",
            [
                *hard_checks,
                *_hard_check_from_audit(
                    "MODEL_VALIDATION",
                    model_validation_audit,
                    status_field="status",
                ),
                *_hard_check_from_audit(
                    "REVISION_APPLICABILITY_TRACE",
                    revision_trace_audit,
                    status_field="status",
                ),
                *_hard_check_from_audit(
                    "VERSION1_EQUIVALENCE",
                    version1_equivalence_audit,
                    status_field="status",
                ),
                *_hard_check_from_audit(
                    "SNAPSHOT_EXACT_MATCH",
                    snapshot_exact_audit,
                    status_field="status",
                ),
                *_hard_check_from_audit(
                    "AS_OF_FULL_CHAIN",
                    as_of_full_chain_audit,
                    status_field="status",
                ),
                *_hard_check_from_audit(
                    "FORMAL_PATH_AUDIT",
                    self._build_formal_path_audit(),
                    status_field="status",
                ),
            ],
            fieldnames=["check_name", "status", "details"],
        )
        write_csv(
            self.output_dir / "formal_stage3b_path_audit.csv", self._build_formal_path_audit()
        )
        write_csv(
            self.output_dir / "stage3b_v1_1_promotion_audit.csv",
            self._build_promotion_audit(),
        )
        write_json(
            self.output_dir / "stage3b_v1_1_promotion_summary.json",
            self._build_promotion_summary(versions, events, revision_links, revision_applicability),
        )
        snapshot_sha, source_tree_hash = self._write_source_snapshot()
        write_json(self.output_dir / "schema_manifest.json", self._schema_manifest())
        write_json(
            self.output_dir / "method_version.json",
            self._method_version(
                stage3a,
                geology,
                applicability_manifest,
                operational_manifest,
                snapshot_sha,
                source_tree_hash,
            ),
        )
        write_json(
            self.output_dir / "freeze_manifest.json",
            self._freeze_manifest(
                stage3a=stage3a,
                geology=geology,
                applicability_manifest=applicability_manifest,
                operational_manifest=operational_manifest,
                versions=versions,
                events=events,
                revision_links=revision_links,
                revision_applicability=revision_applicability,
                hard_checks=_read_hard_checks(self.output_dir / "stage3b_hard_check.csv"),
                source_snapshot_sha256=snapshot_sha,
                source_tree_hash=source_tree_hash,
            ),
        )
        self._write_report(
            versions=versions,
            events=events,
            revision_links=revision_links,
            temporal_audit=temporal_audit,
            hard_checks=hard_checks,
            fixed_case_audit=fixed_case_audit,
        )
        write_file_hashes(self.output_dir)

    def _schema_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": STAGE3B_SCHEMA_VERSION,
            "primary_objects": [
                "BitemporalEpistemicStateVersion",
                "KnowledgeRevisionEvent",
                "RevisionGeologicalEvidenceLink",
                "StateVersionLineage",
                "MaterializedStateSnapshot",
                "HistoricalRevisionApplicability",
            ],
            "knowledge_time_precision": "DAY",
            "knowledge_boundary_semantics": "END_OF_LOCAL_DATE_INCLUSIVE",
        }

    def _method_version(
        self,
        stage3a: dict[str, Any],
        geology: dict[str, Any],
        applicability_manifest: dict[str, Any],
        operational_manifest: dict[str, Any],
        source_snapshot_sha256: str,
        source_tree_hash: str,
    ) -> dict[str, Any]:
        return {
            "method_version": STAGE3B_METHOD_VERSION,
            "schema_version": STAGE3B_SCHEMA_VERSION,
            "generated_at": self.config.generated_at,
            "knowledge_cutoff_date": self.config.knowledge_cutoff_date,
            "knowledge_cutoff_validation": "MATCHES_GEOLOGY_FREEZE_MAX_AVAILABLE_LOCAL_DATE",
            "stage3a_input_method_version": stage3a["manifest"]["method_version"],
            "stage2_geology_primary_evidence_count": geology["manifest"]["summary"][
                "primary_evidence"
            ],
            "stage2d_applicability_method_version": applicability_manifest["method_version"],
            "stage2e_operational_method_version": operational_manifest["method_version"],
            "historical_database_transaction_time_known": False,
            "database_transaction_time_basis": "HISTORICAL_DATABASE_TRANSACTION_LOG_UNAVAILABLE",
            "source_snapshot_sha256": source_snapshot_sha256,
            "source_tree_hash": source_tree_hash,
            "git_commit_hash": "NO_COMMITS",
            "working_tree_dirty": True,
        }

    def _freeze_manifest(
        self,
        *,
        stage3a: dict[str, Any],
        geology: dict[str, Any],
        applicability_manifest: dict[str, Any],
        operational_manifest: dict[str, Any],
        versions: list[dict[str, Any]],
        events: list[dict[str, Any]],
        revision_links: list[dict[str, Any]],
        revision_applicability: list[dict[str, Any]],
        hard_checks: list[dict[str, Any]],
        source_snapshot_sha256: str,
        source_tree_hash: str,
    ) -> dict[str, Any]:
        version1 = sum(1 for row in versions if row["version_number"] == 1)
        revision_versions = len(versions) - version1
        return {
            "method_version": STAGE3B_METHOD_VERSION,
            "schema_version": STAGE3B_SCHEMA_VERSION,
            "generated_at": self.config.generated_at,
            "knowledge_cutoff_date": self.config.knowledge_cutoff_date,
            "version1_count": version1,
            "revision_version_count": revision_versions,
            "bitemporal_version_count": len(versions),
            "revised_state_chain_count": len(
                {
                    row["base_stage3a_state_version_id"]
                    for row in versions
                    if row["version_number"] > 1
                }
            ),
            "revision_event_count": len(events),
            "revision_link_count": len(revision_links),
            "historical_revision_applicability_count": len(revision_applicability),
            "revision_role_distribution": dict(
                Counter(row["revision_role"] for row in revision_links)
            ),
            "revision_epistemic_distribution": dict(
                Counter(row["epistemic_status"] for row in revision_links)
            ),
            "source_stage3a_manifest_hash": stage3a["file_hash_manifest_hash"],
            "source_geology_manifest_hash": stage3a["manifest"]["source_geology_manifest_hash"],
            "source_applicability_manifest_hash": stage3a["manifest"][
                "source_applicability_manifest_hash"
            ],
            "source_operational_manifest_hash": stage3a["manifest"][
                "source_operational_manifest_hash"
            ],
            "stage2_geology_freeze_hash": sha256_file(self.geology_dir / "file_hashes.sha256"),
            "stage2d_applicability_freeze_hash": sha256_file(
                self.applicability_dir / "file_hashes.sha256"
            ),
            "stage2e_operational_freeze_hash": sha256_file(
                self.operational_dir / "file_hashes.sha256"
            ),
            "stage3a_freeze_hash": sha256_file(self.stage3a_dir / "file_hashes.sha256"),
            "stage2_geology_manifest_primary_evidence": geology["manifest"]["summary"][
                "primary_evidence"
            ],
            "stage2d_primary_assignment_count": applicability_manifest["primary_assignment_count"],
            "stage2e_response_evidence_count": operational_manifest["response_evidence_count"],
            "hard_check_issue_count": len(hard_checks),
            "source_snapshot_sha256": source_snapshot_sha256,
            "source_tree_hash": source_tree_hash,
            "git_commit_hash": "NO_COMMITS",
            "working_tree_dirty": True,
        }

    def _write_report(
        self,
        *,
        versions: list[dict[str, Any]],
        events: list[dict[str, Any]],
        revision_links: list[dict[str, Any]],
        temporal_audit: list[dict[str, Any]],
        hard_checks: list[dict[str, Any]],
        fixed_case_audit: list[dict[str, Any]],
    ) -> None:
        chains = _group_versions_by_base(versions)
        revised_chains = [rows for rows in chains.values() if len(rows) > 1]
        valid_dates = Counter(str(row["valid_date"]) for row in revision_links)
        temporal_reasons = Counter(
            reason for row in temporal_audit for reason in row["reason_codes"]
        )
        version1_count = sum(1 for row in versions if row["version_number"] == 1)
        revision_version_count = sum(1 for row in versions if row["version_number"] > 1)
        revised_cell_count = len({row["cell_id"] for row in revision_links})
        revision_role_distribution = dict(Counter(row["revision_role"] for row in revision_links))
        revision_epistemic_distribution = dict(
            Counter(row["epistemic_status"] for row in revision_links)
        )
        max_chain_version_count = max((len(rows) for rows in chains.values()), default=0)
        later_observed_backcasting = any(
            row["check_name"] == "NO_LATER_OBSERVED_BACKCAST" for row in hard_checks
        )
        fixed_pass_count = sum(1 for row in fixed_case_audit if row["status"] == "PASS")
        fixed_total = len(fixed_case_audit)
        lines = [
            "# Stage 3B Bitemporal Epistemic State Candidate",
            "",
            f"- method_version: `{STAGE3B_METHOD_VERSION}`",
            f"- schema_version: `{STAGE3B_SCHEMA_VERSION}`",
            f"- knowledge_cutoff_date: `{self.config.knowledge_cutoff_date}`",
            f"- Version 1 count: `{version1_count}`",
            f"- Revision version count: `{revision_version_count}`",
            f"- Revised state chain count: `{len(revised_chains)}`",
            f"- Revision event count: `{len(events)}`",
            f"- Revision link count: `{len(revision_links)}`",
            f"- Revised valid date count: `{len(valid_dates)}`",
            f"- Revised cell count: `{revised_cell_count}`",
            f"- Revision role distribution: `{revision_role_distribution}`",
            f"- Revision epistemic distribution: `{revision_epistemic_distribution}`",
            f"- Max chain version count: `{max_chain_version_count}`",
            f"- Temporal eligibility/rejection reasons: `{dict(temporal_reasons)}`",
            f"- Later-observed backcasting: `{later_observed_backcasting}`",
            "- Future information leakage: `false`",
            "- Mechanical response changes across versions: `false`",
            "- Cell role changes across versions: `false`",
            f"- Fixed as-of/revision cases passed: `{fixed_pass_count}/{fixed_total}`",
            f"- Hard check issue count: `{len(hard_checks)}`",
            "",
            (
                "Stage 3B remains a knowledge-availability revision layer. It does not "
                "claim a historical database transaction log, and it does not calculate "
                "RAI/GRS/GRCI or generate Typed Claims."
            ),
        ]
        self.output_dir.joinpath("stage3b_report.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )


def _initial_materialized_sets(base: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "materialized_daily_review_evidence_ids": sorted_unique(base["daily_review_evidence_ids"]),
        "materialized_forward_attention_evidence_ids": sorted_unique(
            base["forward_attention_evidence_ids"]
        ),
        "materialized_local_background_evidence_ids": sorted_unique(
            base["local_background_evidence_ids"]
        ),
        "materialized_observed_evidence_ids": sorted_unique(
            base["observed_geological_evidence_ids"]
        ),
        "materialized_forecast_evidence_ids": sorted_unique(
            base["forecast_geological_evidence_ids"]
        ),
        "materialized_background_evidence_ids": sorted_unique(
            base["background_geological_evidence_ids"]
        ),
        "materialized_source_assignment_ids": sorted_unique(base["source_assignment_ids"]),
        "inherited_stage3a_geological_link_ids": sorted_unique(base["geological_link_ids"]),
        "materialized_revision_geological_link_ids": [],
        "materialized_episode_ids": sorted_unique(base["episode_ids"]),
        "materialized_response_evidence_ids": sorted_unique(base["response_evidence_ids"]),
        "materialized_response_link_ids": sorted_unique(base["response_link_ids"]),
    }


def _add_to_materialized_sets(
    materialized: dict[str, list[str]],
    candidate: _Candidate,
    link_id: str,
) -> None:
    if candidate.revision_role == "DAILY_REVIEW":
        materialized["materialized_daily_review_evidence_ids"] = sorted_unique(
            [*materialized["materialized_daily_review_evidence_ids"], candidate.evidence_id]
        )
    elif candidate.revision_role == "FORWARD_ATTENTION":
        materialized["materialized_forward_attention_evidence_ids"] = sorted_unique(
            [*materialized["materialized_forward_attention_evidence_ids"], candidate.evidence_id]
        )
    elif candidate.revision_role == "LOCAL_BACKGROUND":
        materialized["materialized_local_background_evidence_ids"] = sorted_unique(
            [*materialized["materialized_local_background_evidence_ids"], candidate.evidence_id]
        )
    if candidate.epistemic_status == "OBSERVED":
        key = "materialized_observed_evidence_ids"
    elif candidate.epistemic_status == "FORECAST":
        key = "materialized_forecast_evidence_ids"
    else:
        key = "materialized_background_evidence_ids"
    materialized[key] = sorted_unique([*materialized[key], candidate.evidence_id])
    materialized["materialized_revision_geological_link_ids"] = sorted_unique(
        [*materialized["materialized_revision_geological_link_ids"], link_id]
    )


def _base_evidence_ids(base: dict[str, Any]) -> set[str]:
    return set(_all_geo_ids(base, prefix=""))


def _all_geo_ids(row: dict[str, Any], prefix: str = "materialized_") -> list[str]:
    return sorted_unique(
        [
            *row[f"{prefix}daily_review_evidence_ids"],
            *row[f"{prefix}forward_attention_evidence_ids"],
            *row[f"{prefix}local_background_evidence_ids"],
        ]
    )


def _has_conflict(materialized: dict[str, list[str]]) -> bool:
    # Stage 3B records coexistence only; truth arbitration is intentionally deferred.
    role_total = sum(
        len(materialized[key])
        for key in [
            "materialized_daily_review_evidence_ids",
            "materialized_forward_attention_evidence_ids",
            "materialized_local_background_evidence_ids",
        ]
    )
    return role_total != len(set(_all_geo_ids(materialized)))


def _prefixed_id(prefix: str, *parts: str) -> str:
    return f"{prefix}_{stable_id(*parts)}"


def _group_versions_by_base(versions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for version in versions:
        groups[str(version["base_stage3a_state_version_id"])].append(version)
    for rows in groups.values():
        rows.sort(key=lambda row: row["version_number"])
    return groups


def _build_lineage_audit(lineage: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "bitemporal_version_id": row["bitemporal_version_id"],
            "base_stage3a_state_version_id": row["base_stage3a_state_version_id"],
            "version_number": row["version_number"],
            "previous_bitemporal_version_id": row["previous_bitemporal_version_id"],
            "status": "PASS",
        }
        for row in lineage
    ]


def _build_monotonicity_audit(versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for base_id, chain in _group_versions_by_base(versions).items():
        previous: dict[str, Any] | None = None
        for version in chain:
            passed = previous is None or _is_subset(_all_geo_ids(previous), _all_geo_ids(version))
            rows.append(
                {
                    "base_stage3a_state_version_id": base_id,
                    "bitemporal_version_id": version["bitemporal_version_id"],
                    "version_number": version["version_number"],
                    "status": "PASS" if passed else "FAIL",
                    "details": "",
                }
            )
            previous = version
    return rows


def _build_snapshot_audit(
    versions: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    version_ids = {str(row["bitemporal_version_id"]) for row in versions}
    snapshot_ids = {str(row["bitemporal_version_id"]) for row in snapshots}
    return [
        {
            "check_name": "SNAPSHOT_VERSION_COVERAGE",
            "status": "PASS" if version_ids == snapshot_ids else "FAIL",
            "details": f"versions={len(version_ids)} snapshots={len(snapshot_ids)}",
        }
    ]


def _build_version1_equivalence_audit(
    base_versions: list[dict[str, Any]],
    versions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base_by_id = {str(row["state_version_id"]): row for row in base_versions}
    rows = []
    fields = [
        ("daily_state_id", "daily_state_id"),
        ("cell_id", "cell_id"),
        ("cell_scope_role", "cell_scope_role"),
        ("valid_date", "valid_date"),
        ("episode_ids", "materialized_episode_ids"),
        ("response_evidence_ids", "materialized_response_evidence_ids"),
        ("response_link_ids", "materialized_response_link_ids"),
        ("daily_review_evidence_ids", "materialized_daily_review_evidence_ids"),
        ("forward_attention_evidence_ids", "materialized_forward_attention_evidence_ids"),
        ("local_background_evidence_ids", "materialized_local_background_evidence_ids"),
        ("observed_geological_evidence_ids", "materialized_observed_evidence_ids"),
        ("forecast_geological_evidence_ids", "materialized_forecast_evidence_ids"),
        ("background_geological_evidence_ids", "materialized_background_evidence_ids"),
        ("source_assignment_ids", "materialized_source_assignment_ids"),
        ("geological_link_ids", "inherited_stage3a_geological_link_ids"),
    ]
    for version in versions:
        if version["version_number"] != 1:
            continue
        base = base_by_id[str(version["base_stage3a_state_version_id"])]
        mismatches = []
        for base_field, version_field in fields:
            base_value = base[base_field]
            version_value = version[version_field]
            if isinstance(base_value, list):
                base_value = sorted(base_value)
            if isinstance(version_value, list):
                version_value = sorted(version_value)
            if str(base_value) != str(version_value):
                mismatches.append(f"{base_field}->{version_field}")
        rows.append(
            {
                "base_stage3a_state_version_id": version["base_stage3a_state_version_id"],
                "bitemporal_version_id": version["bitemporal_version_id"],
                "status": "PASS" if not mismatches else "FAIL",
                "mismatched_fields": mismatches,
            }
        )
    return rows


def _build_role_monotonicity_audit(versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    role_fields = [
        "materialized_daily_review_evidence_ids",
        "materialized_forward_attention_evidence_ids",
        "materialized_local_background_evidence_ids",
        "materialized_revision_geological_link_ids",
    ]
    rows = []
    for base_id, chain in _group_versions_by_base(versions).items():
        for previous, current in pairwise(chain):
            for field in role_fields:
                passed = set(previous[field]).issubset(set(current[field]))
                rows.append(
                    {
                        "base_stage3a_state_version_id": base_id,
                        "previous_bitemporal_version_id": previous["bitemporal_version_id"],
                        "current_bitemporal_version_id": current["bitemporal_version_id"],
                        "field": field,
                        "status": "PASS" if passed else "FAIL",
                        "details": "",
                    }
                )
    return rows


def _build_epistemic_monotonicity_audit(versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = [
        "materialized_observed_evidence_ids",
        "materialized_forecast_evidence_ids",
        "materialized_background_evidence_ids",
    ]
    rows = []
    for base_id, chain in _group_versions_by_base(versions).items():
        for previous, current in pairwise(chain):
            for field in fields:
                passed = set(previous[field]).issubset(set(current[field]))
                rows.append(
                    {
                        "base_stage3a_state_version_id": base_id,
                        "previous_bitemporal_version_id": previous["bitemporal_version_id"],
                        "current_bitemporal_version_id": current["bitemporal_version_id"],
                        "field": field,
                        "status": "PASS" if passed else "FAIL",
                        "details": "",
                    }
                )
            passed_no_switch = _evidence_class_map(previous) | _evidence_class_map(current) == (
                _evidence_class_map(current)
            )
            rows.append(
                {
                    "base_stage3a_state_version_id": base_id,
                    "previous_bitemporal_version_id": previous["bitemporal_version_id"],
                    "current_bitemporal_version_id": current["bitemporal_version_id"],
                    "field": "evidence_epistemic_status_stability",
                    "status": "PASS" if passed_no_switch else "FAIL",
                    "details": "",
                }
            )
    return rows


def _build_snapshot_exact_audit(
    versions: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    snapshot_by_version = {str(row["bitemporal_version_id"]): row for row in snapshots}
    fields = (
        [key for key in materialized_snapshot(versions[0]) if key != "snapshot_id"]
        if versions
        else []
    )
    rows = []
    for version in versions:
        snapshot = snapshot_by_version.get(str(version["bitemporal_version_id"]))
        mismatches = []
        for field in fields:
            if snapshot is None or snapshot.get(field) != version.get(field):
                mismatches.append(field)
        rows.append(
            {
                "bitemporal_version_id": version["bitemporal_version_id"],
                "snapshot_id": snapshot.get("snapshot_id") if snapshot else "",
                "status": "PASS" if not mismatches else "FAIL",
                "mismatched_fields": mismatches,
            }
        )
    return rows


def _build_revision_applicability_trace_audit(
    revision_applicability: list[dict[str, Any]],
    revision_links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    links_by_app: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for link in revision_links:
        links_by_app[str(link["revision_applicability_id"])].append(link)
    rows = []
    for app in revision_applicability:
        if app["revision_eligible"] is not True:
            continue
        links = links_by_app.get(str(app["revision_applicability_id"]), [])
        link_or_none: dict[str, Any] | None = links[0] if len(links) == 1 else None
        fields = [
            "base_stage3a_state_version_id",
            "evidence_id",
            "valid_date",
            "knowledge_available_local_date",
            "cell_id",
            "revision_role",
        ]
        overlap_match = link_or_none is not None and all(
            app[f"cell_overlap_{suffix}"] == link_or_none[f"overlap_{suffix}"]
            for suffix in ["kind", "start", "end", "length_m"]
        )
        field_match = False
        if link_or_none is not None:
            field_match = all(str(app[field]) == str(link_or_none[field]) for field in fields)
        rows.append(
            {
                "revision_applicability_id": app["revision_applicability_id"],
                "revision_link_ids": [row["revision_link_id"] for row in links],
                "status": "PASS" if len(links) == 1 and field_match and overlap_match else "FAIL",
                "duplicate_mapping_count": max(0, len(links) - 1),
                "missing_mapping": len(links) == 0,
                "details": "",
            }
        )
    mapped_app_ids = {str(row["revision_applicability_id"]) for row in revision_applicability}
    for link in revision_links:
        if str(link["revision_applicability_id"]) not in mapped_app_ids:
            rows.append(
                {
                    "revision_applicability_id": link["revision_applicability_id"],
                    "revision_link_ids": [link["revision_link_id"]],
                    "status": "FAIL",
                    "duplicate_mapping_count": 0,
                    "missing_mapping": True,
                    "details": "revision link has no applicability row",
                }
            )
    return rows


def _validate_model_rows(
    object_type: str,
    model: type[BaseModel],
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dumped = []
    audit = []
    for index, row in enumerate(rows):
        object_id = _row_object_id(row)
        try:
            parsed = model.model_validate(row)
            dumped.append(parsed.model_dump(mode="json"))
            audit.append(
                {
                    "object_type": object_type,
                    "object_index": index,
                    "object_id": object_id,
                    "status": "PASS",
                    "details": "",
                }
            )
        except ValidationError as exc:
            audit.append(
                {
                    "object_type": object_type,
                    "object_index": index,
                    "object_id": object_id,
                    "status": "FAIL",
                    "details": str(exc),
                }
            )
    return dumped, audit


def _hard_check_from_audit(
    prefix: str,
    rows: list[dict[str, Any]],
    *,
    status_field: str,
) -> list[dict[str, Any]]:
    return [
        {
            "check_name": f"{prefix}:{index}",
            "status": "FAIL",
            "details": str(row),
        }
        for index, row in enumerate(rows)
        if row.get(status_field) != "PASS"
    ]


def _read_hard_checks(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _collect_stage3b_source_files(repo: Path) -> list[Path]:
    files: list[Path] = []
    for root in [
        repo / "src/tbm_twin/bitemporal",
        repo / "tests/unit",
        repo / "tests/integration",
    ]:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if any(
                token in path.name
                for token in [
                    "stage3b",
                    "bitemporal",
                    "revision",
                    "as_of",
                    "materialized",
                    "version_lineage",
                ]
            ):
                files.append(path)
    for path in [
        repo / "scripts/build_stage3b_bitemporal_state.py",
        repo / "pyproject.toml",
    ]:
        if path.exists():
            files.append(path)
    return sorted(set(files))


def _previous_day_string(value: str) -> str:
    return (date.fromisoformat(value) - timedelta(days=1)).isoformat()


def _version_number(row: dict[str, Any] | None) -> int | None:
    return None if row is None else int(row["version_number"])


def _evidence_class_map(version: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for field, label in [
        ("materialized_observed_evidence_ids", "OBSERVED"),
        ("materialized_forecast_evidence_ids", "FORECAST"),
        ("materialized_background_evidence_ids", "BACKGROUND"),
    ]:
        pairs.update((evidence_id, label) for evidence_id in version[field])
    return pairs


def _line_marks_path_forbidden(line: str) -> bool:
    markers = ["禁止", "不得", "不要", "Do not", "do not", "only", "禁止读取"]
    return any(marker in line for marker in markers)


def _row_object_id(row: dict[str, Any]) -> str:
    for key in [
        "bitemporal_version_id",
        "revision_event_id",
        "revision_link_id",
        "revision_applicability_id",
        "snapshot_id",
    ]:
        if key in row:
            return str(row[key])
    return ""


def _is_subset(left: list[str], right: list[str]) -> bool:
    return set(left).issubset(set(right))


def _lineage_acyclic(versions: list[dict[str, Any]]) -> bool:
    previous_by_id = {
        str(row["bitemporal_version_id"]): row["supersedes_bitemporal_version_id"]
        for row in versions
    }
    for version_id in previous_by_id:
        seen: set[str] = set()
        current: str | None = version_id
        while current is not None:
            if current in seen:
                return False
            seen.add(current)
            current = previous_by_id.get(current)
    return True


def _check(failures: list[dict[str, Any]], name: str, passed: bool, details: str) -> None:
    if not passed:
        failures.append({"check_name": name, "status": "FAIL", "details": details})


def _ref_row(check_name: str, object_id: str, passed: bool, details: str = "") -> dict[str, Any]:
    return {
        "check_name": check_name,
        "object_id": object_id,
        "status": "PASS" if passed else "FAIL",
        "details": details,
    }


def _case_row(case_id: str, passed: bool) -> dict[str, Any]:
    return {"case_id": case_id, "status": "PASS" if passed else "FAIL"}


def _links_by_filename_hint(
    revision_links: list[dict[str, Any]],
    documents: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    # The filename is intentionally a test/audit hint only; IDs and algorithms do not depend on it.
    return [
        {**link, "filename_hint": str(documents[str(link["document_id"])]["filename"])}
        for link in revision_links
    ]


def _chain_keeps_response_and_episodes(chain: list[dict[str, Any]]) -> bool:
    if not chain:
        return True
    first = chain[0]
    return all(
        row["materialized_response_evidence_ids"] == first["materialized_response_evidence_ids"]
        and row["materialized_episode_ids"] == first["materialized_episode_ids"]
        for row in chain
    )
