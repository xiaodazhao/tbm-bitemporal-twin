# Stage 2 Table Parser V2 Shadow Run Report

## Scope

This shadow run used `table_parser_v2` only. It did not switch the formal pipeline, recalculate Applicability, enter Stage 3, use LLM/OCR, or write Gold.

## Asset Governance

- raw assets: 227
- in-scope assets: 225
- duplicate assets: 2
- out-of-scope assets: 2
- matches Stage 2A expected governance: True

## Outcomes

- INVALID_DOCUMENT: 4
- SUCCESS: 223

## Evidence And Assertions

- primary evidence: 504
- primary evidence source FACE_SKETCH: 167
- primary evidence source SONIC_FORECAST: 263
- primary evidence source TSP_REPORT: 74
- report assertions: 122
- assertion BLOCK_FALL_SUMMARY: 45
- assertion GRADE_SUMMARY: 15
- assertion RISK_SUMMARY: 23
- assertion WATER_SUMMARY: 39

## SourceSpan Validation

- total spans: 3768
- bbox spans: 3646
- text block spans: 122
- valid spans: 3768 (1.0)
- invalid spans: 0
- field-span coverage: 6606/6606 (1.0)
- invalid span detail file: source_span_validation.csv

## Freeze Gate Candidates

- in-scope canonical processing coverage: 223/223
- SUCCESS/SUCCESS_WITH_WARNINGS ratio: 1.0
- unsupported ratio: 0.0
- parse error ratio: 0.0
- SourceSpan effective ratio: 1.0
- field-span coverage ratio: 1.0
- header Evidence count: 0
- duplicate Primary Evidence count: 0
- Forecast outside document scope count: 0
- fixed regression pass rate: 10/10
- Gold pass rate: 3/3

## Interpretation

- Successful: pdfplumber table parser produced explicit outcomes for every raw asset and kept unsupported/invalid outcomes separate from Evidence.
- Failed/unsupported: see unsupported_templates.csv and parse_errors.csv; no failed PDF was silently skipped.
- Source document warnings vs parser warnings are separated in warnings.csv and evidence_hard_checks.csv.
- Systemic errors are not declared fixed here; this report only provides the shadow-run evidence needed for manual review and Stage 2 freeze assessment.

## Manual Review

- See manual_review_sample.csv for fixed-seed review selection.
