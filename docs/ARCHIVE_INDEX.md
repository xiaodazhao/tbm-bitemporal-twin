# Archive Index

## 2026-09-07 repository consolidation

The active repository now keeps one canonical research route. Superseded
candidates, earlier corrected result directories, and review transport ZIPs
were moved outside the worktree to:

```text
/Users/zhaoxiaoda/Desktop/tbm-bitemporal-twin_local_archive_20260907/
```

The archive contains `archive_manifest.csv`. The former repository-level
`_archive/` was also moved to
`repository_root_archive/_archive/`; therefore none of the Stage 2 legacy
implementation, parser snapshots, or review packages remains in the active
GitHub tree. The pre-cleanup repository state is also preserved locally by
branch `codex/pre-cleanup-20260907` at commit
`a0f756a37ac87b347e8fe767424aa891d26a1c40`.

This external archive is a recovery location, not a formal pipeline input and
not part of the GitHub publication tree. The authoritative active paths are
listed in `docs/CANONICAL_RESEARCH_PATH.md`.

The sections below describe paths inside the externally archived `_archive/`,
not directories that remain in the formal project root.

## `_archive/stage2_legacy/prototype_text_parser/`

Original path:

```text
src/tbm_twin/geology/parsers_v2/
tests/unit/test_parser_v2_gold.py
```

Reason:

The prototype text parser used text regexes and sample-oriented assumptions. It
was superseded by the pdfplumber-backed `table_parser_v2`. It must not be
reconnected to the formal route.

Deletion status:

Retain for audit unless a later repository compaction explicitly removes Stage
2 history.

## `_archive/stage2_legacy/one_off_scripts/`

Original paths include:

```text
scripts/stage2_parser_v2_design.py
scripts/run_stage2_table_parser_v2_shadow.py
scripts/run_face_sketch_v2_fixed_audit.py
scripts/build_stage2_geology_v2_freeze_candidate.py
scripts/finalize_stage2_geology_v2_freeze_candidate.py
```

Reason:

These scripts were used during parser design, shadow running, and freeze
candidate assembly. Their outputs are now frozen under protected artifacts.

Deletion status:

Retain for reproducibility and audit.

## `_archive/stage2_legacy/parser_output_snapshots/`

Original paths:

```text
tests/gold/
artifacts/parser_output_snapshots/
```

Reason:

These are parser-generated snapshots, not manual Gold. Formal parser tests use
`tests/manual_gold/geology/`.

Deletion status:

Retain for audit.

## `_archive/artifacts_stage2_history/`

Original paths include:

```text
artifacts/legacy_reference/
artifacts/stage21_validation/
artifacts/stage2_validation/
artifacts/stage2_parser_fix_package/
artifacts/stage2_parser_v2_design/
artifacts/stage2_table_parser_v2_review/
artifacts/stage2_table_parser_v2_shadow/
artifacts/stage2_raw_geology_validation/
```

Reason:

These are historical Stage 2 development, validation, comparison, and shadow
artifacts. Formal Stage 3 input is limited to the formal Stage 2 directories
listed in `docs/STAGE2_FROZEN_PIPELINE.md`.

Deletion status:

Retain for audit and comparison.

## `_archive/review_packages/`

Original paths include:

```text
stage2_full_review_577.zip
stage2_parser_v2_full_review.zip
stage2_shadow_core_review.zip
stage2_table_parser_v2_full_review.zip
review_manifest.md
review_sample_index.csv
review_sample_pdfs/
```

Reason:

Manual review packages are useful historical evidence but are not runtime
inputs.

Deletion status:

Retain unless external review retention is no longer required.

## `_archive/stage2_legacy/old_repository/`

Original path:

```text
tbm-report/
```

Reason:

This is the old repository copy retained as historical reference only. It is not
part of the formal route.

Deletion status:

Retain until the user confirms old-repository retention is no longer needed.
