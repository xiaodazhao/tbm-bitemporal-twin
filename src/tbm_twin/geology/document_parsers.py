"""Source-specific parsers for raw geological PDF documents."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TypedDict
from zoneinfo import ZoneInfo

from tbm_twin.evidence.models import (
    ChainageDirection,
    ChainageInterval,
    EvidenceQualityGrade,
    EvidenceType,
    GeologicalEpistemicStatus,
    GeologicalEvidence,
    GeologicalSourceType,
    SpatialScope,
    SpatialValueConfidence,
    TemporalCandidate,
    TemporalConfidence,
    TemporalExtent,
    TemporalPrecision,
    TemporalRole,
    TemporalValue,
    TemporalValueConfidence,
)
from tbm_twin.geology.chainage import ChainageValidationConfig, parse_chainage_interval
from tbm_twin.geology.document_models import (
    GeologicalDocument,
    GeologicalPdfSourceAsset,
    PdfPageText,
    SpatialCandidate,
)

SOURCE_TIMEZONE = "Asia/Shanghai"
TIMEZONE_BASIS = "PROJECT_LOCATION_AND_CONFIGURATION"

DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日"),
    re.compile(r"(?P<y>20\d{2})[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})"),
    re.compile(r"(?P<y>20\d{2})(?P<m>\d{2})(?P<d>\d{2})"),
    re.compile(
        r"(?P<y>二[\u3007零一二三四五六七八九十]{3})年"
        r"(?P<m>[一二三四五六七八九十]+)月"
        r"(?P<d>[一二三四五六七八九十]+)日"
    ),
    re.compile(r"(?<!\d)(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日"),
]


class DateMatch(TypedDict):
    """A regex date match with parsed semantics."""

    raw: str
    date: date
    start: int
    end: int
    year_inferred: bool


@dataclass(frozen=True)
class ParseResult:
    """Raw parser output for one PDF."""

    document: GeologicalDocument | None
    evidence: list[GeologicalEvidence]
    unparsed_reason: str | None = None
    non_evidence_sections: list[dict[str, str | int | None]] | None = None
    table_row_audit: list[dict[str, str | int | None]] | None = None
    unresolved_table_cells: list[dict[str, str | int | None]] | None = None
    duplicate_evidence_rows: list[dict[str, str | int | None]] | None = None


@dataclass(frozen=True)
class EvidenceSection:
    """A source text section eligible for canonical geological evidence."""

    source_level: str
    raw_text: str
    source_page: int
    extraction_rule: str
    evidence_type: EvidenceType
    epistemic_status: GeologicalEpistemicStatus
    spatial_scope: SpatialScope | None
    validation_flags: list[str]
    row_id: str | None = None
    range_source: str = "SELF_RANGE"
    resolved_fragments: tuple[str, ...] = ()


class BaseDocumentParser:
    """Base parser for one source-specific geological PDF."""

    source_type: GeologicalSourceType = GeologicalSourceType.OTHER
    epistemic_status: GeologicalEpistemicStatus = GeologicalEpistemicStatus.UNKNOWN
    evidence_type: EvidenceType = EvidenceType.GEOLOGICAL_UNKNOWN

    def parse(self, asset: GeologicalPdfSourceAsset, pages: list[PdfPageText]) -> ParseResult:
        """Parse a PDF into one document and one or more evidence records."""

        if not any(page.text_length > 0 for page in pages):
            return ParseResult(
                document=None,
                evidence=[],
                unparsed_reason="PDF_TEXT_LAYER_UNAVAILABLE",
                non_evidence_sections=[],
                table_row_audit=[],
                unresolved_table_cells=[],
                duplicate_evidence_rows=[],
            )
        text = "\n".join(page.page_text for page in pages)
        report_id = asset.source_path.stem
        temporal_candidates = extract_temporal_candidates(
            pages, asset.source_type, asset.source_filename
        )
        spatial_candidates = extract_spatial_candidates(pages, asset.source_filename)
        document_scope = _document_scope(spatial_candidates, asset.source_type)
        face_candidate = _choose_face_candidate(
            spatial_candidates, document_scope, asset.source_type
        )
        face_chainage = face_candidate.start_chainage if face_candidate else None
        observed = choose_extent(temporal_candidates, TemporalRole.OBSERVED)
        documented = choose_extent(temporal_candidates, TemporalRole.DOCUMENTED)
        issued = choose_extent(temporal_candidates, TemporalRole.ISSUED)
        submitted = choose_extent(temporal_candidates, TemporalRole.SUBMITTED)
        available = choose_available_extent(
            asset.source_type, temporal_candidates, submitted, issued, documented
        )
        document_id = stable_id("document", asset.asset_id, report_id)
        warnings = _document_warnings(temporal_candidates, spatial_candidates)
        document = GeologicalDocument(
            document_id=document_id,
            source_asset_id=asset.asset_id,
            source_type=asset.source_type,
            report_id=report_id,
            title=report_id,
            tunnel_name=_extract_tunnel_name(text),
            face_chainage=face_chainage,
            face_chainage_basis=face_candidate.extraction_rule if face_candidate else None,
            face_chainage_source_page=face_candidate.source_page if face_candidate else None,
            face_chainage_validation_status=_face_validation_status(
                face_candidate, document_scope, asset.source_type
            ),
            document_spatial_scope=document_scope,
            observed_time_extent=observed,
            document_time_extent=documented,
            issued_time_extent=issued,
            submitted_time_extent=submitted,
            available_time_extent=available,
            temporal_candidates=temporal_candidates,
            spatial_candidates=spatial_candidates,
            document_warnings=warnings,
        )
        records = self._evidence(asset, pages, document)
        return ParseResult(
            document=document,
            evidence=records,
            non_evidence_sections=getattr(self, "_last_non_evidence_sections", []),
            table_row_audit=getattr(self, "_last_table_row_audit", []),
            unresolved_table_cells=getattr(self, "_last_unresolved_table_cells", []),
            duplicate_evidence_rows=getattr(self, "_last_duplicate_evidence_rows", []),
        )

    def _evidence(
        self,
        asset: GeologicalPdfSourceAsset,
        pages: list[PdfPageText],
        document: GeologicalDocument,
    ) -> list[GeologicalEvidence]:
        section_text = _first_nonempty_page_excerpt(pages, 1600)
        return [
            build_evidence(
                asset=asset,
                document=document,
                source_level="document_background",
                raw_text=section_text[1],
                spatial_scope=document.document_spatial_scope,
                chainage_interval=_chainage_interval_from_scope(
                    document.document_spatial_scope,
                    [],
                ),
                page_refs=[section_text[0]],
                evidence_index=0,
                evidence_type=EvidenceType.GEOLOGICAL_BACKGROUND,
                epistemic_status=GeologicalEpistemicStatus.BACKGROUND,
                extraction_rule="base_document_background_excerpt",
            )
        ]


class TSPDocumentParser(BaseDocumentParser):
    """Parser for TSP forecast PDFs."""

    source_type = GeologicalSourceType.TSP_REPORT
    epistemic_status = GeologicalEpistemicStatus.FORECAST
    evidence_type = EvidenceType.GEOLOGICAL_FORECAST

    def _evidence(
        self,
        asset: GeologicalPdfSourceAsset,
        pages: list[PdfPageText],
        document: GeologicalDocument,
    ) -> list[GeologicalEvidence]:
        records, audits = forecast_evidence_from_ranges(asset, pages, document, "tsp")
        self._last_non_evidence_sections = audits["non_evidence_sections"]
        self._last_table_row_audit = audits["table_row_audit"]
        self._last_unresolved_table_cells = audits["unresolved_table_cells"]
        self._last_duplicate_evidence_rows = audits["duplicate_evidence_rows"]
        return records


class SonicDocumentParser(BaseDocumentParser):
    """Parser for HSP/Sonic forecast PDFs."""

    source_type = GeologicalSourceType.SONIC_FORECAST
    epistemic_status = GeologicalEpistemicStatus.FORECAST
    evidence_type = EvidenceType.GEOLOGICAL_FORECAST

    def _evidence(
        self,
        asset: GeologicalPdfSourceAsset,
        pages: list[PdfPageText],
        document: GeologicalDocument,
    ) -> list[GeologicalEvidence]:
        records, audits = forecast_evidence_from_ranges(asset, pages, document, "sonic")
        self._last_non_evidence_sections = audits["non_evidence_sections"]
        self._last_table_row_audit = audits["table_row_audit"]
        self._last_unresolved_table_cells = audits["unresolved_table_cells"]
        self._last_duplicate_evidence_rows = audits["duplicate_evidence_rows"]
        return records


class FaceSketchDocumentParser(BaseDocumentParser):
    """Parser for face sketch observation PDFs."""

    source_type = GeologicalSourceType.FACE_SKETCH
    epistemic_status = GeologicalEpistemicStatus.OBSERVED
    evidence_type = EvidenceType.GEOLOGICAL_OBSERVATION

    def parse(self, asset: GeologicalPdfSourceAsset, pages: list[PdfPageText]) -> ParseResult:
        result = super().parse(asset, pages)
        if result.document is None:
            return result
        candidates = result.document.temporal_candidates
        observed = choose_extent(candidates, TemporalRole.OBSERVED)
        documented = choose_extent(candidates, TemporalRole.DOCUMENTED) or observed
        available = observed
        document = result.document.model_copy(
            update={
                "observed_time_extent": observed,
                "document_time_extent": documented,
                "available_time_extent": available.model_copy(
                    update={"basis": "SIGNED_DOCUMENT_DATE_DAY_PRECISION_POLICY"}
                )
                if available
                else None,
            }
        )
        return ParseResult(document=document, evidence=self._evidence(asset, pages, document))

    def _evidence(
        self,
        asset: GeologicalPdfSourceAsset,
        pages: list[PdfPageText],
        document: GeologicalDocument,
    ) -> list[GeologicalEvidence]:
        records: list[GeologicalEvidence] = []
        face_candidate = _choose_face_candidate(
            document.spatial_candidates,
            document.document_spatial_scope,
            asset.source_type,
        )
        if face_candidate is not None:
            face_page = face_candidate.source_page or 1
            face_text = _sketch_face_observation_text(
                pages,
                face_page,
                face_candidate.start_chainage,
            )
            scope = SpatialScope(
                start_chainage=face_candidate.start_chainage,
                end_chainage=face_candidate.end_chainage,
                basis=face_candidate.extraction_rule,
            )
            records.append(
                build_evidence(
                    asset=asset,
                    document=document,
                    source_level="face_observation",
                    raw_text=face_text,
                    spatial_scope=scope,
                    chainage_interval=_chainage_interval_from_scope(
                        scope,
                        face_candidate.validation_flags,
                    ),
                    page_refs=[face_candidate.source_page] if face_candidate.source_page else [],
                    evidence_index=0,
                    evidence_type=EvidenceType.GEOLOGICAL_OBSERVATION,
                    epistemic_status=GeologicalEpistemicStatus.OBSERVED,
                    extraction_rule=face_candidate.extraction_rule,
                )
            )
        for index, section in enumerate(_sketch_interval_sections(pages), start=1):
            records.append(
                build_evidence(
                    asset=asset,
                    document=document,
                    source_level=section.source_level,
                    raw_text=section.raw_text,
                    spatial_scope=section.spatial_scope,
                    chainage_interval=_chainage_interval_from_scope(
                        section.spatial_scope,
                        section.validation_flags,
                    ),
                    page_refs=[section.source_page],
                    evidence_index=index,
                    evidence_type=section.evidence_type,
                    epistemic_status=section.epistemic_status,
                    extraction_rule=section.extraction_rule,
                )
            )
        return records


def parser_for_source(source_type: GeologicalSourceType) -> BaseDocumentParser:
    """Return the source-specific parser."""

    if source_type == GeologicalSourceType.TSP_REPORT:
        return TSPDocumentParser()
    if source_type == GeologicalSourceType.SONIC_FORECAST:
        return SonicDocumentParser()
    if source_type == GeologicalSourceType.FACE_SKETCH:
        return FaceSketchDocumentParser()
    return BaseDocumentParser()


def forecast_evidence_from_ranges(
    asset: GeologicalPdfSourceAsset,
    pages: list[PdfPageText],
    document: GeologicalDocument,
    parser_name: str,
) -> tuple[list[GeologicalEvidence], dict[str, list[dict[str, str | int | None]]]]:
    """Build source-specific forecast/background evidence from eligible sections."""

    records: list[GeologicalEvidence] = []
    audits = _empty_forecast_audits()
    for index, section in enumerate(
        _forecast_sections(asset, pages, document, parser_name, audits), start=1
    ):
        record = build_evidence(
            asset=asset,
            document=document,
            source_level=section.source_level,
            raw_text=section.raw_text,
            spatial_scope=section.spatial_scope,
            chainage_interval=_chainage_interval_from_scope(
                section.spatial_scope,
                section.validation_flags,
            ),
            page_refs=[section.source_page],
            evidence_index=index,
            evidence_type=section.evidence_type,
            epistemic_status=section.epistemic_status,
            extraction_rule=section.extraction_rule,
        )
        records.append(record)
        if section.row_id is not None:
            audits["table_row_audit"].append(
                {
                    "document_id": document.document_id,
                    "page": section.source_page,
                    "row_id": section.row_id,
                    "range": _scope_text(section.spatial_scope),
                    "merged_cells": section.raw_text,
                    "evidence_id": record.evidence_id,
                    "status": "EVIDENCE_CREATED",
                }
            )
            for fragment in section.resolved_fragments:
                audits["unresolved_table_cells"].append(
                    {
                        "document_id": document.document_id,
                        "page": section.source_page,
                        "row_id": section.row_id,
                        "range": _scope_text(section.spatial_scope),
                        "text": fragment,
                        "status": "RESOLVED_IN_EVIDENCE",
                        "evidence_id": record.evidence_id,
                    }
                )
    deduped, duplicate_rows = _dedupe_evidence_records(records)
    deduped, semantic_duplicate_rows = _dedupe_forecast_scope_records(deduped)
    audits["duplicate_evidence_rows"].extend(duplicate_rows)
    audits["duplicate_evidence_rows"].extend(semantic_duplicate_rows)
    for rows in audits.values():
        for row in rows:
            if row.get("document_id") is None:
                row["document_id"] = document.document_id
    return deduped, audits


def _empty_forecast_audits() -> dict[str, list[dict[str, str | int | None]]]:
    return {
        "non_evidence_sections": [],
        "table_row_audit": [],
        "unresolved_table_cells": [],
        "duplicate_evidence_rows": [],
    }


def _scope_text(scope: SpatialScope | None) -> str:
    if scope is None:
        return "UNKNOWN"
    return f"{scope.start_chainage}-{scope.end_chainage}"


def _dedupe_evidence_records(
    records: list[GeologicalEvidence],
) -> tuple[list[GeologicalEvidence], list[dict[str, str | int | None]]]:
    seen: set[tuple[str | None, tuple[int, ...], str, str | None, float | None, float | None]] = (
        set()
    )
    out: list[GeologicalEvidence] = []
    duplicates: list[dict[str, str | int | None]] = []
    for record in records:
        key = (
            record.document_id,
            tuple(record.source_page_refs),
            record.normalized_text,
            record.source_level,
            record.spatial_scope.start_chainage if record.spatial_scope else None,
            record.spatial_scope.end_chainage if record.spatial_scope else None,
        )
        if key in seen:
            duplicates.append(
                {
                    "document_id": record.document_id,
                    "evidence_id": record.evidence_id,
                    "source_page_refs": ";".join(str(page) for page in record.source_page_refs),
                    "source_level": record.source_level,
                    "reason": "EXACT_DUPLICATE_DOCUMENT_PAGE_RANGE_TEXT",
                }
            )
            continue
        seen.add(key)
        out.append(record)
    return out, duplicates


def _dedupe_forecast_scope_records(
    records: list[GeologicalEvidence],
) -> tuple[list[GeologicalEvidence], list[dict[str, str | int | None]]]:
    selected: dict[tuple[str | None, float | None, float | None], GeologicalEvidence] = {}
    order: list[tuple[str | None, float | None, float | None]] = []
    duplicates: list[dict[str, str | int | None]] = []
    passthrough: list[GeologicalEvidence] = []
    for record in records:
        if (
            record.evidence_type != EvidenceType.GEOLOGICAL_FORECAST
            or record.source_level != "forecast_segment"
            or record.spatial_scope is None
        ):
            passthrough.append(record)
            continue
        key = (
            record.document_id,
            record.spatial_scope.start_chainage,
            record.spatial_scope.end_chainage,
        )
        if key not in selected:
            selected[key] = record
            order.append(key)
            continue
        current = selected[key]
        preferred = _prefer_forecast_record(current, record)
        duplicate = record if preferred is current else current
        selected[key] = preferred
        duplicates.append(
            {
                "document_id": duplicate.document_id,
                "evidence_id": duplicate.evidence_id,
                "source_page_refs": ";".join(str(page) for page in duplicate.source_page_refs),
                "source_level": duplicate.source_level or "",
                "reason": "DUPLICATE_FORECAST_SCOPE_TABLE_ROW_PREFERRED",
            }
        )
    return passthrough + [selected[key] for key in order], duplicates


def _prefer_forecast_record(
    left: GeologicalEvidence,
    right: GeologicalEvidence,
) -> GeologicalEvidence:
    left_rule = str(left.structured_attributes.get("extraction_rule"))
    right_rule = str(right.structured_attributes.get("extraction_rule"))
    if left_rule == "forecast_table_row_reconstruction":
        return left
    if right_rule == "forecast_table_row_reconstruction":
        return right
    return left if len(left.raw_text) >= len(right.raw_text) else right


def build_evidence(
    *,
    asset: GeologicalPdfSourceAsset,
    document: GeologicalDocument,
    source_level: str,
    raw_text: str,
    spatial_scope: SpatialScope | None,
    chainage_interval: ChainageInterval | None,
    page_refs: list[int],
    evidence_index: int,
    evidence_type: EvidenceType | None = None,
    epistemic_status: GeologicalEpistemicStatus | None = None,
    extraction_rule: str = "unspecified_rule",
) -> GeologicalEvidence:
    """Build canonical GeologicalEvidence from a parsed document."""

    resolved_type = evidence_type or EvidenceType.GEOLOGICAL_UNKNOWN
    epistemic = epistemic_status or GeologicalEpistemicStatus.UNKNOWN
    evidence_id = stable_id(
        "geology", document.document_id, source_level, str(evidence_index), raw_text
    )
    warnings: list[str] = []
    if spatial_scope is None:
        warnings.append("SPATIAL_SCOPE_UNKNOWN")
    if chainage_interval is not None:
        warnings.extend(chainage_interval.validation_flags)
    if document.available_time_extent is None:
        warnings.append("AVAILABLE_TIME_UNKNOWN")
    quality = EvidenceQualityGrade.B if warnings else EvidenceQualityGrade.A
    structured_attributes = extract_structured_attributes(raw_text, source_level)
    structured_attributes["parser_source_level"] = source_level
    structured_attributes["section_role"] = source_level
    structured_attributes["extraction_rule"] = extraction_rule
    return GeologicalEvidence(
        evidence_id=evidence_id,
        evidence_type=resolved_type,
        source_asset_ids=[asset.asset_id],
        valid_time=None,
        available_time=None,
        ingested_time=asset.ingested_time,
        spatial_scope=spatial_scope,
        quality_grade=quality,
        quality_flags=sorted(set(warnings)),
        method_version="raw_geological_evidence_v1",
        provenance_refs=[asset.asset_id, *[f"page:{page}" for page in page_refs]],
        document_id=document.document_id,
        source_asset_id=asset.asset_id,
        source_pdf_path=str(asset.source_path),
        geological_source_type=asset.source_type,
        source_level=source_level,
        epistemic_status=epistemic,
        title=document.title,
        raw_text=raw_text,
        normalized_text=_normalize_text(raw_text),
        observed_time=_extent_to_value(document.observed_time_extent),
        issued_time=_extent_to_value(document.issued_time_extent),
        available_time_value=_extent_to_value(document.available_time_extent),
        observed_time_extent=document.observed_time_extent,
        document_time_extent=document.document_time_extent,
        issued_time_extent=document.issued_time_extent,
        submitted_time_extent=document.submitted_time_extent,
        available_time_extent=document.available_time_extent,
        chainage_interval=chainage_interval,
        face_chainage=document.face_chainage,
        structured_attributes=structured_attributes,
        source_record_id=f"{document.report_id}:{source_level}:{evidence_index}",
        source_page_refs=page_refs,
        source_text_refs=[raw_text],
        source_type_raw=asset.source_type.value,
        epistemic_status_raw=epistemic.value,
        epistemic_status_before_mapping=epistemic,
        epistemic_mapping_basis="RAW_PDF_SOURCE_TYPE_FIXED_MAPPING",
        parse_warnings=sorted(set(warnings)),
    )


def extract_temporal_candidates(
    pages: list[PdfPageText],
    source_type: GeologicalSourceType,
    filename: str,
) -> list[TemporalCandidate]:
    """Extract date candidates from page text and filename."""

    candidates: list[TemporalCandidate] = []
    known_year = _known_year_from_text(" ".join(page.page_text for page in pages) + " " + filename)
    for page in pages:
        for match in _date_matches(page.page_text, known_year):
            context = _context(page.page_text, match["start"], match["end"])
            classification_context = _context(
                page.page_text, match["start"], match["end"], window=12
            )
            role, rule, basis, confidence = classify_date_context(
                classification_context,
                source_type,
                match["raw"],
                year_inferred=match["year_inferred"],
            )
            candidates.append(
                _candidate(
                    source_type=source_type,
                    role=role,
                    raw=match["raw"],
                    parsed=match["date"],
                    page=page.page_number,
                    context=context,
                    rule=rule,
                    confidence=confidence,
                    basis=basis,
                )
            )
    for match in _date_matches(filename, known_year):
        candidates.append(
            _candidate(
                source_type=source_type,
                role=TemporalRole.FILENAME_DATE,
                raw=match["raw"],
                parsed=match["date"],
                page=None,
                context=filename,
                rule="filename_date_regex",
                confidence=TemporalConfidence.DERIVED,
                basis="FILENAME_DATE",
            )
        )
    return _dedupe_candidates(candidates)


def classify_date_context(
    context: str,
    source_type: GeologicalSourceType,
    raw: str,
    *,
    year_inferred: bool,
) -> tuple[TemporalRole, str, str, TemporalConfidence]:
    """Classify a date using context and source type."""

    local_flat = re.sub(r"\s+", "", context)
    confidence = TemporalConfidence.DERIVED if year_inferred else TemporalConfidence.VERIFIED
    basis_suffix = "YEAR_INFERRED_FROM_DOCUMENT_CONTEXT" if year_inferred else "EXPLICIT_DATE"
    if source_type in {GeologicalSourceType.TSP_REPORT, GeologicalSourceType.SONIC_FORECAST}:
        if any(
            token in local_flat
            for token in [
                "报告日期",
                "报告编制日期",
                "编制日期",
                "批准日期",
                "审核日期",
                "报告时间",
                "成文日期",
                "编制单位",
                "盖章",
            ]
        ):
            return (
                TemporalRole.DOCUMENTED,
                "forecast_document_date",
                "EXPLICIT_REPORT_OR_COMPILED_DATE",
                confidence,
            )
        if "签发日期" in local_flat:
            return TemporalRole.ISSUED, "forecast_issued_date", "EXPLICIT_ISSUED_DATE", confidence
        if any(
            token in local_flat for token in ["提交预报结果", "提交", "报送", "送达", "预报成果"]
        ):
            return (
                TemporalRole.SUBMITTED,
                "forecast_submission_date",
                "EXPLICIT_SUBMISSION_STATEMENT",
                confidence,
            )
        if any(
            token in local_flat
            for token in ["检测日期", "测试日期", "现场探测", "数据采集", "探测工作"]
        ):
            return (
                TemporalRole.OBSERVED,
                "forecast_detection_date",
                "EXPLICIT_DETECTION_DATE",
                confidence,
            )
    if source_type == GeologicalSourceType.FACE_SKETCH and any(
        token in local_flat for token in ["日期", "记录日期", "调绘日期", "观测日期", "签字日期"]
    ):
        return (
            TemporalRole.OBSERVED,
            "sketch_signed_date",
            "SIGNED_DOCUMENT_DATE",
            confidence,
        )
    if any(
        token in local_flat for token in ["检定有效期", "有效期", "校准", "规范", "合同", "引用"]
    ):
        return (
            TemporalRole.IRRELEVANT,
            "irrelevant_date_context",
            "IRRELEVANT_DATE_CONTEXT",
            TemporalConfidence.DERIVED,
        )
    return TemporalRole.IRRELEVANT, "unclassified_date_context", basis_suffix, confidence


def choose_extent(candidates: list[TemporalCandidate], role: TemporalRole) -> TemporalExtent | None:
    """Choose the first non-irrelevant candidate for a role."""

    for candidate in candidates:
        if candidate.semantic_role == role and candidate.parsed_value is not None:
            basis = candidate.basis
            if role == TemporalRole.SUBMITTED:
                basis = "SUBMITTED_TIME_DAY_PRECISION"
            local_date = candidate.source_local_date
            if local_date is None:
                continue
            return day_extent(
                local_date,
                basis=basis,
                candidate_ids=[candidate.candidate_id],
            )
    return None


def choose_available_extent(
    source_type: GeologicalSourceType,
    candidates: list[TemporalCandidate],
    submitted: TemporalExtent | None,
    issued: TemporalExtent | None,
    documented: TemporalExtent | None = None,
) -> TemporalExtent | None:
    """Choose available_time extent by source-specific policy."""

    if source_type in {GeologicalSourceType.TSP_REPORT, GeologicalSourceType.SONIC_FORECAST}:
        if submitted is not None:
            return submitted
        if issued is not None:
            return issued.model_copy(update={"basis": "ISSUED_TIME_DAY_PRECISION_FALLBACK"})
        if documented is not None:
            return documented.model_copy(update={"basis": "DOCUMENT_TIME_DAY_PRECISION_FALLBACK"})
        filename = choose_extent(candidates, TemporalRole.FILENAME_DATE)
        return filename.model_copy(update={"basis": "FILENAME_DATE"}) if filename else None
    if source_type == GeologicalSourceType.FACE_SKETCH:
        observed = choose_extent(candidates, TemporalRole.OBSERVED)
        return (
            observed.model_copy(update={"basis": "SIGNED_DOCUMENT_DATE_DAY_PRECISION_POLICY"})
            if observed
            else None
        )
    return None


def day_extent(day: date, *, basis: str, candidate_ids: list[str]) -> TemporalExtent:
    """Represent a day-precision date as a UTC interval."""

    zone = ZoneInfo(SOURCE_TIMEZONE)
    start = datetime(day.year, day.month, day.day, tzinfo=zone)
    end = start + timedelta(days=1)
    return TemporalExtent(
        earliest_possible_time=start.astimezone(UTC),
        latest_possible_time=end.astimezone(UTC),
        precision=TemporalPrecision.DAY,
        source_timezone=SOURCE_TIMEZONE,
        timezone_confidence=TemporalConfidence.ASSUMED,
        timezone_basis=TIMEZONE_BASIS,
        value_confidence=TemporalConfidence.DERIVED,
        basis=basis,
        candidate_ids=candidate_ids,
    )


def extract_spatial_candidates(
    pages: list[PdfPageText],
    filename: str = "",
) -> list[SpatialCandidate]:
    """Extract chainage candidates from page text."""

    candidates: list[SpatialCandidate] = []
    candidates.extend(_spatial_candidates_from_filename(filename))
    for page in pages:
        text = page.page_text
        range_spans: list[tuple[int, int]] = []
        for match in re.finditer(
            r"((?:DyK|DK|K)\s*\d+\s*\+\s*\d+(?:\.\d+)?\s*"
            r"[~\uff5e\-至到]\s*(?:DyK|DK|K)\s*\d+\s*\+\s*\d+(?:\.\d+)?)",
            text,
            flags=re.I,
        ):
            context = _context(text, match.start(), match.end())
            interval = parse_chainage_interval({}, match.group(1), ChainageValidationConfig())
            role = _range_role(context, page.page_number)
            candidates.append(
                SpatialCandidate(
                    candidate_id=stable_id(
                        "spatial", str(page.page_number), match.group(1), context, role
                    ),
                    role=role,
                    raw_expression=match.group(1),
                    start_chainage=interval.normalized_start_chainage if interval else None,
                    end_chainage=interval.normalized_end_chainage if interval else None,
                    source_page=page.page_number,
                    source_context=context,
                    extraction_rule=f"{role}_regex",
                    confidence="DERIVED",
                    validation_flags=interval.validation_flags if interval else [],
                )
            )
            range_spans.append((match.start(), match.end()))
        for match in re.finditer(r"(?:DyK|DK|K)\s*\d+\s*\+\s*\d+(?:\.\d+)?", text, flags=re.I):
            if any(match.start() >= start and match.end() <= end for start, end in range_spans):
                continue
            context = _context(text, match.start(), match.end())
            role, rule = _point_role(context)
            interval = parse_chainage_interval({}, match.group(0), ChainageValidationConfig())
            candidates.append(
                SpatialCandidate(
                    candidate_id=stable_id(
                        "spatial", str(page.page_number), match.group(0), context, role
                    ),
                    role=role,
                    raw_expression=match.group(0),
                    start_chainage=interval.normalized_start_chainage if interval else None,
                    end_chainage=interval.normalized_end_chainage if interval else None,
                    source_page=page.page_number,
                    source_context=context,
                    extraction_rule=rule,
                    confidence="DERIVED",
                    validation_flags=interval.validation_flags if interval else [],
                )
            )
    return _dedupe_spatial(candidates)


def _spatial_candidates_from_filename(filename: str) -> list[SpatialCandidate]:
    candidates: list[SpatialCandidate] = []
    if not filename:
        return candidates
    first_point = re.search(r"(?:DyK|DK|K)\s*\d+\s*\+\s*\d+(?:\.\d+)?", filename, flags=re.I)
    if first_point:
        interval = parse_chainage_interval({}, first_point.group(0), ChainageValidationConfig())
        candidates.append(
            SpatialCandidate(
                candidate_id=stable_id("spatial", "filename", first_point.group(0), filename),
                role="face_chainage_filename",
                raw_expression=first_point.group(0),
                start_chainage=interval.normalized_start_chainage if interval else None,
                end_chainage=interval.normalized_end_chainage if interval else None,
                source_page=None,
                source_context=filename,
                extraction_rule="filename_leading_chainage_face_fallback",
                confidence="DERIVED",
                validation_flags=interval.validation_flags if interval else [],
            )
        )
    for match in re.finditer(
        r"((?:DyK|DK|K)\s*\d+\s*\+\s*\d+(?:\.\d+)?\s*"
        r"[~\uff5e\-至到]\s*(?:DyK|DK|K)\s*\d+\s*\+\s*\d+(?:\.\d+)?)",
        filename,
        flags=re.I,
    ):
        interval = parse_chainage_interval({}, match.group(1), ChainageValidationConfig())
        candidates.append(
            SpatialCandidate(
                candidate_id=stable_id("spatial", "filename", match.group(1), filename),
                role="document_forecast_scope",
                raw_expression=match.group(1),
                start_chainage=interval.normalized_start_chainage if interval else None,
                end_chainage=interval.normalized_end_chainage if interval else None,
                source_page=None,
                source_context=filename,
                extraction_rule="filename_parenthetical_forecast_scope",
                confidence="DERIVED",
                validation_flags=interval.validation_flags if interval else [],
            )
        )
    return candidates


def _range_role(context: str, page_number: int) -> str:
    compact = re.sub(r"\s+", "", context)
    if page_number == 1 and any(token in compact for token in ["预报范围", "预报里程", "范围"]):
        return "document_forecast_scope"
    if any(token in compact for token in ["预报", "风险", "建议", "结论", "不良地质"]):
        return "forecast_range"
    if any(token in compact for token in ["已开挖", "揭示", "洞身", "掌子面素描"]):
        return "local_observed_range"
    if any(token in compact for token in ["布置", "测线", "检定", "校准", "仪器"]):
        return "instrument_or_calibration_range"
    return "unclassified_range"


def _point_role(context: str) -> tuple[str, str]:
    compact = re.sub(r"\s+", "", context)
    strict_tokens = [
        "开挖面里程",
        "当前掌子面",
        "掌子面里程",
        "预报掌子面里程",
        "掌子面桩号",
        "里程\uff1a",
    ]
    if any(token in compact for token in strict_tokens):
        return "face_chainage_strict", "explicit_face_chainage_label"
    return "point", "single_chainage_regex"


def _forecast_sections(
    _asset: GeologicalPdfSourceAsset,
    pages: list[PdfPageText],
    document: GeologicalDocument,
    parser_name: str,
    audits: dict[str, list[dict[str, str | int | None]]],
) -> list[EvidenceSection]:
    sections: list[EvidenceSection] = []
    table_sections = _table_row_sections(pages, parser_name, audits)
    table_pages = {section.source_page for section in table_sections}
    table_scopes = {
        (section.spatial_scope.start_chainage, section.spatial_scope.end_chainage)
        for section in table_sections
        if section.spatial_scope is not None
    }
    sections.extend(table_sections)
    for page in pages:
        for paragraph in _paragraphs(page.page_text):
            compact = re.sub(r"\s+", "", paragraph)
            if page.page_number in table_pages and _is_forecast_conclusion(compact):
                continue
            reason = _non_evidence_reason(compact)
            if reason is not None:
                audits["non_evidence_sections"].append(
                    _non_evidence_row(page.page_number, paragraph, reason)
                )
                continue
            ranges = _ranges_in_text(paragraph)
            scope = _scope_from_first_range(ranges, f"{parser_name}_section_range")
            flags = ranges[0].validation_flags if ranges else []
            if _is_forecast_conclusion(compact):
                if len(ranges) > 1:
                    sections.extend(
                        _split_multi_range_forecast_section(
                            paragraph,
                            page.page_number,
                            parser_name,
                            table_scopes,
                            audits,
                        )
                    )
                    continue
                if scope is not None and _range_is_document_scope_header(compact):
                    scope = None
                    flags = []
                if (
                    scope is not None
                    and (
                        scope.start_chainage,
                        scope.end_chainage,
                    )
                    in table_scopes
                ):
                    audits["unresolved_table_cells"].append(
                        {
                            "document_id": document.document_id,
                            "page": page.page_number,
                            "row_id": None,
                            "range": _scope_text(scope),
                            "text": _excerpt(paragraph, 300),
                            "status": "RESOLVED_BY_TABLE_ROW_DUPLICATE",
                        }
                    )
                    continue
                inherited_scope = None
                range_source = "SELF_RANGE"
                if scope is None and _can_inherit_document_scope(compact):
                    inherited_scope = document.document_spatial_scope
                    range_source = "LEGAL_DOCUMENT_SCOPE_INHERITANCE"
                if scope is None and inherited_scope is None:
                    audits["unresolved_table_cells"].append(
                        {
                            "document_id": document.document_id,
                            "page": page.page_number,
                            "row_id": None,
                            "range": None,
                            "text": _excerpt(paragraph, 300),
                            "status": "UNRESOLVED_TABLE_CELL",
                        }
                    )
                    continue
                sections.append(
                    EvidenceSection(
                        source_level="forecast_segment",
                        raw_text=_excerpt(paragraph, 1200),
                        source_page=page.page_number,
                        extraction_rule="forecast_conclusion_or_risk_section",
                        evidence_type=EvidenceType.GEOLOGICAL_FORECAST,
                        epistemic_status=GeologicalEpistemicStatus.FORECAST,
                        spatial_scope=scope or inherited_scope,
                        validation_flags=flags,
                        range_source=range_source,
                    )
                )
                continue
            if _is_excavated_or_exposed(compact):
                sections.append(
                    EvidenceSection(
                        source_level="already_excavated_observation",
                        raw_text=_excerpt(paragraph, 1200),
                        source_page=page.page_number,
                        extraction_rule="already_excavated_or_exposed_section",
                        evidence_type=EvidenceType.GEOLOGICAL_OBSERVATION,
                        epistemic_status=GeologicalEpistemicStatus.OBSERVED,
                        spatial_scope=scope or _face_scope(document),
                        validation_flags=flags,
                    )
                )
                continue
            if _is_design_background(compact):
                sections.append(
                    EvidenceSection(
                        source_level="design_geological_background",
                        raw_text=_excerpt(paragraph, 1200),
                        source_page=page.page_number,
                        extraction_rule="engineering_geological_overview_section",
                        evidence_type=EvidenceType.GEOLOGICAL_BACKGROUND,
                        epistemic_status=GeologicalEpistemicStatus.BACKGROUND,
                        spatial_scope=scope or document.document_spatial_scope,
                        validation_flags=flags,
                    )
                )
    return _dedupe_sections(sections)


def _table_row_sections(
    pages: list[PdfPageText],
    parser_name: str,
    audits: dict[str, list[dict[str, str | int | None]]],
) -> list[EvidenceSection]:
    sections: list[EvidenceSection] = []
    active_table = False
    for page in pages:
        text = page.page_text
        starts_table = _looks_like_forecast_table(text)
        if starts_table:
            active_table = True
        if not active_table:
            continue
        body_start = _table_body_start(text, starts_table)
        table_text = text[body_start:]
        header_text = text[:body_start]
        if starts_table:
            table_header = _table_header_excerpt(text)
            if table_header:
                audits["non_evidence_sections"].append(
                    _non_evidence_row(page.page_number, table_header, "TABLE_HEADER_ONLY")
                )
        range_matches = list(_range_matches(table_text))
        if active_table and not range_matches and _table_end_seen(table_text):
            active_table = False
            continue
        for index, match in enumerate(range_matches, start=1):
            raw_range = match.group(1)
            interval = parse_chainage_interval({}, raw_range, ChainageValidationConfig())
            if interval is None:
                continue
            next_start = (
                range_matches[index].start() if index < len(range_matches) else len(table_text)
            )
            if index == len(range_matches):
                next_start = _table_tail_index(table_text, match.end())
            block = table_text[match.start() : next_start]
            if not _table_block_has_geology(block):
                audits["non_evidence_sections"].append(
                    _non_evidence_row(page.page_number, block, "TABLE_ROW_WITHOUT_GEOLOGY")
                )
                continue
            scope = SpatialScope(
                start_chainage=interval.normalized_start_chainage,
                end_chainage=interval.normalized_end_chainage,
                basis="table_row_range",
            )
            row_id = stable_id("row", str(page.page_number), raw_range, _excerpt(block, 160))
            merged = _merge_table_cells(block)
            fragments = _resolved_table_fragments(block)
            sections.append(
                EvidenceSection(
                    source_level="forecast_segment",
                    raw_text=merged,
                    source_page=page.page_number,
                    extraction_rule="forecast_table_row_reconstruction",
                    evidence_type=EvidenceType.GEOLOGICAL_FORECAST,
                    epistemic_status=GeologicalEpistemicStatus.FORECAST,
                    spatial_scope=scope,
                    validation_flags=interval.validation_flags,
                    row_id=row_id,
                    range_source="TABLE_ROW_RANGE",
                    resolved_fragments=tuple(fragments),
                )
            )
            audits["table_row_audit"].append(
                {
                    "document_id": None,
                    "page": page.page_number,
                    "row_id": row_id,
                    "range": raw_range,
                    "merged_cells": merged,
                    "evidence_id": None,
                    "status": "RECONSTRUCTED",
                }
            )
        if _table_end_seen(table_text):
            active_table = False
        elif starts_table and not range_matches and header_text:
            active_table = True
    return sections


def _looks_like_forecast_table(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return all(token in compact for token in ["里程范围", "预报结论"]) and any(
        token in compact for token in ["风险提示", "围岩等级", "物探"]
    )


def _table_body_start(text: str, starts_table: bool) -> int:
    if not starts_table:
        return 0
    positions = [
        index for token in ["里程范围", "本次预报结论"] if (index := text.find(token)) >= 0
    ]
    return min(positions) if positions else 0


def _table_header_excerpt(text: str) -> str:
    start = _table_body_start(text, True)
    if start < 0:
        return ""
    end = _first_range_start(text[start:])
    header = text[start : start + end] if end is not None else text[start:]
    return _excerpt(header, 500)


def _first_range_start(text: str) -> int | None:
    matches = _range_matches(text)
    return matches[0].start() if matches else None


def _range_matches(text: str) -> list[re.Match[str]]:
    return list(
        re.finditer(
            r"((?:DyK|DK|K)\s*\d+\s*\+\s*\d+(?:\.\d+)?\s*"
            r"(?:~|\uff5e|\-)\s*(?:DyK|DK|K)?\s*\d+\s*\+\s*\d+(?:\.\d+)?)",
            text,
            flags=re.I,
        )
    )


def _table_tail_index(text: str, start: int) -> int:
    tail_markers = [
        index
        for token in ["下一次", "下次", "备注", "附图", "请施工单位"]
        if (index := text.find(token, start)) >= 0
    ]
    return min(tail_markers) if tail_markers else len(text)


def _table_end_seen(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return any(
        token in compact
        for token in [
            "下一次超前预报里程",
            "附图",
            "附表",
            "本次伯舒拉岭隧道进口右线的超前预报结果详见表",
        ]
    )


def _table_block_has_geology(block: str) -> bool:
    compact = re.sub(r"\s+", "", block)
    if _non_evidence_reason(compact) is not None:
        return False
    return any(
        token in compact
        for token in [
            "该段",
            "围岩",
            "岩性",
            "反射异常",
            "风险",
            "掉块",
            "涌水",
            "\u2163级",
            "\u2164级",
            "IV级",
            "V级",
        ]
    )


def _resolved_table_fragments(block: str) -> list[str]:
    fragments = []
    for paragraph in _paragraphs(block):
        compact = re.sub(r"\s+", "", paragraph)
        if _is_forecast_conclusion(compact) or _table_block_has_geology(paragraph):
            fragments.append(_excerpt(paragraph, 300))
    return fragments[:6]


def _merge_table_cells(block: str) -> str:
    return _excerpt(re.sub(r"\s+", " ", block).strip(), 1200)


def _split_multi_range_forecast_section(
    paragraph: str,
    page_number: int,
    parser_name: str,
    table_scopes: set[tuple[float | None, float | None]],
    audits: dict[str, list[dict[str, str | int | None]]],
) -> list[EvidenceSection]:
    matches = _range_matches(paragraph)
    sections: list[EvidenceSection] = []
    if len(matches) <= 1:
        return sections
    for index, match in enumerate(matches):
        raw_range = match.group(1)
        interval = parse_chainage_interval({}, raw_range, ChainageValidationConfig())
        if interval is None:
            continue
        scope_key = (interval.normalized_start_chainage, interval.normalized_end_chainage)
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(paragraph)
        block_start = _sentence_start(paragraph, match.start())
        block = paragraph[block_start:block_end].strip()
        block = _limit_to_single_range(block)
        if not _table_block_has_geology(block):
            audits["unresolved_table_cells"].append(
                {
                    "document_id": None,
                    "page": page_number,
                    "row_id": None,
                    "range": raw_range,
                    "text": _excerpt(block, 300),
                    "status": "UNRESOLVED_MULTI_RANGE_FRAGMENT",
                }
            )
            continue
        if scope_key in table_scopes:
            audits["unresolved_table_cells"].append(
                {
                    "document_id": None,
                    "page": page_number,
                    "row_id": None,
                    "range": raw_range,
                    "text": _excerpt(block, 300),
                    "status": "RESOLVED_BY_TABLE_ROW_DUPLICATE",
                }
            )
            continue
        scope = SpatialScope(
            start_chainage=interval.normalized_start_chainage,
            end_chainage=interval.normalized_end_chainage,
            basis=f"{parser_name}_multi_range_section_split",
        )
        sections.append(
            EvidenceSection(
                source_level="forecast_segment",
                raw_text=_excerpt(block, 1200),
                source_page=page_number,
                extraction_rule="multi_range_forecast_section_split",
                evidence_type=EvidenceType.GEOLOGICAL_FORECAST,
                epistemic_status=GeologicalEpistemicStatus.FORECAST,
                spatial_scope=scope,
                validation_flags=interval.validation_flags,
                row_id=stable_id("section", str(page_number), raw_range, _excerpt(block, 80)),
                range_source="SELF_RANGE",
            )
        )
    return sections


def _limit_to_single_range(text: str) -> str:
    matches = _range_matches(text)
    if len(matches) <= 1:
        return text
    return text[: matches[1].start()].rstrip("\uff0c,\uff1b; ")


def _sentence_start(text: str, position: int) -> int:
    starts = [text.rfind(mark, 0, position) for mark in ["。", "\uff1b", ";", "\n"]]
    start = max(starts)
    return 0 if start < 0 else start + 1


def _non_evidence_reason(compact: str) -> str | None:
    if not compact:
        return "EMPTY_OR_TITLE"
    if _is_table_header_only(compact):
        return "TABLE_HEADER_ONLY"
    if len(compact) < 12:
        return "SECTION_TITLE_ONLY"
    rules = [
        ("任务要求", "TASK_OR_WORK_REQUIREMENT"),
        ("目的要求", "TASK_OR_WORK_REQUIREMENT"),
        ("执行规范", "EXECUTION_STANDARD"),
        ("技术规程", "EXECUTION_STANDARD"),
        ("工作原理", "METHOD_PRINCIPLE"),
        ("原理简介", "METHOD_PRINCIPLE"),
        ("方法原理", "METHOD_PRINCIPLE"),
        ("震动信号", "METHOD_PRINCIPLE"),
        ("仪器", "INSTRUMENT_PARAMETER_OR_CALIBRATION"),
        ("校准", "INSTRUMENT_PARAMETER_OR_CALIBRATION"),
        ("检定", "INSTRUMENT_PARAMETER_OR_CALIBRATION"),
        ("施工组织", "CONSTRUCTION_ORGANIZATION"),
        ("图例", "LEGEND_EXPLANATION"),
        ("封面", "COVER_METADATA"),
        ("目录", "COVER_METADATA"),
    ]
    for token, reason in rules:
        if token in compact:
            return reason
    return None


def _is_table_header_only(compact: str) -> bool:
    if not all(token in compact for token in ["里程范围", "本次预报结论"]):
        return False
    geology_tokens = ["该段", "岩性", "弱风化", "节理", "破碎", "出水", "掉块", "坍塌"]
    return not any(token in compact for token in geology_tokens)


def _non_evidence_row(
    page_number: int,
    text: str,
    reason: str,
) -> dict[str, str | int | None]:
    return {
        "document_id": None,
        "page": page_number,
        "reason": reason,
        "text": _excerpt(text, 500),
    }


def _can_inherit_document_scope(compact: str) -> bool:
    return any(
        token in compact
        for token in [
            "本次预报范围整体",
            "本次预报结论",
            "最终结论",
            "全范围",
            "整体围岩",
        ]
    )


def _range_is_document_scope_header(compact: str) -> bool:
    if not compact.startswith(("预报范围", "预报里程", "本次预报范围")):
        return False
    return not _can_inherit_document_scope(compact)


def _sketch_interval_sections(pages: list[PdfPageText]) -> list[EvidenceSection]:
    sections: list[EvidenceSection] = []
    for page in pages:
        for paragraph in _paragraphs(page.page_text):
            compact = re.sub(r"\s+", "", paragraph)
            if not _is_excavated_or_exposed(compact):
                continue
            ranges = _ranges_in_text(paragraph)
            if not ranges:
                continue
            sections.append(
                EvidenceSection(
                    source_level="local_interval_observation",
                    raw_text=_excerpt(paragraph, 1200),
                    source_page=page.page_number,
                    extraction_rule="sketch_current_excavated_interval",
                    evidence_type=EvidenceType.GEOLOGICAL_OBSERVATION,
                    epistemic_status=GeologicalEpistemicStatus.OBSERVED,
                    spatial_scope=_scope_from_first_range(ranges, "sketch_local_interval"),
                    validation_flags=ranges[0].validation_flags,
                )
            )
    return _dedupe_sections(sections)


def _sketch_face_observation_text(
    pages: list[PdfPageText],
    page_number: int,
    face_chainage: float | None = None,
) -> str:
    for page in pages:
        if page.page_number == page_number and page.page_text.strip():
            cleaned = _remove_non_face_interval_sentences(page.page_text, face_chainage)
            return _excerpt(cleaned, 5000)
    return _first_nonempty_page_excerpt(pages, 5000)[1]


def _remove_non_face_interval_sentences(text: str, face_chainage: float | None) -> str:
    if face_chainage is None:
        return text
    kept: list[str] = []
    for sentence in re.split(r"(?<=。)", text):
        ranges = _ranges_in_text(sentence)
        if ranges and not any(
            interval.normalized_start_chainage is not None
            and interval.normalized_end_chainage is not None
            and interval.normalized_start_chainage
            <= face_chainage
            <= interval.normalized_end_chainage
            for interval in ranges
        ):
            continue
        kept.append(_remove_non_face_ranges(sentence, face_chainage))
    return "".join(kept)


def _remove_non_face_ranges(text: str, face_chainage: float) -> str:
    cleaned = re.sub(
        r"当前开挖\s*段落\s*(?:DyK|DK|K)\s*\d+\s*\+\s*\d+(?:\.\d+)?\s*"
        r"(?:—|--|-|~|\uff5e|至)\s*(?:DyK|DK|K)?\s*\d+\s*\+\s*\d+(?:\.\d+)?"
        r"\s*段[^。]*。?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    for match in _range_matches(cleaned):
        interval = parse_chainage_interval({}, match.group(1), ChainageValidationConfig())
        if (
            interval is None
            or interval.normalized_start_chainage is None
            or interval.normalized_end_chainage is None
        ):
            continue
        contains_face = (
            interval.normalized_start_chainage <= face_chainage <= interval.normalized_end_chainage
        )
        if not contains_face or interval.validation_flags:
            cleaned = cleaned.replace(match.group(1), "")
    cleaned = re.sub(
        r"当前开挖\s*段落\s*段[^。]*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"当前开挖\s*段落[^。]*。?",
        "",
        cleaned,
    )
    return cleaned


def _paragraphs(text: str) -> list[str]:
    chunks = re.split(r"\n\s*\n|(?<=。)\s*", text)
    return [chunk.strip() for chunk in chunks if len(chunk.strip()) >= 20]


def _is_cover_or_instrument_metadata(compact: str) -> bool:
    return any(
        token in compact for token in ["封面", "测线布置", "观测系统", "仪器", "检定", "校准"]
    )


def _is_forecast_conclusion(compact: str) -> bool:
    return any(token in compact for token in ["预报结论", "预报成果", "风险", "建议", "不良地质"])


def _is_excavated_or_exposed(compact: str) -> bool:
    return any(token in compact for token in ["已开挖", "揭示", "出露", "洞身开挖", "当前开挖"])


def _is_design_background(compact: str) -> bool:
    return any(token in compact for token in ["工程地质概况", "地层岩性", "区域地质", "设计地质"])


def _ranges_in_text(text: str) -> list[ChainageInterval]:
    intervals: list[ChainageInterval] = []
    for match in re.finditer(
        r"((?:DyK|DK|K)\s*\d+\s*\+\s*\d+(?:\.\d+)?\s*"
        r"[~\uff5e\-至到]\s*(?:DyK|DK|K)\s*\d+\s*\+\s*\d+(?:\.\d+)?)",
        text,
        flags=re.I,
    ):
        interval = parse_chainage_interval({}, match.group(1), ChainageValidationConfig())
        if interval is not None:
            intervals.append(interval)
    return intervals


def _scope_from_first_range(
    intervals: list[ChainageInterval],
    basis: str,
) -> SpatialScope | None:
    if not intervals:
        return None
    interval = intervals[0]
    return SpatialScope(
        start_chainage=interval.normalized_start_chainage,
        end_chainage=interval.normalized_end_chainage,
        basis=basis,
    )


def _face_scope(document: GeologicalDocument) -> SpatialScope | None:
    if document.face_chainage is None:
        return None
    return SpatialScope(
        start_chainage=document.face_chainage,
        end_chainage=document.face_chainage,
        basis=document.face_chainage_basis or "face_chainage",
    )


def _dedupe_sections(sections: list[EvidenceSection]) -> list[EvidenceSection]:
    seen: set[tuple[str, int, str]] = set()
    out: list[EvidenceSection] = []
    for section in sections:
        key = (section.source_level, section.source_page, section.raw_text)
        if key in seen:
            continue
        seen.add(key)
        out.append(section)
    return out


def extract_structured_attributes(
    text: str,
    source_level: str,
) -> dict[str, str | int | float | bool | None]:
    """Extract deterministic geological attributes from the evidence text."""

    normalized = re.sub(r"\s+", "", text)
    checkbox = _checkbox_attributes(text) if source_level == "face_observation" else {}
    narrative = _face_attribute_narrative(text) if source_level == "face_observation" else text
    narrative_normalized = re.sub(r"\s+", "", narrative)
    attribute_text = narrative_normalized if source_level == "face_observation" else normalized
    lithology = _first_keyword(
        attribute_text,
        [
            "板岩夹变质砂岩",
            "板岩夹砂岩",
            "变质砂岩",
            "花岗岩",
            "板岩",
            "砂岩",
            "片岩",
            "泥岩",
            "灰岩",
        ],
    )
    weathering = checkbox.get("weathering") or _first_keyword(
        attribute_text, ["全风化", "强风化", "中风化", "弱风化", "微风化", "未风化"]
    )
    joint = _joint_development(attribute_text)
    rock_state = _first_keyword(
        attribute_text,
        ["破碎-极破碎", "较破碎", "相对破碎", "极破碎", "破碎", "较完整", "完整"],
    )
    stability = _first_keyword(
        attribute_text,
        ["自稳性较差", "稳定性较差", "稳定性差", "自稳性差", "基本稳定", "稳定"],
    )
    narrative_water = _water_observation(narrative_normalized)
    form_water = checkbox.get("water_state")
    water_state = _water_state(attribute_text, checkbox, narrative_water)
    water_type = _water_type(attribute_text) or _form_water_type(form_water)
    anomaly_level = _anomaly_level(attribute_text, source_level)
    attributes: dict[str, str | int | float | bool | None] = {
        "lithology": lithology,
        "lithology_raw_value": lithology,
        "lithology_canonical_value": lithology,
        "lithology_normalization_rule": "LONGEST_SPECIFIC_MATCH" if lithology else None,
        "weathering": weathering,
        "surrounding_rock_grade": _rock_grade(attribute_text),
        "suggested_surrounding_rock_grade": checkbox.get("suggested_surrounding_rock_grade"),
        "design_surrounding_rock_grade": checkbox.get("design_surrounding_rock_grade"),
        "joint_development": joint,
        "rock_mass_state": rock_state,
        "stability": stability,
        "water_state": water_state,
        "water_type": water_type,
        "form_water_status": form_water,
        "narrative_water_observation": narrative_water,
        "water_status_conflict": _status_conflict(form_water, narrative_water),
        "block_fall_or_collapse": _block_fall(attribute_text),
        "deformation": _first_keyword(attribute_text, ["大变形", "变形", "收敛"]),
        "anomaly_level": anomaly_level,
        "anomaly_trigger_text": _anomaly_trigger_text(
            narrative if source_level == "face_observation" else text
        ),
        "source_risk_text": _risk_text(narrative if source_level == "face_observation" else text),
        "forecast_qualifiers": _forecast_qualifiers(normalized, source_level),
        "face_state": checkbox.get("face_state"),
        "narrative_face_state": _face_state_from_text(attribute_text),
        "face_state_conflict": _status_conflict(
            checkbox.get("face_state"),
            _face_state_from_text(attribute_text),
        ),
        "excavated_face_state": checkbox.get("excavated_face_state"),
        "narrative_stability_observation": stability,
        "stability_status_conflict": _status_conflict(
            checkbox.get("excavated_face_state"),
            stability,
        ),
        "rock_strength_interval": checkbox.get("rock_strength_interval"),
        "structure_spacing": checkbox.get("structure_spacing"),
        "extension": checkbox.get("extension"),
        "roughness": checkbox.get("roughness"),
        "openness": checkbox.get("openness"),
        "karst_development": checkbox.get("karst_development"),
    }
    for key, value in list(attributes.items()):
        if value is None:
            attributes[key] = "UNKNOWN"
    attributes["attribute_extraction_scope"] = source_level
    return attributes


def _first_keyword(text: str, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in text:
            return candidate
    return None


def _joint_development(text: str) -> str | None:
    candidates = [
        "节理裂隙发育密集",
        "节理裂隙较发育",
        "节理裂隙发育",
        "节理发育密集",
        "裂隙发育密集",
        "发育密集",
        "较发育",
        "节理发育",
        "裂隙发育",
        "节理不发育",
    ]
    matches: list[str] = []
    for candidate in candidates:
        if candidate not in text:
            continue
        if any(candidate in existing and candidate != existing for existing in matches):
            continue
        matches.append(candidate)
    return ";".join(matches) if matches else None


def _checkbox_attributes(text: str) -> dict[str, str | None]:
    return {
        "face_state": _checked_option(
            text,
            "掌子面状态",
            ["稳定", "正面掉块", "正面挤出", "正面不能自稳"],
        ),
        "excavated_face_state": _checked_option(
            text,
            "毛开挖",
            ["自稳", "随时间松弛、掉块", "自稳困难、要及时支护", "要超前支护"],
        ),
        "rock_strength_interval": _checked_option(
            text,
            "岩石强度",
            ["R\uff1e60", "30\uff1cR≤60", "15\uff1cR≤30", "5\uff1cR≤15", "R\uff1c5"],
        ),
        "weathering": _checked_option(
            text,
            "风化程度",
            ["未风化", "微风化", "弱风化", "强风化", "全风化"],
        ),
        "structure_spacing": _checked_option(
            text,
            "间距",
            ["\uff1e1.5", "0.6\uff5e1.5", "0.2\uff5e0.6", "0.06\uff5e0.2", "\uff1c0.06"],
        ),
        "extension": _checked_option(text, "延伸性", ["极差", "差", "中等", "好", "极好"]),
        "roughness": _checked_option(
            text,
            "粗糙度",
            ["明显台阶状", "粗糙波纹状", "平整光滑有擦痕", "平整光滑"],
        ),
        "openness": _checked_option(
            text,
            "张开性",
            [
                "密闭\uff1c0.1",
                "部分张开0.1\uff5e0.5",
                "张开0.5\uff5e1.0",
                "无充填张开\uff1e1.0",
                "黏土充填",
            ],
        ),
        "water_state": _checked_option(
            text,
            "涌水状态",
            ["无水", "湿润", "偶有渗水", "涌出或喷出"],
        ),
        "karst_development": _checked_option(text, "岩溶发育程度", ["无", "弱", "中等", "强烈"]),
        "design_surrounding_rock_grade": _grade_after_label(text, "设计围岩级别"),
        "suggested_surrounding_rock_grade": _grade_after_label(text, "建议围岩级别"),
    }


def _checked_option(text: str, label: str, options: list[str]) -> str | None:
    segment = _label_segment(text, label)
    if not segment:
        return None
    compact = re.sub(r"\s+", "", segment)
    for option in sorted(options, key=len, reverse=True):
        normalized_option = re.sub(r"\s+", "", option)
        suffix_checked = rf"{re.escape(normalized_option)}\u221a"
        prefix_checked = rf"(?:^|[:;\uff1a\uff1b,\uff0c])\u221a{re.escape(normalized_option)}"
        if re.search(suffix_checked, compact) or re.search(prefix_checked, compact):
            return option
    return None


def _label_segment(text: str, label: str) -> str:
    compact = re.sub(r"\s+", "", text)
    start = compact.find(label)
    if start < 0:
        return ""
    labels = [
        "掌子面状态",
        "毛开挖",
        "岩石强度",
        "风化程度",
        "间距",
        "延伸性",
        "粗糙度",
        "张开性",
        "涌水状态",
        "岩溶发育程度",
        "设计围岩级别",
        "建议围岩级别",
        "地质描述",
    ]
    end_candidates = [
        compact.find(next_label, start + len(label))
        for next_label in labels
        if next_label != label and compact.find(next_label, start + len(label)) > start
    ]
    end = min(end_candidates) if end_candidates else min(len(compact), start + 160)
    return compact[start:end]


def _grade_after_label(text: str, label: str) -> str | None:
    segment = _label_segment(text, label)
    match = re.search(r"[\u2162\u2163\u2164VI]+", segment)
    return f"{match.group(0)}级" if match else None


def _narrative_segment(text: str) -> str:
    compact = re.sub(r"\s+", "", text)
    for label in ["地质描述", "地质 描述"]:
        start = compact.find(re.sub(r"\s+", "", label))
        if start >= 0:
            return compact[start:]
    return ""


def _face_attribute_narrative(text: str) -> str:
    narrative = _narrative_segment(text)
    kept: list[str] = []
    for sentence in re.split(r"(?<=。)|(?<=\uff1b)|;", narrative):
        if not sentence:
            continue
        if re.search(r"当前开挖\s*段落", sentence):
            continue
        if _range_matches(sentence):
            continue
        kept.append(sentence)
    return "".join(kept)


def _water_state(
    text: str,
    checkbox: dict[str, str | None],
    narrative_water: str | None = None,
) -> str | None:
    if narrative_water:
        return narrative_water
    if checkbox.get("water_state"):
        return checkbox["water_state"]
    if any(token in text for token in ["未见出水", "无涌水", "未见涌水", "无水"]):
        return "NONE"
    return _water_type(text)


def _water_observation(text: str) -> str | None:
    if "渗滴水" in text:
        return "渗滴水"
    return _water_type(text)


def _water_type(text: str) -> str | None:
    if any(token in text for token in ["未见出水", "无涌水", "未见涌水", "无水"]):
        return "NONE"
    mappings = [
        ("滴渗水-线状出水", "滴渗水-线状出水"),
        ("渗滴水-线状出水", "滴渗水-线状出水"),
        ("线-股状出水", "线-股状出水"),
        ("线状水-股状水", "线-股状出水"),
        ("线状出水", "线状出水"),
        ("股状出水", "股状出水"),
        ("涌出或喷出", "喷出"),
        ("突涌水", "突涌水"),
        ("渗滴水", "滴渗水"),
        ("滴渗水", "滴渗水"),
        ("偶有渗水", "偶有渗水"),
        ("经常渗水", "偶有渗水"),
        ("湿润", "湿润"),
        ("喷出", "喷出"),
    ]
    for token, value in mappings:
        if token in text:
            return value
    return None


def _form_water_type(form_water: str | None) -> str | None:
    if form_water == "无水":
        return "NONE"
    return form_water


def _status_conflict(form_value: str | None, narrative_value: str | bool | None) -> bool:
    if form_value in {None, "UNKNOWN"} or narrative_value in {None, "UNKNOWN"}:
        return False
    normalized_form = str(form_value).replace("无水", "NONE")
    normalized_narrative = str(narrative_value)
    return (
        normalized_form not in normalized_narrative and normalized_narrative not in normalized_form
    )


def _block_fall(text: str) -> bool | str:
    if any(token in text for token in ["未见掉块", "无掉块"]):
        return False
    return True if any(token in text for token in ["掉块", "坍塌", "塌方"]) else "UNKNOWN"


def _anomaly_level(text: str, source_level: str = "") -> str | None:
    if source_level == "face_observation" and not _actual_anomaly_text(text):
        return None
    if any(token in text for token in ["未见明显反射异常", "无明显反射异常", "未发现异常"]):
        return "NONE"
    return _first_keyword(text, ["强异常", "中等异常", "弱异常", "明显反射异常", "异常"])


def _actual_anomaly_text(text: str) -> bool:
    if any(token in text for token in ["如有异常及时上报", "异常及时上报"]):
        text = text.replace("如有异常及时上报", "").replace("异常及时上报", "")
    return any(token in text for token in ["反射异常", "异常带", "异常区", "异常涌水"])


def _anomaly_trigger_text(text: str) -> str:
    compact = re.sub(r"\s+", "", text)
    match = re.search(
        r"[^。\uff1b;]{0,40}(?:反射异常|异常带|异常区|异常涌水)[^。\uff1b;]{0,60}",
        compact,
    )
    return _excerpt(match.group(0), 160) if match else "UNKNOWN"


def _rock_grade(text: str) -> str | None:
    match = re.search(r"[\u2162\u2163\u2164VI]+级|[IIIIVX]+级", text)
    return match.group(0) if match else None


def _risk_text(text: str) -> str:
    compact = re.sub(r"\s+", "", text)
    compact = re.sub(r"如有异常及时上报[^。\uff1b;]*", "", compact)
    match = re.search(
        r"[^。\uff1b;\n]{0,40}(?:风险|坍塌|涌水|突涌水|突水|掉块|失稳|变形|出水|卡机)[^。\uff1b;\n]{0,80}",
        compact,
    )
    return _excerpt(match.group(0), 160) if match else "UNKNOWN"


def _forecast_qualifiers(text: str, source_level: str) -> str:
    if source_level not in {"forecast_segment", "design_geological_background"}:
        return "UNKNOWN"
    matches = [token for token in ["可能", "局部", "建议", "较强", "较弱"] if token in text]
    return ";".join(matches) if matches else "UNKNOWN"


def _face_state_from_text(text: str) -> str | None:
    return _first_keyword(
        text,
        ["正面掉块", "正面挤出", "不能自稳", "自稳性较差", "稳定性较差", "稳定"],
    )


def _date_matches(text: str, known_year: int | None) -> list[DateMatch]:
    matches: list[DateMatch] = []
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            parsed, inferred = _parse_date_match(match, known_year)
            if parsed is None:
                continue
            matches.append(
                {
                    "raw": match.group(0),
                    "date": parsed,
                    "start": match.start(),
                    "end": match.end(),
                    "year_inferred": inferred,
                }
            )
    out: list[DateMatch] = []
    occupied: list[tuple[int, int]] = []
    sorted_matches = sorted(
        matches,
        key=lambda value: (value["start"], -(value["end"] - value["start"])),
    )
    for item in sorted_matches:
        if any(item["start"] >= start and item["end"] <= end for start, end in occupied):
            continue
        occupied.append((item["start"], item["end"]))
        out.append(item)
    return out


def _parse_date_match(match: re.Match[str], known_year: int | None) -> tuple[date | None, bool]:
    try:
        groups = match.groupdict()
        inferred = False
        if groups.get("y"):
            year_raw = groups["y"]
            year = _chinese_year(year_raw) if year_raw.startswith("二") else int(year_raw)
        elif known_year:
            year = known_year
            inferred = True
        else:
            return None, False
        month_raw = groups.get("m")
        day_raw = groups.get("d")
        if month_raw is None or day_raw is None:
            return None, inferred
        month = _chinese_number(month_raw)
        day = _chinese_number(day_raw)
        parsed = date(year, month, day)
        if parsed.year < 2023 or parsed.year > 2026:
            return None, inferred
        return parsed, inferred
    except Exception:
        return None, False


def _known_year_from_text(text: str) -> int | None:
    match = re.search(r"20\d{2}", text)
    return int(match.group(0)) if match else None


def _chinese_year(value: str) -> int:
    digits = {
        "\u3007": "0",
        "零": "0",
        "一": "1",
        "二": "2",
        "三": "3",
        "四": "4",
        "五": "5",
        "六": "6",
        "七": "7",
        "八": "8",
        "九": "9",
    }
    return int("".join(digits.get(char, char) for char in value))


def _chinese_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    mapping = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + mapping[value[-1]]
    if "十" in value:
        left, right = value.split("十", 1)
        return mapping.get(left, 1) * 10 + (mapping[right] if right else 0)
    return mapping[value]


def _candidate(
    *,
    source_type: GeologicalSourceType,
    role: TemporalRole,
    raw: str,
    parsed: date,
    page: int | None,
    context: str,
    rule: str,
    confidence: TemporalConfidence,
    basis: str,
) -> TemporalCandidate:
    zone = ZoneInfo(SOURCE_TIMEZONE)
    dt = datetime(parsed.year, parsed.month, parsed.day, tzinfo=zone).astimezone(UTC)
    return TemporalCandidate(
        candidate_id=stable_id("temporal", source_type.value, raw, str(page), context, role.value),
        semantic_role=role,
        raw_expression=raw,
        parsed_value=dt,
        source_local_date=parsed,
        precision=TemporalPrecision.DAY,
        source_type=source_type.value,
        source_page=page,
        source_context=context,
        extraction_rule=rule,
        confidence=confidence,
        basis=basis,
    )


def _dedupe_candidates(candidates: list[TemporalCandidate]) -> list[TemporalCandidate]:
    seen: set[tuple[str, str, int | None]] = set()
    out: list[TemporalCandidate] = []
    for candidate in candidates:
        key = (candidate.semantic_role.value, candidate.raw_expression, candidate.source_page)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _dedupe_spatial(candidates: list[SpatialCandidate]) -> list[SpatialCandidate]:
    seen: set[tuple[str, float | None, float | None]] = set()
    out: list[SpatialCandidate] = []
    for candidate in candidates:
        key = (candidate.role, candidate.start_chainage, candidate.end_chainage)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _document_scope(
    candidates: list[SpatialCandidate],
    source_type: GeologicalSourceType,
) -> SpatialScope | None:
    if source_type in {GeologicalSourceType.TSP_REPORT, GeologicalSourceType.SONIC_FORECAST}:
        ranges = [
            candidate
            for candidate in candidates
            if candidate.role in {"document_forecast_scope", "forecast_range"}
            and not candidate.validation_flags
        ]
        if not ranges:
            ranges = [
                candidate
                for candidate in candidates
                if candidate.role in {"document_forecast_scope", "forecast_range"}
            ]
        if not ranges:
            return None
        selected = ranges[0]
        return SpatialScope(
            start_chainage=selected.start_chainage,
            end_chainage=selected.end_chainage,
            basis="document_forecast_range",
        )
    points = [
        candidate
        for candidate in candidates
        if candidate.role in {"face_chainage_strict", "face_chainage_filename"}
    ]
    if points:
        return SpatialScope(
            start_chainage=points[0].start_chainage,
            end_chainage=points[0].end_chainage,
            basis="face_observation_point",
        )
    return None


def _choose_face_candidate(
    candidates: list[SpatialCandidate],
    document_scope: SpatialScope | None,
    source_type: GeologicalSourceType,
) -> SpatialCandidate | None:
    strict = [candidate for candidate in candidates if candidate.role == "face_chainage_strict"]
    fallback = [candidate for candidate in candidates if candidate.role == "face_chainage_filename"]
    for candidate in [*strict, *fallback]:
        if _face_validation_status(candidate, document_scope, source_type) in {
            "WITHIN_FORECAST_SCOPE",
            "ADJACENT_TO_FORECAST_SCOPE",
            "NOT_REQUIRED_FOR_SKETCH",
        }:
            return candidate
    return strict[0] if source_type == GeologicalSourceType.FACE_SKETCH and strict else None


def _face_validation_status(
    candidate: SpatialCandidate | None,
    document_scope: SpatialScope | None,
    source_type: GeologicalSourceType,
) -> str:
    if candidate is None:
        return "UNKNOWN"
    if source_type == GeologicalSourceType.FACE_SKETCH:
        return "NOT_REQUIRED_FOR_SKETCH"
    if (
        document_scope is None
        or candidate.start_chainage is None
        or document_scope.start_chainage is None
        or document_scope.end_chainage is None
    ):
        return "UNKNOWN"
    start = min(document_scope.start_chainage, document_scope.end_chainage)
    end = max(document_scope.start_chainage, document_scope.end_chainage)
    value = candidate.start_chainage
    if start <= value <= end:
        return "WITHIN_FORECAST_SCOPE"
    if abs(value - start) <= 5.0 or abs(value - end) <= 5.0:
        return "ADJACENT_TO_FORECAST_SCOPE"
    return "CONFLICT_WITH_FORECAST_SCOPE"


def _document_warnings(
    temporal_candidates: list[TemporalCandidate],
    spatial_candidates: list[SpatialCandidate],
) -> list[str]:
    warnings: set[str] = set()
    if not [
        candidate
        for candidate in temporal_candidates
        if candidate.semantic_role != TemporalRole.IRRELEVANT
    ]:
        warnings.add("DOCUMENT_TEMPORAL_METADATA_UNKNOWN")
    if not spatial_candidates:
        warnings.add("DOCUMENT_SPATIAL_METADATA_UNKNOWN")
    for candidate in spatial_candidates:
        warnings.update(candidate.validation_flags)
    return sorted(warnings)


def _extent_to_value(extent: TemporalExtent | None) -> TemporalValue | None:
    if extent is None:
        return None
    return TemporalValue(
        value=extent.earliest_possible_time,
        confidence=TemporalValueConfidence.DERIVED,
        basis=extent.basis,
    )


def _first_nonempty_page_excerpt(pages: list[PdfPageText], length: int) -> tuple[int, str]:
    for page in pages:
        if page.page_text.strip():
            return page.page_number, _excerpt(page.page_text, length)
    return 1, ""


def _chainage_interval_from_scope(
    scope: SpatialScope | None,
    validation_flags: list[str],
) -> ChainageInterval | None:
    if scope is None or scope.start_chainage is None or scope.end_chainage is None:
        return None
    chainage_flags = [flag for flag in validation_flags if flag.startswith("CHAINAGE_")]
    if scope.start_chainage == scope.end_chainage:
        direction = ChainageDirection.POINT
    elif scope.start_chainage < scope.end_chainage:
        direction = ChainageDirection.INCREASING
    else:
        direction = ChainageDirection.DECREASING
    return ChainageInterval(
        start_chainage=scope.start_chainage,
        end_chainage=scope.end_chainage,
        direction=direction,
        confidence=SpatialValueConfidence.DERIVED,
        basis=scope.basis,
        raw_start_chainage=scope.start_chainage,
        raw_end_chainage=scope.end_chainage,
        normalized_start_chainage=min(scope.start_chainage, scope.end_chainage),
        normalized_end_chainage=max(scope.start_chainage, scope.end_chainage),
        normalization_reason=None,
        spatial_scope_usable=not chainage_flags,
        validation_flags=chainage_flags,
    )


def _extract_tunnel_name(text: str) -> str | None:
    match = re.search(r"伯舒拉岭隧道[^\n]{0,10}右线", text)
    return match.group(0) if match else None


def _context(text: str, start: int, end: int, window: int = 80) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - window) : min(len(text), end + window)]).strip()


def _excerpt(text: str, length: int) -> str:
    return re.sub(r"\s+", " ", text).strip()[:length]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
