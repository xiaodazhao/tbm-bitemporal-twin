# Spatial Semantics Lineage

## Authoritative path

`raw PLC shield-head chainage` -> `core EXCAVATING observations` ->
`ExcavationEpisode trusted SpatialFootprint` -> `cell overlap/reference link` ->
`Claim authoritative support` -> `FactLock contained scope` -> `controlled realization`.

## Field contract

| Formal field | True source | Cell aligned | May be called actual excavation? | Permitted use | Forbidden inference |
|---|---|---:|---:|---|---|
| `ExcavationEpisode.excavation_start/end` | Core EXCAVATING intervals | No | Time only | Event temporal boundary | Spatial advance |
| `SpatialFootprint.trusted_spatial_scope` | Core shield-head chainage | No | Yes, only as event-supported footprint | Mechanical evidence location | Geological cause |
| `raw_daily_plc_range` | Raw daily shield-head range | No | Raw measured range, with quality caveat | Audit/diagnosis | Trusted advance when regime invalid |
| `trusted_daily_plc_range` | Trusted daily chainage regime | No | Yes, as trusted measured day range | Day-level measured span | Cell coverage |
| `daily_excavated_scope` | Ten-metre alignment of trusted range | **Yes** | **No** | Daily review cell selection | Actual daily advance or measured range |
| `ConstructionStateCell` | Fixed alignment/grid/index | Yes | No | Knowledge-state spatial index | Construction fact |
| `forward_scope` | Applicability rule ahead of review scope | Yes | No | Forecast attention organization | Already excavated fact |
| `local_background_scope` | Applicability rule behind review scope | Yes | No | Context organization | Current measured advance |
| Claim spatial scope | Frozen subject/support intersection | Sometimes | Only if claim type and support authorize it | Claim subject | Expansion beyond support |
| FactLock spatial scope | Resolved authoritative support | Inherited | Only with matching fact semantics | Controlled realization | Any support expansion |

## Concrete distinction

On `2023-09-15`, the trusted PLC range is `1013197.0-1013198.0`
(1.000 m), while the field named `daily_excavated_scope` is
`1013190.0-1013200.0` (10.000 m) with basis
`trusted_ten_meter_aligned_daily_review_scope`.  The latter is a cell-aligned review
scope and must not be reported as actual daily advance.

## Enforcement evidence

- `src/tbm_twin/state/builder.py`: measured span fields are computed from raw/trusted PLC
  ranges; the aligned scope is used for cell-role assignment.
- `src/tbm_twin/state/builder.py`: multicell response links carry
  `response_stat_scope=EPISODE_LEVEL_SHARED`.
- `configs/claim_contract_v1.yaml` and Stage5A validation: claim scope must be contained
  by resolved support.
- `artifacts/stage6a_fact_lock_evidence_pack_v1/fact_locks.jsonl`: locked support and
  prohibited spatial expansion are persisted.

## Paper wording rule

Translate `daily_excavated_scope` as **cell-aligned daily review scope**, despite its
legacy internal field name. Use **trusted daily PLC range** for actual measured daily
range, and **event footprint** for episode-supported mechanical location.
