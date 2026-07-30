# Stage 2 Geological Parser V2 Design Report

## Current Facts
- V1 parser file: src/tbm_twin/geology/document_parsers.py, 2219 lines at audit time.
- Current GeologicalEvidence model is unchanged; Parser V2 uses parallel models.
- Old repository parsers were read only from /Users/zhaoxiaoda/tbm-report/backend/parsers.
- Legacy evidence_db rows: 484.
- Legacy sketch point: 169.
- Legacy sonic segment: 176, from 44 reports, per-report count 2-6, not fixed at 4.
- Legacy TSP segment: 67.
- Legacy TSP report_conclusion: 71.
- Legacy TSP overview: 1.
- Legacy report_date equals issue_date: 484/484.

## V2 Boundary
- V2 is parallel under src/tbm_twin/geology/parsers_v2 and is not wired into the full Stage 2 pipeline.
- Main Evidence types are FACE_OBSERVATION, FORECAST_SEGMENT, and DESIGN_BACKGROUND.
- TSP chapter 7 summaries are ReportAssertion records and do not enter EvidenceApplicabilityAssignment.
- pdfplumber is declared as a project dependency; this runtime lacked it, so inventory records PDFPLUMBER_UNAVAILABLE and the three executable Gold parses use the PyMuPDF text layer with explicit SourceSpan text positions.

## Template Inventory
- inventoried_pdf_count: 227
- template_variant_count: 8