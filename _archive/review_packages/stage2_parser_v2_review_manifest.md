# Stage 2 Parser V2 Review Manifest

Generated at: 2026-07-29T20:07:48

## Git
- current_git_commit_hash: NO_HEAD_COMMIT
- working_tree_dirty: True
- git_status_short:
```text
?? .DS_Store
?? .env.example
?? .gitignore
?? .vscode/
?? AGENTS.md
?? README.md
?? configs/
?? data_contracts/
?? docs/
?? pyproject.toml
?? review_manifest.md
?? review_sample_index.csv
?? review_sample_pdfs/
?? scripts/
?? src/
?? stage2_full_review_577.zip
?? tests/
```

## pdfplumber
- exact_requested_command: `python -c "import pdfplumber; print(pdfplumber.**version**)"`
- exact_requested_command_exit_code: 1
- exact_requested_command_output:
```text
File "<string>", line 1
    import pdfplumber; print(pdfplumber.**version**)
                                        ^^
SyntaxError: invalid syntax
```
- valid_import_check_command: `python -c "import pdfplumber; print(pdfplumber.__version__)"`
- valid_import_check_exit_code: 1
- valid_import_check_output:
```text
Traceback (most recent call last):
  File "<string>", line 1, in <module>
    import pdfplumber; print(pdfplumber.__version__)
    ^^^^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'pdfplumber'
```
- pdfplumber_importable: False
- tests_actually_called_pdfplumber: False
- fallback_branch: `src/tbm_twin/geology/parsers_v2/template_inventory.py::_pdfplumber_table_info` records `PDFPLUMBER_UNAVAILABLE`; executable V2 Gold parsers use `raw_documents.extract_pdf_page_text` / PyMuPDF text layer and SourceSpan text_start/text_end.

## Source And Tests
- v2_source_file_count: 10
- v2_test_file_count: 1

### V2 Source Line Counts
- src/tbm_twin/geology/parsers_v2/__init__.py: 9 lines
- src/tbm_twin/geology/parsers_v2/face_sketch.py: 198 lines
- src/tbm_twin/geology/parsers_v2/hsp.py: 213 lines
- src/tbm_twin/geology/parsers_v2/models.py: 130 lines
- src/tbm_twin/geology/parsers_v2/provenance.py: 66 lines
- src/tbm_twin/geology/parsers_v2/registry.py: 33 lines
- src/tbm_twin/geology/parsers_v2/report_assertions.py: 36 lines
- src/tbm_twin/geology/parsers_v2/table_utils.py: 129 lines
- src/tbm_twin/geology/parsers_v2/template_inventory.py: 137 lines
- src/tbm_twin/geology/parsers_v2/tsp.py: 306 lines

### V2 Test Files
- tests/unit/test_parser_v2_gold.py

### Three Real PDF End-to-End Tests
- test_v2_sketch_gold_from_real_pdf
- test_v2_hsp_gold_from_real_pdf
- test_v2_tsp_gold_from_real_pdf

## Gold And Hardcode Audit
- gold_json_read_by_src_code: False
- gold_json_grep_result: `<NO_MATCH>`
- sample_chainage_hardcode_found: True
- sample_chainage_hardcode_result:
```text
src/tbm_twin/geology/parsers_v2/table_utils.py:    """Convert DyK1013+184.2-like text to absolute chainage metres."""
Binary file src/tbm_twin/geology/parsers_v2/__pycache__/table_utils.cpython-313.pyc matches
Binary file src/tbm_twin/geology/parsers_v2/__pycache__/tsp.cpython-313.pyc matches
src/tbm_twin/geology/parsers_v2/tsp.py:            if "以下结论" in compact(page.page_text) and "DyK1013+080.2" in page.page_text
src/tbm_twin/geology/parsers_v2/tsp.py:        ("DyK1013+080.2～DyK1013+161", "Ⅴ级"),
```
- hardcode_audit_file: artifacts/stage2_parser_v2_design/hardcode_and_gold_dependency_audit.txt

## Template Variants
- 2846040cba6a: source_type=TSP_REPORT, asset_count=2, page_count_values=[20]
- 4bbd88442dcf: source_type=TSP_REPORT, asset_count=2, page_count_values=[21]
- 59c85de9542b: source_type=TSP_REPORT, asset_count=1, page_count_values=[22]
- a760e531b83d: source_type=TSP_REPORT, asset_count=2, page_count_values=[23]
- ca122cf80748: source_type=SONIC_FORECAST, asset_count=47, page_count_values=[12]
- d256ff85f375: source_type=FACE_SKETCH, asset_count=18, page_count_values=[2]
- e0664feb620a: source_type=SONIC_FORECAST, asset_count=2, page_count_values=[13]
- f2306bebe044: source_type=FACE_SKETCH, asset_count=153, page_count_values=[1]

