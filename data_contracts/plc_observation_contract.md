# PLC Observation Contract

标准化结果写入 Parquet，并在旁路 JSON 中记录 `asset_id`、`catalog_version`、`normalization_version`、原始行数、标准化行数和警告数量。

## Required Columns

| Column | Type | Unit status | Missing semantics | Used by |
|---|---|---|---|---|
| observation_id | string | not applicable | must exist | trace reference |
| asset_id | string | not applicable | must exist | source reference |
| source_row_number | integer | not applicable | must exist | raw row trace |
| timestamp | timezone-aware datetime | verified as time | parse failures excluded from algorithms | sorting, gaps, episodes |
| shield_head_chainage | float nullable | unit `m`, unverified | missing means no position anchor | quality, footprint |
| daily_advance | float nullable | unverified | support unavailable | consistency check only |
| cumulative_advance | float nullable | unverified | support unavailable | consistency check only |
| cylinder_displacement | float nullable | unverified | support unavailable | consistency check only |
| excavation_state | string/number nullable | verified as state code/label only | weak rule falls back to signals | phase weak labels |
| advance_speed | float nullable | unverified | weak rule may become UNKNOWN | phase weak labels |
| set_advance_speed | float nullable | unverified | subphase may be VARIABLE | subphase hint |
| total_thrust | float nullable | unverified | weak rule may become UNKNOWN | phase weak labels |
| cutterhead_torque | float nullable | unverified | weak rule may become UNKNOWN | phase weak labels |
| cutterhead_rpm | float nullable | unverified | weak rule may become UNKNOWN | phase weak labels |
| penetration | float nullable | unverified | not used for conclusions | diagnostics/support |
| quality_flags | list[string] | not applicable | empty list means no row flag | trace diagnostics |

## Quality Rules

The quality report covers missing time fields, timestamp parse failures, duplicate timestamps, non-monotonic time, median and P95 sampling interval, large gaps, missing chainage, chainage reverse movement, large chainage jumps, static chainage ratio, core-channel missing rates, configured valid ranges, and unverified units.

Quality grades are explanatory:

- `A`: no material diagnostic reason codes.
- `B`: warnings such as duplicate timestamps, parse failures, large gaps, or minor reverse movement.
- `C`: serious issues such as large chainage jumps or highly missing primary channels.
- `D`: required time or chainage anchors are missing.

## Allowed Uses

The contract may be used for PLC quality diagnosis, transparent weak operation labels, continuous excavation episode construction, and quality-aware spatial footprint estimation.

## Not Allowed Uses

This contract must not be used to infer geological causes, classify planned versus unplanned stoppage, generate daily reports, build fixed 10 m construction facts, or claim precise physical quantities from channels whose units remain unverified.

