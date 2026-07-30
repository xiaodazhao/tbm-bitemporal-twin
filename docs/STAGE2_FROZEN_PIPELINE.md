# Stage 2 Frozen Pipeline

This repository has one formal post-Stage-2 route:

```text
Stage 2 Geology V2 Freeze
-> Applicability V2
-> Stage 3 ConstructionStateVersion
```

Stage 3 must read from the two frozen output directories below. It must not
rerun PDF parsing, use legacy raw validation outputs, or reinterpret frozen
evidence.

## Formal Inputs

The formal Stage 2 geology input is:

```text
artifacts/stage2_geology_v2_freeze_candidate/
```

Protected freeze counts:

- Documents: 223
- Primary Evidence: 659
- ReportAssertion: 122
- Unlocated Clause: 496
- SourceSpan: 4713

Key files:

- `geological_documents.jsonl`
- `primary_geological_evidence.jsonl`
- `report_assertions.jsonl`
- `source_spans.jsonl`
- `unlocated_clauses.jsonl`
- `freeze_manifest.json`
- `method_version.json`
- `parser_source_snapshot.tar.gz`
- `file_hashes.sha256`

## Formal Parser

The only formal PDF parser source is:

```text
src/tbm_twin/geology/table_parser_v2/
```

The previous text-regex prototype `src/tbm_twin/geology/parsers_v2/` has been
archived and must not be reconnected to the formal route.

## Formal Applicability

The formal Applicability V2 output is:

```text
artifacts/stage2d_applicability_v2/
```

Protected applicability counts:

- PLC dates: 91
- Primary EvidenceApplicabilityAssignment rows: 59,969

Key files:

- `evidence_applicability_assignments.jsonl`
- `assertion_applicability_assignments.jsonl`
- `clause_applicability_assignments.jsonl`
- `applicability_daily_summary.csv`
- `applicability_evidence_summary.csv`
- `forecast_role_transition_audit.csv`
- `applicability_report.md`
- `method_version.json`
- `file_hashes.sha256`

## Archived Legacy Material

Legacy Stage 2 development outputs and prototype code are under:

```text
_archive/
```

See [ARCHIVE_INDEX.md](ARCHIVE_INDEX.md) for the complete index.

Archived material includes:

- prototype text parser
- parser-generated Gold snapshots
- Stage 2 design and review packages
- raw geology validation artifacts
- table parser shadow artifacts
- old review ZIP packages
- the local old repository copy

## Do Not Use

Do not use these as formal Stage 3 inputs:

- `evidence_db.csv`
- old 484-row evidence exports
- old 653-row or 824-row parser outputs
- `tests/gold/`
- `artifacts/stage2_raw_geology_validation/`
- `artifacts/stage2_table_parser_v2_shadow/`
- `_archive/**` except for explicit audit comparison

## Stage 3 Boundary

Stage 3 may read:

```text
artifacts/stage2_geology_v2_freeze_candidate/
artifacts/stage2d_applicability_v2/
```

Stage 3 must not modify either directory.

## Hash Verification

Each protected directory contains `file_hashes.sha256`.

Example:

```bash
cd /path/to/tbm-bitemporal-twin
shasum -a 256 -c artifacts/stage2_geology_v2_freeze_candidate/file_hashes.sha256
shasum -a 256 -c artifacts/stage2d_applicability_v2/file_hashes.sha256
```

The cleanup audit also records protected pre/post hashes in:

```text
artifacts/repository_cleanup_stage2/protected_hash_audit.csv
```

## Formal Tests

Run:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest -q
```
