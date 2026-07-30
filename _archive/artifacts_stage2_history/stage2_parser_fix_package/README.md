# Stage 2 Parser Fix Package

This package summarizes the Stage 2 parser-focused repair round.

Scope:
- Gold and Stage 3 stayed paused.
- No LLM extraction was introduced.
- No old repository was modified.
- Existing SourceAsset, page text, timezone, available_time_extent, line scope, SHA dedup, warning isolation, and Applicability interfaces were preserved.

Main code areas changed:
- `src/tbm_twin/geology/document_parsers.py`
- `src/tbm_twin/geology/chainage.py`
- `scripts/validate_stage2_raw_geology.py`
- `tests/unit/test_raw_geology_documents.py`
- `tests/unit/test_raw_geology_semantic_regressions.py`

Validation commands run:
- `python -m ruff check .`
- `python -m ruff format --check .`
- `python -m mypy src`
- `python -m pytest -q`
- `python scripts/validate_stage2_raw_geology.py --tsp-dir ... --hsp-dir ... --sketch-dir ... --legacy-evidence-db ... --stage1-artifact-dir artifacts/stage1_validation --dates 2023-12-30,2023-12-28,2023-09-15 --output-dir artifacts/stage2_raw_geology_validation`

Validation result:
- Ruff check: passed
- Ruff format check: passed
- Mypy: passed
- Pytest: 94 passed
- Full raw geology validation: regenerated

Key full-data metrics:
- Raw assets: 227
- In-scope assets: 225
- Duplicate assets: 2
- Out-of-scope assets: 2
- Canonical documents: 223
- Canonical evidence: 577
- Evidence distribution: OBSERVED 297, FORECAST 217, BACKGROUND 63
- Non-evidence sections excluded: 566
- Forecast range source distribution: TABLE_ROW_RANGE 189, SELF_RANGE 23, LEGAL_DOCUMENT_SCOPE_INHERITANCE 5
- Forecast without explicit or legal inherited range: 0
- Table row reconstruction evidence: 189
- Exact duplicate evidence: 0
- Face observation coverage: 167/167
- Temporal local date consistency: 669/669
- Forecast face_chainage validation: 56/56 WITHIN_FORECAST_SCOPE
- Future leakage check: 0

Included files:
- `stage2_raw_geology_validation_report.md`
- `raw_geology_validation_summary.json`
- `audit_csv/non_evidence_section_audit.csv`
- `audit_csv/table_row_reconstruction_audit.csv`
- `audit_csv/unresolved_table_cell_audit.csv`
- `audit_csv/duplicate_evidence_audit.csv`
- `audit_csv/chainage_prefix_review_audit.csv`
- `audit_csv/forecast_face_chainage_audit.csv`
- `audit_csv/structured_attribute_coverage.csv`
- `audit_csv/applicability_result_matrix.csv`

The authoritative complete artifact directory remains:
- `artifacts/stage2_raw_geology_validation`