## Sample PDFs
Included under `review_sample_pdfs/`:
- /Users/zhaoxiaoda/Library/CloudStorage/GoogleDrive-xiaodazhao0608@gmail.com/我的云端硬盘/TBM9/SKETCH/DyK1013+184.20_伯舒拉岭进口右线DyK1013+184.2洞身素描记录表.pdf
- /Users/zhaoxiaoda/Library/CloudStorage/GoogleDrive-xiaodazhao0608@gmail.com/我的云端硬盘/TBM9/HSP/DyK1013+190.20_伯舒拉岭隧道进口右线水平声波剖面法超前地质预报报告(DyK1013+190.2～DyK1013+290.2)-20230914.pdf
- /Users/zhaoxiaoda/Library/CloudStorage/GoogleDrive-xiaodazhao0608@gmail.com/我的云端硬盘/TBM9/TSP/DyK1013+124.20_伯舒拉岭隧道进口右线地震波反射法超前地质预报报告(DyK1013+080.2～DyK1013+200.2)-20230603.pdf

## ZIP File List
- artifacts/stage2_parser_v2_design/design_report.md (1213 bytes)
- artifacts/stage2_parser_v2_design/gold_validation_report.md (4093 bytes)
- artifacts/stage2_parser_v2_design/hardcode_and_gold_dependency_audit.txt (1044 bytes)
- artifacts/stage2_parser_v2_design/legacy_assertion_mapping_audit.csv (103666 bytes)
- artifacts/stage2_parser_v2_design/legacy_primary_mapping_audit.csv (1094999 bytes)
- artifacts/stage2_parser_v2_design/template_inventory.csv (221037 bytes)
- artifacts/stage2_parser_v2_design/template_variants.json (8230 bytes)
- artifacts/stage2_parser_v2_design/unclassified_template_audit.csv (7 bytes)
- artifacts/stage2_parser_v2_design/v1_v2_sample_comparison.csv (1159 bytes)
- pyproject.toml (1001 bytes)
- review_sample_pdfs/DyK1013+124.20_伯舒拉岭隧道进口右线地震波反射法超前地质预报报告(DyK1013+080.2～DyK1013+200.2)-20230603.pdf (1778467 bytes)
- review_sample_pdfs/DyK1013+184.20_伯舒拉岭进口右线DyK1013+184.2洞身素描记录表.pdf (389005 bytes)
- review_sample_pdfs/DyK1013+190.20_伯舒拉岭隧道进口右线水平声波剖面法超前地质预报报告(DyK1013+190.2～DyK1013+290.2)-20230914.pdf (1166065 bytes)
- scripts/stage2_parser_v2_design.py (8489 bytes)
- src/tbm_twin/evidence/models.py (13420 bytes)
- src/tbm_twin/geology/chainage.py (6609 bytes)
- src/tbm_twin/geology/document_models.py (2993 bytes)
- src/tbm_twin/geology/parsers_v2/__init__.py (314 bytes)
- src/tbm_twin/geology/parsers_v2/face_sketch.py (7587 bytes)
- src/tbm_twin/geology/parsers_v2/hsp.py (7741 bytes)
- src/tbm_twin/geology/parsers_v2/models.py (3321 bytes)
- src/tbm_twin/geology/parsers_v2/provenance.py (1823 bytes)
- src/tbm_twin/geology/parsers_v2/registry.py (1239 bytes)
- src/tbm_twin/geology/parsers_v2/report_assertions.py (1056 bytes)
- src/tbm_twin/geology/parsers_v2/table_utils.py (3553 bytes)
- src/tbm_twin/geology/parsers_v2/template_inventory.py (5047 bytes)
- src/tbm_twin/geology/parsers_v2/tsp.py (11507 bytes)
- src/tbm_twin/geology/raw_documents.py (4465 bytes)
- src/tbm_twin/geology/time_semantics.py (1229 bytes)
- stage2_parser_v2_review_manifest.md (7057 bytes)
- tbm-report/_archive/old_frontend/package-lock.json (186387 bytes)
- tbm-report/frontend/package-lock.json (72316 bytes)
- tests/gold/geology/hsp_dyk1013_190_2.json (17651 bytes)
- tests/gold/geology/sketch_dyk1013_184_2.json (18799 bytes)
- tests/gold/geology/tsp_dyk1013_080_2.json (70326 bytes)
- tests/unit/test_parser_v2_gold.py (5354 bytes)
