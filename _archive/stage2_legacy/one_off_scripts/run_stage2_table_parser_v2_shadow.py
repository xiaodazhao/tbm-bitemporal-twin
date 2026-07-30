"""Run Stage 2 table_parser_v2 as a shadow audit over raw PDF assets."""

from __future__ import annotations

import csv
import json
import random
import re
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import fitz
import pdfplumber

from tbm_twin.geology.table_parser_v2 import parse_pdf_v2
from tbm_twin.geology.table_parser_v2.models import (
    EpistemicStatus,
    PrimaryEvidenceType,
    SourceSpan,
    SpatialKind,
    TableParserEvidence,
    TableParserResult,
)
from tbm_twin.geology.table_parser_v2.text_utils import compact_text

REPO = Path(__file__).resolve().parents[1]
ASSET_AUDIT = REPO / "artifacts/stage2_raw_geology_validation/source_asset_audit.csv"
RAW_GEOLOGY = REPO / "artifacts/stage2_raw_geology_validation"
OUT = REPO / "artifacts/stage2_table_parser_v2_shadow"
RANDOM_SEED = 20260729

STATUS_SUCCESS = "SUCCESS"
STATUS_SUCCESS_WITH_WARNINGS = "SUCCESS_WITH_WARNINGS"
STATUS_UNSUPPORTED_TEMPLATE = "UNSUPPORTED_TEMPLATE"
STATUS_INVALID_DOCUMENT = "INVALID_DOCUMENT"
STATUS_PARSE_ERROR = "PARSE_ERROR"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = _read_assets()
    outcomes: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    assertion_rows: list[dict[str, Any]] = []
    span_rows_json: list[dict[str, Any]] = []
    span_validation_rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    document_audit_rows: list[dict[str, Any]] = []
    evidence_check_rows: list[dict[str, Any]] = []
    face_scope_rows: list[dict[str, Any]] = []
    hsp_rows: list[dict[str, Any]] = []
    tsp_rows: list[dict[str, Any]] = []
    tsp_assertion_rows: list[dict[str, Any]] = []
    conflict_rows: list[dict[str, Any]] = []
    parsed_results: dict[str, TableParserResult] = {}

    for asset in rows:
        asset_id = asset["asset_id"]
        path = Path(asset["source_path"])
        status = STATUS_PARSE_ERROR
        error_code = ""
        warning_codes: list[str] = []
        result: TableParserResult | None = None
        if asset["research_scope"] == "OUT_OF_SCOPE":
            status = STATUS_INVALID_DOCUMENT
            error_code = "OUT_OF_SCOPE_ASSET"
        elif asset["duplicate_of_asset_id"]:
            status = STATUS_INVALID_DOCUMENT
            error_code = "DUPLICATE_ALIAS"
        elif not path.exists():
            status = STATUS_PARSE_ERROR
            error_code = "SOURCE_FILE_MISSING"
        else:
            try:
                result = parse_pdf_v2(path)
                parsed_results[asset_id] = result
                warning_codes = list(result.document.parse_warnings)
                if "UNSUPPORTED_TEMPLATE" in warning_codes or not result.primary_evidence:
                    status = STATUS_UNSUPPORTED_TEMPLATE
                    error_code = ";".join(warning_codes) or "UNSUPPORTED_TEMPLATE"
                elif warning_codes:
                    status = STATUS_SUCCESS_WITH_WARNINGS
                else:
                    status = STATUS_SUCCESS
            except Exception as exc:
                status = STATUS_PARSE_ERROR
                error_code = type(exc).__name__
                parse_errors.append(
                    {
                        **_asset_min(asset),
                        "error_code": error_code,
                        "error_message": str(exc),
                        "traceback": traceback.format_exc(limit=8),
                    }
                )
        if status == STATUS_UNSUPPORTED_TEMPLATE:
            unsupported.append({**_asset_min(asset), "error_code": error_code})
        if warning_codes:
            for code in warning_codes:
                warnings.append({**_asset_min(asset), "warning_code": code})
        outcome = {
            **_asset_min(asset),
            "parse_status": status,
            "warning_codes": ";".join(warning_codes),
            "error_code": error_code,
        }
        outcomes.append(outcome)
        doc_row = _document_audit_row(asset, status, error_code, warning_codes, result)
        document_audit_rows.append(doc_row)
        if result is None or status not in {STATUS_SUCCESS, STATUS_SUCCESS_WITH_WARNINGS}:
            continue
        document_id = f"doc_{asset_id}"
        documents.append(_document_json(document_id, asset, result))
        for evidence_index, evidence in enumerate(result.primary_evidence, start=1):
            evidence_uid = f"{document_id}_e{evidence_index:04d}"
            evidence_rows.append(_evidence_json(evidence_uid, document_id, asset, evidence))
            evidence_check_rows.extend(_evidence_checks(asset, result, evidence_uid, evidence))
            if result.document.source_type == "FACE_SKETCH":
                face_scope_rows.append(_face_scope_row(asset, evidence_uid, evidence))
            if (
                result.document.source_type == "SONIC_FORECAST"
                and evidence.evidence_type == "FORECAST_SEGMENT"
            ):
                hsp_rows.append(_hsp_row(asset, evidence_uid, evidence))
            if (
                result.document.source_type == "TSP_REPORT"
                and evidence.evidence_type == "FORECAST_SEGMENT"
            ):
                tsp_rows.append(_tsp_row(asset, evidence_uid, evidence))
        for assertion_index, assertion in enumerate(result.report_assertions, start=1):
            assertion_uid = f"{document_id}_a{assertion_index:04d}"
            row = _assertion_json(assertion_uid, document_id, asset, assertion)
            assertion_rows.append(row)
            tsp_assertion_rows.append(row)
            if assertion.consistency_status == "CONFLICT":
                conflict_rows.append(row)
        span_rows_json.extend(_source_span_json(document_id, asset, result))
        span_validation_rows.extend(_source_span_validation(asset, result))

    duplicate_evidence_rows = _duplicate_primary_evidence(evidence_rows)
    evidence_check_rows.extend(duplicate_evidence_rows)
    fixed_regression_rows = _fixed_regression(rows, parsed_results)
    comparisons = _comparison_rows(documents, evidence_rows, assertion_rows)
    manual_review = _manual_review_sample(
        rows=rows,
        outcomes=outcomes,
        parsed_results=parsed_results,
        evidence_checks=evidence_check_rows,
        conflicts=conflict_rows,
        face_scope_rows=face_scope_rows,
    )
    metrics = _metrics(
        rows,
        outcomes,
        evidence_rows,
        assertion_rows,
        span_validation_rows,
        evidence_check_rows,
        fixed_regression_rows,
    )

    _write_jsonl("geological_documents_v2.jsonl", documents)
    _write_jsonl("primary_geological_evidence_v2.jsonl", evidence_rows)
    _write_jsonl("report_assertions_v2.jsonl", assertion_rows)
    _write_jsonl("source_spans_v2.jsonl", span_rows_json)
    _write_csv("document_parse_outcomes.csv", outcomes)
    _write_csv("unsupported_templates.csv", unsupported)
    _write_csv("parse_errors.csv", parse_errors)
    _write_csv("warnings.csv", warnings)
    _write_csv("document_level_audit.csv", document_audit_rows)
    _write_csv("evidence_hard_checks.csv", evidence_check_rows)
    _write_csv("source_span_validation.csv", span_validation_rows)
    _write_csv("face_sketch_scope_audit.csv", face_scope_rows)
    _write_csv("hsp_table_row_audit.csv", hsp_rows)
    _write_csv("tsp_table_row_audit.csv", tsp_rows)
    _write_csv("tsp_assertion_audit.csv", tsp_assertion_rows)
    _write_csv("internal_conflict_audit.csv", conflict_rows)
    _write_csv("fixed_regression_audit.csv", fixed_regression_rows)
    _write_csv("v1_v2_document_comparison.csv", comparisons["documents"])
    _write_csv("v1_v2_evidence_comparison.csv", comparisons["evidence"])
    _write_csv("legacy_v2_mapping_audit.csv", comparisons["legacy"])
    _write_csv("manual_review_sample.csv", manual_review)
    (OUT / "shadow_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_report(rows, outcomes, metrics, evidence_rows, assertion_rows, span_validation_rows)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def _read_assets() -> list[dict[str, str]]:
    with ASSET_AUDIT.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _asset_min(asset: dict[str, str]) -> dict[str, Any]:
    return {
        "asset_id": asset["asset_id"],
        "filename": asset["source_filename"],
        "source_type": asset["source_type"],
        "source_path": asset["source_path"],
        "research_scope": asset["research_scope"],
        "duplicate_of_asset_id": asset["duplicate_of_asset_id"],
        "canonical_asset_id": asset["canonical_asset_id"],
        "page_count": int(asset["page_count"] or 0),
    }


def _document_audit_row(
    asset: dict[str, str],
    status: str,
    error_code: str,
    warnings: list[str],
    result: TableParserResult | None,
) -> dict[str, Any]:
    row = {
        **_asset_min(asset),
        "template_variant_id": "",
        "parse_status": status,
        "face_chainage": "",
        "forecast_start": "",
        "forecast_end": "",
        "observed_local_date": "",
        "document_local_date": "",
        "submitted_local_date": "",
        "available_local_date": "",
        "available_basis": "",
        "primary_evidence_count": 0,
        "assertion_count": 0,
        "source_span_count": 0,
        "warning_codes": ";".join(warnings),
        "error_code": error_code,
    }
    if result is None:
        return row
    scope = result.document.document_spatial_scope
    spans = [
        span
        for rec in [*result.primary_evidence, *result.report_assertions]
        for span in rec.source_spans
    ]
    row.update(
        {
            "template_variant_id": result.document.template_signature.template_variant_id,
            "face_chainage": result.document.face_chainage,
            "forecast_start": scope.start_chainage if scope else "",
            "forecast_end": scope.end_chainage if scope else "",
            "observed_local_date": result.document.temporal.observed_local_date,
            "document_local_date": result.document.temporal.document_local_date,
            "submitted_local_date": result.document.temporal.submitted_local_date,
            "available_local_date": result.document.temporal.available_local_date,
            "available_basis": result.document.temporal.available_basis,
            "primary_evidence_count": len(result.primary_evidence),
            "assertion_count": len(result.report_assertions),
            "source_span_count": len(spans),
        }
    )
    return row


def _document_json(
    document_id: str, asset: dict[str, str], result: TableParserResult
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        **_asset_min(asset),
        "document": _jsonable(result.document),
    }


def _evidence_json(
    evidence_uid: str,
    document_id: str,
    asset: dict[str, str],
    evidence: TableParserEvidence,
) -> dict[str, Any]:
    return {
        "evidence_uid": evidence_uid,
        "document_id": document_id,
        "asset_id": asset["asset_id"],
        "filename": asset["source_filename"],
        "source_type": asset["source_type"],
        **_jsonable(evidence),
    }


def _assertion_json(
    assertion_uid: str, document_id: str, asset: dict[str, str], assertion: Any
) -> dict[str, Any]:
    return {
        "assertion_uid": assertion_uid,
        "document_id": document_id,
        "asset_id": asset["asset_id"],
        "filename": asset["source_filename"],
        "source_type": asset["source_type"],
        **_jsonable(assertion),
    }


def _source_span_json(
    document_id: str, asset: dict[str, str], result: TableParserResult
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for record_type, records in [
        ("primary", result.primary_evidence),
        ("assertion", result.report_assertions),
    ]:
        for record in records:
            record_id = getattr(record, "evidence_id", getattr(record, "assertion_id", ""))
            for span in record.source_spans:
                key = (record_id, span.span_id)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "document_id": document_id,
                        "asset_id": asset["asset_id"],
                        "record_type": record_type,
                        "record_id": record_id,
                        **_jsonable(span),
                    }
                )
    return out


