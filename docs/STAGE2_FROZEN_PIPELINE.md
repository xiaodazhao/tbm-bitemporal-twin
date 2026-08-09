# Stage 2 Frozen Pipeline

This repository has one formal post-Stage-2 route:

```text
Stage 2 Geology V2 Freeze
+ Applicability V2.1
+ PLC Operational Evidence Freeze V2
-> Stage 3A Initial Construction State v1.1
-> Stage 3B Bitemporal Epistemic State v1.1
-> Stage 4 Bitemporal State Metrics v1.1
```

Stage 3 must read from the three frozen output directories below. It must not
rerun PDF parsing, rebuild PLC operational evidence, use legacy raw validation
outputs, or reinterpret frozen evidence.

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

The formal Applicability V2.1 output is:

```text
artifacts/stage2d_applicability_v2_1/
```

Protected applicability counts:

- PLC dates: 91
- Primary EvidenceApplicabilityAssignment rows: 59,969
- Assertion assignment rows: 11,102
- Clause assignment rows: 45,136
- Role counts: DAILY_REVIEW 285, FORWARD_ATTENTION 138, LOCAL_BACKGROUND 1052, NOT_APPLICABLE 58494
- Role changes vs Applicability V2: 32
- Temporal future leakage: 0
- Spatial regime leakage: 0

Key files:

- `evidence_applicability_assignments.jsonl`
- `assertion_applicability_assignments.jsonl`
- `clause_applicability_assignments.jsonl`
- `applicability_daily_summary.csv`
- `applicability_evidence_summary.csv`
- `forecast_role_transition_audit.csv`
- `applicability_v2_1_report.md`
- `applicability_v2_v2_1_semantic_difference.csv`
- `applicability_v2_v2_1_difference_summary.json`
- `method_version.json`
- `file_hashes.sha256`

## Formal PLC Operational Evidence

The formal PLC operational evidence freeze V2 output is:

```text
artifacts/stage2_plc_operational_freeze_v2/
```

Key files:

- `source_assets.jsonl`
- `normalized_observation_manifest.csv`
- `phase_intervals.jsonl`
- `excavation_episodes.jsonl`
- `spatial_footprints.jsonl`
- `response_evidence.jsonl`
- `plc_daily_scope_reference.jsonl`
- `plc_daily_scope_v2.jsonl`
- `chainage_regime_observation_audit.csv`
- `chainage_regime_episode_audit.csv`
- `chainage_regime_daily_audit.csv`
- `plc_applicability_scope_consistency_audit.csv`
- `freeze_manifest.json`
- `method_version.json`
- `stage2e_source_snapshot.tar.gz`
- `file_hashes.sha256`

Operational semantics:

- Episodes are `PLC_INFERRED`, not verified construction rings or manual logs.
- `shield_head_chainage` is the primary spatial anchor.
- ResponseEvidence is mechanical/operational evidence, not geological cause.
- `baseline_mode = NO_BASELINE` in Stage 2E.
- `reconstructed_at` is offline freeze time and must not be used as historical
  transaction or ingestion time.
- Raw PLC ranges are preserved for trace audit only. Stage 3 must use trusted
  spatial scope from `plc_daily_scope_v2.jsonl` and ResponseEvidence records.
- RESTORED chainage regime means trusted trajectory was re-established after an
  earlier anomaly; it does not mean those Episodes are themselves unusable.

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

The old `artifacts/stage2d_applicability_v2/` output used raw PLC min/max space.
It is retained only for audit comparison and must not be used as Stage 3 input.

The old `artifacts/stage2_plc_operational_freeze/` output predates chainage
regime governance. It is retained only for audit comparison and must not be used
as Stage 3 input.

## Stage 3 Boundary

Stage 3A may read:

```text
artifacts/stage2_geology_v2_freeze_candidate/
artifacts/stage2d_applicability_v2_1/
artifacts/stage2_plc_operational_freeze_v2/
```

Stage 3A must not modify these directories.

The formal Stage3A v1.1 output is:

```text
artifacts/stage3a_initial_epistemic_state_v1_1/
```

Stage3B must read only this formal Stage3A directory. 禁止Stage3B读取
`artifacts/stage3a_initial_epistemic_state_v1/`; it is
`SUPERSEDED_BY_STAGE3A_V1_1` and `POINT_RESPONSE_INCOMPLETE`. 禁止Stage3B读取
`artifacts/stage3a_initial_epistemic_state_v1_1_candidate/`; it is retained only
as promotion-audit input.

The formal Stage3B v1.1 output is:

```text
artifacts/stage3b_bitemporal_epistemic_state_v1_1/
```

Post-Stage3B metrics and Claim layers must read only this formal Stage3B
directory. Do not read
`artifacts/stage3b_bitemporal_epistemic_state_v1_candidate/`; it is retained
only as promotion-audit input.

## Formal Stage4 Metrics

The formal Stage4 metric output is:

```text
artifacts/stage4_bitemporal_state_metrics_v1_1/
```

Protected semantics:

- RAI uses LOAD_RESPONSE and ADVANCE_KINEMATIC_RESPONSE only.
- RPM is diagnostic trace only and is excluded from scalar RAI.
- GRS uses six frozen geological attention dimensions.
- Missing GRS dimensions are excluded from the denominator, not filled with 0.
- GRCI is defined only for DAILY_REVIEW_CELL when both RAI and GRS are available.
- GRCI uses `NONPROBABILISTIC_CONJUNCTIVE_PRODUCT`.
- RAI, GRS and GRCI are not risk probabilities or causal estimates.

Stage5 must read only this formal Stage4 directory. Stage4 candidate and method
review directories may be retained for audit history, but they are not formal
runtime inputs for later stages.

## Hash Verification

Each protected directory contains `file_hashes.sha256`.

Example:

```bash
cd /path/to/tbm-bitemporal-twin
shasum -a 256 -c artifacts/stage2_geology_v2_freeze_candidate/file_hashes.sha256
shasum -a 256 -c artifacts/stage2d_applicability_v2_1/file_hashes.sha256
shasum -a 256 -c artifacts/stage2_plc_operational_freeze_v2/file_hashes.sha256
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
