# Stage 2 Table Parser V2 Implementation Report

- Scope: final targeted fixes to the existing pdfplumber-backed table parser V2 only.
- pdfplumber version: `0.11.10`.
- Manual Gold samples: Sketch PASS, HSP PASS, TSP PASS.
- TSP Gold ReportAssertion count: 9.
- Non-Gold structural samples: 4 PASS.
- Non-Gold TSP 21-page assertions cover pages: [10, 11].
- First non-Gold TSP Ed value: `88~95`.
- FaceSketch field-span semantic validation: 23/23 non-null fields have field spans.
- Table-cell SourceSpan bbox pass rate: 176/176.
- Zero bbox spans: 0.
- Sketch two-page boundary: checked 18 in-scope two-page Sketch PDFs; no nonblank page-2 Sketch was found. Current support is one-page main table plus blank trailing page. Future nonblank continuation pages return `UNSUPPORTED_TEMPLATE` with `NONBLANK_SKETCH_CONTINUATION_PAGE`.
- Full pipeline migration, Applicability recompute, Gold expansion, and Stage 3 were not run.