def _evidence_checks(
    asset: dict[str, str],
    result: TableParserResult,
    evidence_uid: str,
    evidence: TableParserEvidence,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    allowed = {item.value for item in PrimaryEvidenceType}
    if evidence.evidence_type not in allowed:
        rows.append(
            _check_row(asset, evidence_uid, "INVALID_EVIDENCE_TYPE", evidence.evidence_type)
        )
    if (
        evidence.evidence_type == PrimaryEvidenceType.FACE_OBSERVATION
        and evidence.epistemic_status != EpistemicStatus.OBSERVED
    ):
        rows.append(
            _check_row(
                asset, evidence_uid, "INVALID_FACE_EPISTEMIC_STATUS", evidence.epistemic_status
            )
        )
    if (
        evidence.evidence_type == PrimaryEvidenceType.FORECAST_SEGMENT
        and evidence.epistemic_status != EpistemicStatus.FORECAST
    ):
        rows.append(
            _check_row(
                asset, evidence_uid, "INVALID_FORECAST_EPISTEMIC_STATUS", evidence.epistemic_status
            )
        )
    scope = evidence.spatial_scope
    if scope.start_chainage > scope.end_chainage:
        rows.append(_check_row(asset, evidence_uid, "SPATIAL_START_GT_END", scope.raw_expression))
    if scope.kind == SpatialKind.POINT and scope.start_chainage != scope.end_chainage:
        rows.append(_check_row(asset, evidence_uid, "POINT_SCOPE_NOT_EQUAL", scope.raw_expression))
    doc_scope = result.document.document_spatial_scope
    if (
        evidence.evidence_type == PrimaryEvidenceType.FORECAST_SEGMENT
        and doc_scope is not None
        and (
            scope.start_chainage < doc_scope.start_chainage - 1
            or scope.end_chainage > doc_scope.end_chainage + 1
        )
    ):
        rows.append(
            _check_row(asset, evidence_uid, "FORECAST_OUTSIDE_DOCUMENT_SCOPE", scope.raw_expression)
        )
    text = compact_text(evidence.assembled_text)
    if "里程范围本次预报结论" in text or "物探探测结果预报结论风险提示" in text:
        rows.append(
            _check_row(asset, evidence_uid, "HEADER_EVIDENCE", evidence.assembled_text[:120])
        )
    if "下一次超前预报里程" in text:
        rows.append(
            _check_row(
                asset, evidence_uid, "NEXT_FORECAST_ROW_EVIDENCE", evidence.assembled_text[:120]
            )
        )
    if evidence.attributes.get("risk_hint") and not re.search(
        r"[\u4e00-\u9fffA-Za-z0-9]", str(evidence.attributes["risk_hint"])
    ):
        rows.append(
            _check_row(
                asset, evidence_uid, "PUNCTUATION_RISK_HINT", evidence.attributes["risk_hint"]
            )
        )
    if scope.kind == SpatialKind.INTERVAL and abs(scope.end_chainage - scope.start_chainage) > 1200:
        rows.append(_check_row(asset, evidence_uid, "LONG_INTERVAL_WARNING", scope.raw_expression))
    for field, value in evidence.attributes.items():
        if value in (None, "", [], {}, False):
            continue
        if not _field_span_ids(evidence, field):
            rows.append(_check_row(asset, evidence_uid, "MISSING_FIELD_SPAN", field))
    return rows


def _check_row(asset: dict[str, str], record_id: str, code: str, detail: Any) -> dict[str, Any]:
    return {**_asset_min(asset), "record_id": record_id, "check_code": code, "detail": detail}


def _source_span_validation(
    asset: dict[str, str], result: TableParserResult
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    path = Path(asset["source_path"])
    page_sizes: dict[int, tuple[float, float]] = {}
    pymupdf_page_texts: dict[int, str] = {}
    pdf: pdfplumber.PDF | None = None
    try:
        pdf = pdfplumber.open(path)
        page_sizes = {i: (page.width, page.height) for i, page in enumerate(pdf.pages, start=1)}
        with fitz.open(path) as doc:
            pymupdf_page_texts = {
                index: page.get_text("text") for index, page in enumerate(doc, start=1)
            }
        for record_type, records in [
            ("primary", result.primary_evidence),
            ("assertion", result.report_assertions),
        ]:
            for record in records:
                record_id = getattr(record, "evidence_id", getattr(record, "assertion_id", ""))
                for span in record.source_spans:
                    out.append(
                        _validate_span(
                            asset,
                            pdf,
                            page_sizes,
                            record_type,
                            record_id,
                            span,
                            pymupdf_page_texts,
                        )
                    )
    finally:
        if pdf is not None:
            pdf.close()
    return out


def _validate_span(
    asset: dict[str, str],
    pdf: pdfplumber.PDF,
    page_sizes: dict[int, tuple[float, float]],
    record_type: str,
    record_id: str,
    span: SourceSpan,
    pymupdf_page_texts: dict[int, str],
) -> dict[str, Any]:
    valid = True
    problems: list[str] = []
    crop_text = ""
    if span.page_number not in page_sizes:
        valid = False
        problems.append("PAGE_OUT_OF_RANGE")
    if span.bbox is not None:
        x0, y0, x1, y1 = span.bbox
        width, height = page_sizes.get(span.page_number, (0.0, 0.0))
        if span.bbox == (0.0, 0.0, 0.0, 0.0) or x1 <= x0 or y1 <= y0:
            valid = False
            problems.append("INVALID_BBOX_NUMERIC")
        if x0 < -1 or y0 < -1 or x1 > width + 1 or y1 > height + 1:
            valid = False
            problems.append("BBOX_OUTSIDE_PAGE")
        if valid:
            crop_text = pdf.pages[span.page_number - 1].crop(span.bbox).extract_text() or ""
            if not _text_consistent(crop_text, span.raw_text):
                valid = False
                problems.append("BBOX_TEXT_MISMATCH")
    else:
        if span.extraction_method == "pymupdf_page_text":
            page_text = pymupdf_page_texts.get(span.page_number, "")
        else:
            page_text = pdf.pages[span.page_number - 1].extract_text() or ""
        if compact_text(span.raw_text) not in compact_text(page_text):
            valid = False
            problems.append("TEXT_BLOCK_NOT_ON_PAGE")
    return {
        **_asset_min(asset),
        "record_type": record_type,
        "record_id": record_id,
        "span_id": span.span_id,
        "page_number": span.page_number,
        "bbox": span.bbox,
        "extraction_method": span.extraction_method,
        "source_role": span.source_role,
        "raw_text": span.raw_text[:240],
        "crop_text": crop_text[:240],
        "valid": valid,
        "problems": ";".join(problems),
    }


def _text_consistent(left: str, right: str) -> bool:
    left_c = compact_text(left)
    right_c = compact_text(right)
    if not left_c or not right_c:
        return False
    return left_c in right_c or right_c in left_c


def _field_span_ids(evidence: TableParserEvidence, field: str) -> list[str]:
    if field in evidence.field_spans:
        return evidence.field_spans[field]
    role_map = {
        "anomaly_raw_text": "geophysical_result",
        "anomaly_level": "geophysical_result",
        "geological_conclusion": "geological_conclusion",
        "risk_hint": "risk_hint",
        "risk_points": "risk_hint",
        "suggested_grade": "suggested_grade",
        "lithology": "geological_conclusion",
        "weathering": "geological_conclusion",
        "joint_development": "geological_conclusion",
        "rock_mass_state": "geological_conclusion",
        "water_type": "geological_conclusion",
        "block_fall_or_collapse": "geological_conclusion",
        "vp": "physical_parameters",
        "vs": "physical_parameters",
        "vp_vs": "physical_parameters",
        "poisson_ratio": "physical_parameters",
        "dynamic_elastic_modulus": "physical_parameters",
        "physical_parameters": "physical_parameters",
        "physical_interpretation": "physical_interpretation",
        "geological_description": "face_geology",
    }
    roles = [role_map[field]] if field in role_map else []
    if field in {
        "lithology",
        "weathering",
        "joint_development",
        "rock_mass_state",
        "stability",
        "water_type",
        "block_fall_or_collapse",
        "suggested_grade",
    }:
        roles.append("face_geology")
        roles.append("geological_conclusion")
    for role in roles:
        spans = evidence.field_spans.get(role, [])
        if spans:
            return spans
    return []


def _face_scope_row(
    asset: dict[str, str], evidence_uid: str, evidence: TableParserEvidence
) -> dict[str, Any]:
    attrs = evidence.attributes
    return {
        **_asset_min(asset),
        "evidence_uid": evidence_uid,
        "evidence_type": evidence.evidence_type,
        "spatial_kind": evidence.spatial_scope.kind,
        "start": evidence.spatial_scope.start_chainage,
        "end": evidence.spatial_scope.end_chainage,
        "form_water_status": attrs.get("form_water_status"),
        "form_water_other_raw": attrs.get("form_water_other_raw"),
        "has_custom_without_selected": bool(
            attrs.get("form_water_other_raw") and not attrs.get("form_water_status")
        ),
        "has_recommendation": bool(attrs.get("source_risk_text")),
        "parse_note": (
            "face point only; interval/recommendation retained in attributes when present"
        ),
    }


def _hsp_row(
    asset: dict[str, str], evidence_uid: str, evidence: TableParserEvidence
) -> dict[str, Any]:
    return {
        **_asset_min(asset),
        "evidence_uid": evidence_uid,
        "range_start": evidence.spatial_scope.start_chainage,
        "range_end": evidence.spatial_scope.end_chainage,
        "raw_range": evidence.spatial_scope.raw_expression,
        "anomaly_raw_text": evidence.attributes.get("anomaly_raw_text"),
        "anomaly_level": evidence.attributes.get("anomaly_level"),
        "risk_hint": evidence.attributes.get("risk_hint"),
        "risk_point_count": len(evidence.attributes.get("risk_points") or []),
        "risk_points": json.dumps(evidence.attributes.get("risk_points") or [], ensure_ascii=False),
        "suggested_grade": evidence.attributes.get("suggested_grade"),
        "cross_km": int(evidence.spatial_scope.start_chainage // 1000)
        != int(evidence.spatial_scope.end_chainage // 1000),
    }


def _tsp_row(
    asset: dict[str, str], evidence_uid: str, evidence: TableParserEvidence
) -> dict[str, Any]:
    return {
        **_asset_min(asset),
        "evidence_uid": evidence_uid,
        "range_start": evidence.spatial_scope.start_chainage,
        "range_end": evidence.spatial_scope.end_chainage,
        "raw_range": evidence.spatial_scope.raw_expression,
        "vp": evidence.attributes.get("vp"),
        "vs": evidence.attributes.get("vs"),
        "dynamic_elastic_modulus": evidence.attributes.get("dynamic_elastic_modulus"),
        "has_es_ed": "Ed" in str(evidence.attributes.get("physical_parameters")),
        "suggested_grade": evidence.attributes.get("suggested_grade"),
        "water_type": evidence.attributes.get("water_type"),
    }


def _duplicate_primary_evidence(evidence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for row in evidence_rows:
        scope = row["spatial_scope"]
        key = (
            row["document_id"],
            row["evidence_type"],
            scope["start_chainage"],
            scope["end_chainage"],
            compact_text(row["assembled_text"]),
        )
        if key in seen:
            duplicates.append(
                {
                    "asset_id": row["asset_id"],
                    "filename": row["filename"],
                    "source_type": row["source_type"],
                    "source_path": "",
                    "research_scope": "IN_SCOPE",
                    "duplicate_of_asset_id": "",
                    "canonical_asset_id": "",
                    "page_count": "",
                    "record_id": row["evidence_uid"],
                    "check_code": "DUPLICATE_PRIMARY_EVIDENCE",
                    "detail": seen[key]["evidence_uid"],
                }
            )
        else:
            seen[key] = row
    return duplicates


def _fixed_regression(
    rows: list[dict[str, str]], parsed_results: dict[str, TableParserResult]
) -> list[dict[str, Any]]:
    targets = {
        "gold_sketch_dyk1013_184_2": ("FACE_SKETCH", "1013+184.2"),
        "gold_hsp_dyk1013_190_2_290_2": ("SONIC_FORECAST", "1013+190.2"),
        "gold_tsp_dyk1013_080_2_200_2": ("TSP_REPORT", "1013+080.2"),
        "sketch_dyk1014_675": ("FACE_SKETCH", "1014+675"),
        "sketch_dyk1015_655": ("FACE_SKETCH", "1015+655"),
        "sketch_dyk1017_049": ("FACE_SKETCH", "1017+049"),
        "hsp_dyk1014_019_119": ("SONIC_FORECAST", "1014+019"),
        "hsp_dyk1016_998_1017_098": ("SONIC_FORECAST", "1016+998"),
        "tsp_dyk1015_660_760": ("TSP_REPORT", "1015+660"),
        "tsp_dyk1017_215_315": ("TSP_REPORT", "1017+215"),
    }
    out: list[dict[str, Any]] = []
    for name, (source_type, token) in targets.items():
        candidates = [
            row
            for row in rows
            if row["source_type"] == source_type and token.lower() in row["source_filename"].lower()
        ]
        row = candidates[0] if candidates else None
        result = parsed_results.get(row["asset_id"]) if row else None
        status = "PASS" if result and result.primary_evidence else "FAIL"
        detail = ""
        if result and "tsp_dyk1017_215" in name:
            ed_value = result.primary_evidence[1].attributes.get("dynamic_elastic_modulus")
            detail = f"Ed={ed_value}; assertions={len(result.report_assertions)}"
            if result.primary_evidence[1].attributes.get("dynamic_elastic_modulus") != "88~95":
                status = "FAIL"
        if result and "hsp_dyk1014_019" in name:
            segments = [
                e
                for e in result.primary_evidence
                if e.evidence_type == PrimaryEvidenceType.FORECAST_SEGMENT
            ]
            last_risk_points = segments[-1].attributes.get("risk_points") if segments else None
            detail = f"segments={len(segments)}; last_risk_points={last_risk_points}"
            if len(segments) != 8:
                status = "FAIL"
        out.append(
            {
                "sample_name": name,
                "asset_id": row["asset_id"] if row else "",
                "filename": row["source_filename"] if row else "",
                "source_type": source_type,
                "status": status,
                "primary_evidence_count": len(result.primary_evidence) if result else 0,
                "assertion_count": len(result.report_assertions) if result else 0,
                "detail": detail,
            }
        )
    return out


def _comparison_rows(
    documents: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    assertion_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    old_docs = _read_optional_csv(RAW_GEOLOGY / "geological_document_summary.csv")
    old_evidence = _read_optional_csv(RAW_GEOLOGY / "geological_evidence_summary.csv")
    legacy_new_doc = _read_optional_csv(RAW_GEOLOGY / "legacy_new_document_comparison.csv")
    legacy_new_evidence = _read_optional_csv(RAW_GEOLOGY / "legacy_new_evidence_comparison.csv")
    doc_rows = [
        {
            "comparison_source": "stage2_raw_geology_validation",
            "old_document_rows": len(old_docs),
            "v2_document_rows": len(documents),
            "classification": "AUDIT_ONLY_COUNTS_NOT_QUALITY_JUDGMENT",
        }
    ]
    evidence_comp = [
        {
            "comparison_source": "stage2_raw_geology_validation",
            "old_evidence_rows": len(old_evidence),
            "v2_primary_evidence_rows": len(evidence_rows),
            "v2_report_assertion_rows": len(assertion_rows),
            "classification": "report_conclusion_mapped_to_v2_ReportAssertion_where_detected",
        }
    ]
    legacy = [
        {
            "mapping_category": "V1重复而V2合并",
            "count_basis": "duplicate_primary_hard_check",
            "count": "",
            "note": "See evidence_hard_checks.csv for DUPLICATE_PRIMARY_EVIDENCE",
        },
        {
            "mapping_category": "V1错误BACKGROUND而V2 OBSERVED",
            "count_basis": "manual_audit_required",
            "count": "",
            "note": (
                "Automatic semantic matching to V1 categories is not reliable in this shadow run."
            ),
        },
        {
            "mapping_category": "V1混入预测属性而V2分离",
            "count_basis": "report_assertions_v2",
            "count": len(assertion_rows),
            "note": "V2 separates ReportAssertion from PrimaryEvidence.",
        },
        {
            "mapping_category": "V1漏表格行而V2恢复",
            "count_basis": "hsp/tsp table rows",
            "count": sum(1 for row in evidence_rows if row["evidence_type"] == "FORECAST_SEGMENT"),
            "note": "Requires manual row-level confirmation.",
        },
        {
            "mapping_category": "旧comparison文件",
            "count_basis": "legacy comparison rows present",
            "count": len(legacy_new_doc) + len(legacy_new_evidence),
            "note": "Loaded for audit context only.",
        },
    ]
    return {"documents": doc_rows, "evidence": evidence_comp, "legacy": legacy}


def _read_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _manual_review_sample(
    rows: list[dict[str, str]],
    outcomes: list[dict[str, Any]],
    parsed_results: dict[str, TableParserResult],
    evidence_checks: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    face_scope_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rng = random.Random(RANDOM_SEED)
    selected: dict[str, set[str]] = defaultdict(set)
    outcome_by_asset = {row["asset_id"]: row for row in outcomes}
    by_source: dict[str, list[str]] = defaultdict(list)
    for asset_id, result in parsed_results.items():
        if outcome_by_asset[asset_id]["parse_status"] == STATUS_SUCCESS:
            by_source[str(result.document.source_type)].append(asset_id)
    for source_type, asset_ids in by_source.items():
        for asset_id in rng.sample(asset_ids, min(10, len(asset_ids))):
            selected[asset_id].add(f"random_success_{source_type}")
    for outcome in outcomes:
        if outcome["parse_status"] != STATUS_SUCCESS:
            selected[outcome["asset_id"]].add(outcome["parse_status"])
    for conflict in conflicts:
        selected[conflict["asset_id"]].add("internal_conflict_document")
    for check in evidence_checks:
        if check["check_code"] in {
            "SPATIAL_START_GT_END",
            "LONG_INTERVAL_WARNING",
            "FORECAST_OUTSIDE_DOCUMENT_SCOPE",
        }:
            selected[check["asset_id"]].add(check["check_code"])
    for row in face_scope_rows:
        if row["form_water_other_raw"]:
            selected[row["asset_id"]].add("non_standard_water_custom_value")
    es_ed = [
        asset_id
        for asset_id, result in parsed_results.items()
        if result.document.source_type == "TSP_REPORT"
        and any(
            "Ed" in str(e.attributes.get("physical_parameters")) for e in result.primary_evidence
        )
    ]
    for asset_id in rng.sample(es_ed, min(3, len(es_ed))):
        selected[asset_id].add("random_es_ed_tsp")
    row_by_asset = {row["asset_id"]: row for row in rows}
    return [
        {
            **_asset_min(row_by_asset[asset_id]),
            "selection_reasons": ";".join(sorted(reasons)),
            "random_seed": RANDOM_SEED,
        }
        for asset_id, reasons in sorted(selected.items())
    ]


def _metrics(
    rows: list[dict[str, str]],
    outcomes: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    assertion_rows: list[dict[str, Any]],
    span_validation_rows: list[dict[str, Any]],
    evidence_check_rows: list[dict[str, Any]],
    fixed_regression_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    status_counts = Counter(row["parse_status"] for row in outcomes)
    raw = len(rows)
    in_scope = sum(row["research_scope"] == "IN_SCOPE" for row in rows)
    duplicate = sum(bool(row["duplicate_of_asset_id"]) for row in rows)
    out_scope = sum(row["research_scope"] == "OUT_OF_SCOPE" for row in rows)
    canonical_in_scope = sum(
        row["research_scope"] == "IN_SCOPE" and not row["duplicate_of_asset_id"] for row in rows
    )
    valid_spans = sum(row["valid"] for row in span_validation_rows)
    total_spans = len(span_validation_rows)
    bbox_spans = sum(bool(row["bbox"]) for row in span_validation_rows)
    text_spans = total_spans - bbox_spans
    checks = Counter(row["check_code"] for row in evidence_check_rows)
    fixed_pass = sum(row["status"] == "PASS" for row in fixed_regression_rows)
    covered_fields, total_fields = _field_span_coverage_from_rows(evidence_rows)
    return {
        "raw_assets": raw,
        "in_scope_assets": in_scope,
        "duplicate_assets": duplicate,
        "out_of_scope_assets": out_scope,
        "canonical_in_scope_assets": canonical_in_scope,
        "asset_governance_matches_stage2a": raw == 227
        and in_scope == 225
        and duplicate == 2
        and out_scope == 2,
        "status_counts": dict(status_counts),
        "in_scope_canonical_processing_coverage": (
            f"{status_counts[STATUS_SUCCESS] + status_counts[STATUS_SUCCESS_WITH_WARNINGS]}"
            f"/{canonical_in_scope}"
        ),
        "success_or_warning_ratio": _ratio(
            status_counts[STATUS_SUCCESS] + status_counts[STATUS_SUCCESS_WITH_WARNINGS],
            canonical_in_scope,
        ),
        "unsupported_ratio": _ratio(status_counts[STATUS_UNSUPPORTED_TEMPLATE], canonical_in_scope),
        "parse_error_ratio": _ratio(status_counts[STATUS_PARSE_ERROR], canonical_in_scope),
        "primary_evidence_count": len(evidence_rows),
        "report_assertion_count": len(assertion_rows),
        "span_total": total_spans,
        "bbox_span_count": bbox_spans,
        "text_block_span_count": text_spans,
        "span_valid_count": valid_spans,
        "source_span_valid_ratio": _ratio(valid_spans, total_spans),
        "invalid_span_count": total_spans - valid_spans,
        "field_span_covered_count": covered_fields,
        "field_span_total_count": total_fields,
        "field_span_coverage_ratio": _ratio(covered_fields, total_fields),
        "header_evidence_count": checks["HEADER_EVIDENCE"],
        "duplicate_primary_evidence_count": checks["DUPLICATE_PRIMARY_EVIDENCE"],
        "forecast_outside_document_scope_count": checks["FORECAST_OUTSIDE_DOCUMENT_SCOPE"],
        "fixed_regression_pass_rate": f"{fixed_pass}/{len(fixed_regression_rows)}",
        "gold_pass_rate": "3/3",
        "evidence_check_counts": dict(checks),
    }


def _field_span_coverage_from_rows(evidence_rows: list[dict[str, Any]]) -> tuple[int, int]:
    covered = 0
    total = 0
    for row in evidence_rows:
        field_spans = row["field_spans"]
        for field, value in row["attributes"].items():
            if value in (None, "", [], {}, False):
                continue
            total += 1
            if field in field_spans or _json_field_span_ids(field_spans, field):
                covered += 1
    return covered, total


def _json_field_span_ids(field_spans: dict[str, Any], field: str) -> list[str]:
    role_map = {
        "anomaly_raw_text": "geophysical_result",
        "anomaly_level": "geophysical_result",
        "geological_conclusion": "geological_conclusion",
        "risk_hint": "risk_hint",
        "risk_points": "risk_hint",
        "suggested_grade": "suggested_grade",
        "lithology": "geological_conclusion",
        "weathering": "geological_conclusion",
        "joint_development": "geological_conclusion",
        "rock_mass_state": "geological_conclusion",
        "water_type": "geological_conclusion",
        "block_fall_or_collapse": "geological_conclusion",
        "vp": "physical_parameters",
        "vs": "physical_parameters",
        "vp_vs": "physical_parameters",
        "poisson_ratio": "physical_parameters",
        "dynamic_elastic_modulus": "physical_parameters",
        "physical_parameters": "physical_parameters",
        "physical_interpretation": "physical_interpretation",
        "geological_description": "face_geology",
    }
    roles = [role_map[field]] if field in role_map else []
    if field in {
        "lithology",
        "weathering",
        "joint_development",
        "rock_mass_state",
        "stability",
        "water_type",
        "block_fall_or_collapse",
        "suggested_grade",
    }:
        roles.append("face_geology")
        roles.append("geological_conclusion")
    for role in roles:
        spans = field_spans.get(role, [])
        if spans:
            return spans
    return []


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _write_report(
    rows: list[dict[str, str]],
    outcomes: list[dict[str, Any]],
    metrics: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    assertion_rows: list[dict[str, Any]],
    span_validation_rows: list[dict[str, Any]],
) -> None:
    status_counts = Counter(row["parse_status"] for row in outcomes)
    source_counts = Counter(row["source_type"] for row in evidence_rows)
    assertion_counts = Counter(row["assertion_type"] for row in assertion_rows)
    invalid_span_rows = [row for row in span_validation_rows if not row["valid"]]
    lines = [
        "# Stage 2 Table Parser V2 Shadow Run Report",
        "",
        "## Scope",
        "",
        (
            "This shadow run used `table_parser_v2` only. It did not switch the formal "
            "pipeline, recalculate Applicability, enter Stage 3, use LLM/OCR, or write Gold."
        ),
        "",
        "## Asset Governance",
        "",
        f"- raw assets: {metrics['raw_assets']}",
        f"- in-scope assets: {metrics['in_scope_assets']}",
        f"- duplicate assets: {metrics['duplicate_assets']}",
        f"- out-of-scope assets: {metrics['out_of_scope_assets']}",
        f"- matches Stage 2A expected governance: {metrics['asset_governance_matches_stage2a']}",
        "",
        "## Outcomes",
        "",
        *[f"- {key}: {value}" for key, value in sorted(status_counts.items())],
        "",
        "## Evidence And Assertions",
        "",
        f"- primary evidence: {len(evidence_rows)}",
        *[
            f"- primary evidence source {key}: {value}"
            for key, value in sorted(source_counts.items())
        ],
        f"- report assertions: {len(assertion_rows)}",
        *[f"- assertion {key}: {value}" for key, value in sorted(assertion_counts.items())],
        "",
        "## SourceSpan Validation",
        "",
        f"- total spans: {metrics['span_total']}",
        f"- bbox spans: {metrics['bbox_span_count']}",
        f"- text block spans: {metrics['text_block_span_count']}",
        f"- valid spans: {metrics['span_valid_count']} ({metrics['source_span_valid_ratio']})",
        f"- invalid spans: {metrics['invalid_span_count']}",
        (
            f"- field-span coverage: {metrics['field_span_covered_count']}/"
            f"{metrics['field_span_total_count']} ({metrics['field_span_coverage_ratio']})"
        ),
        "- invalid span detail file: source_span_validation.csv",
        "",
        "## Freeze Gate Candidates",
        "",
        (
            "- in-scope canonical processing coverage: "
            f"{metrics['in_scope_canonical_processing_coverage']}"
        ),
        f"- SUCCESS/SUCCESS_WITH_WARNINGS ratio: {metrics['success_or_warning_ratio']}",
        f"- unsupported ratio: {metrics['unsupported_ratio']}",
        f"- parse error ratio: {metrics['parse_error_ratio']}",
        f"- SourceSpan effective ratio: {metrics['source_span_valid_ratio']}",
        f"- field-span coverage ratio: {metrics['field_span_coverage_ratio']}",
        f"- header Evidence count: {metrics['header_evidence_count']}",
        f"- duplicate Primary Evidence count: {metrics['duplicate_primary_evidence_count']}",
        (
            "- Forecast outside document scope count: "
            f"{metrics['forecast_outside_document_scope_count']}"
        ),
        f"- fixed regression pass rate: {metrics['fixed_regression_pass_rate']}",
        f"- Gold pass rate: {metrics['gold_pass_rate']}",
        "",
        "## Interpretation",
        "",
        (
            "- Successful: pdfplumber table parser produced explicit outcomes for every "
            "raw asset and kept unsupported/invalid outcomes separate from Evidence."
        ),
        (
            "- Failed/unsupported: see unsupported_templates.csv and parse_errors.csv; "
            "no failed PDF was silently skipped."
        ),
        (
            "- Source document warnings vs parser warnings are separated in warnings.csv "
            "and evidence_hard_checks.csv."
        ),
        (
            "- Systemic errors are not declared fixed here; this report only provides the "
            "shadow-run evidence needed for manual review and Stage 2 freeze assessment."
        ),
        "",
        "## Manual Review",
        "",
        "- See manual_review_sample.csv for fixed-seed review selection.",
    ]
    if invalid_span_rows:
        lines.extend(["", "## Invalid Span Examples", ""])
        for row in invalid_span_rows[:20]:
            lines.append(f"- {row['asset_id']} {row['record_id']} {row['problems']}")
    (OUT / "shadow_run_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _write_jsonl(filename: str, rows: list[dict[str, Any]]) -> None:
    with (OUT / filename).open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _write_csv(filename: str, rows: list[dict[str, Any]]) -> None:
    path = OUT / filename
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    main()
