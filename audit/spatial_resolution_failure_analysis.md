# Spatial Resolution Failure Analysis

## Deterministic conclusion

The 20 m arm crosses the method's support-semantic validity boundary. This is not
a numerical instability in RAI/GRS/GRCI. A coarse cell can intersect a 10 m-aligned
daily review region and an adjacent forward or local-background region on the same
date, while the state model requires one role per cell. Retaining one role necessarily
drops or misallocates some point/interval support, producing the observed secondary
coverage failures.

- Role-conflict rows: **90**
- Unique problematic 20 m cells: **57**
- Date-cell instances containing multiple role-support regions: **90**
- Point missing/duplicate: **23**
- Interval overlap mismatch: **76**
- 5 m role conflicts: **0**
- 10 m role conflicts: **0**

## Conflict patterns

- `DAILY_REVIEW_CELL -> FORWARD_ATTENTION_CELL`: 41
- `DAILY_REVIEW_CELL -> LOCAL_BACKGROUND_CELL`: 49

## Real examples

### Example 1: 2023-09-15 / cell_da32263c3a02dac7ce6611e3

- Cell range: `1013180.0-1013200.0`
- Existing role: `DAILY_REVIEW_CELL`
- Conflicting role: `LOCAL_BACKGROUND_CELL`
- Triggering scope: `local_background_scope`
- Daily review scope: `{"basis": "trusted_ten_meter_aligned_daily_review_scope", "end_chainage": 1013200.0, "kind": "INTERVAL", "start_chainage": 1013190.0}`
- Forward scope: `{"basis": "trusted_forward_attention_scope", "end_chainage": 1013230.0, "kind": "INTERVAL", "start_chainage": 1013200.0}`
- Local background scope: `{"basis": "trusted_local_background_scope", "end_chainage": 1013190.0, "kind": "INTERVAL", "start_chainage": 1013090.0}`

### Example 2: 2023-09-17 / cell_d1e83d27a7e98099969cd28d

- Cell range: `1013200.0-1013220.0`
- Existing role: `DAILY_REVIEW_CELL`
- Conflicting role: `LOCAL_BACKGROUND_CELL`
- Triggering scope: `local_background_scope`
- Daily review scope: `{"basis": "trusted_ten_meter_aligned_daily_review_scope", "end_chainage": 1013220.0, "kind": "INTERVAL", "start_chainage": 1013210.0}`
- Forward scope: `{"basis": "trusted_forward_attention_scope", "end_chainage": 1013250.0, "kind": "INTERVAL", "start_chainage": 1013220.0}`
- Local background scope: `{"basis": "trusted_local_background_scope", "end_chainage": 1013210.0, "kind": "INTERVAL", "start_chainage": 1013110.0}`

### Example 3: 2023-09-18 / cell_d1e83d27a7e98099969cd28d

- Cell range: `1013200.0-1013220.0`
- Existing role: `DAILY_REVIEW_CELL`
- Conflicting role: `LOCAL_BACKGROUND_CELL`
- Triggering scope: `local_background_scope`
- Daily review scope: `{"basis": "trusted_ten_meter_aligned_daily_review_scope", "end_chainage": 1013220.0, "kind": "INTERVAL", "start_chainage": 1013210.0}`
- Forward scope: `{"basis": "trusted_forward_attention_scope", "end_chainage": 1013250.0, "kind": "INTERVAL", "start_chainage": 1013220.0}`
- Local background scope: `{"basis": "trusted_local_background_scope", "end_chainage": 1013210.0, "kind": "INTERVAL", "start_chainage": 1013110.0}`

### Example 4: 2023-09-19 / cell_7fbae1f859778928bcd57c1a

- Cell range: `1013220.0-1013240.0`
- Existing role: `DAILY_REVIEW_CELL`
- Conflicting role: `FORWARD_ATTENTION_CELL`
- Triggering scope: `forward_scope`
- Daily review scope: `{"basis": "trusted_ten_meter_aligned_daily_review_scope", "end_chainage": 1013230.0, "kind": "INTERVAL", "start_chainage": 1013210.0}`
- Forward scope: `{"basis": "trusted_forward_attention_scope", "end_chainage": 1013260.0, "kind": "INTERVAL", "start_chainage": 1013230.0}`
- Local background scope: `{"basis": "trusted_local_background_scope", "end_chainage": 1013210.0, "kind": "INTERVAL", "start_chainage": 1013110.0}`

### Example 5: 2023-09-19 / cell_d1e83d27a7e98099969cd28d

- Cell range: `1013200.0-1013220.0`
- Existing role: `DAILY_REVIEW_CELL`
- Conflicting role: `LOCAL_BACKGROUND_CELL`
- Triggering scope: `local_background_scope`
- Daily review scope: `{"basis": "trusted_ten_meter_aligned_daily_review_scope", "end_chainage": 1013230.0, "kind": "INTERVAL", "start_chainage": 1013210.0}`
- Forward scope: `{"basis": "trusted_forward_attention_scope", "end_chainage": 1013260.0, "kind": "INTERVAL", "start_chainage": 1013230.0}`
- Local background scope: `{"basis": "trusted_local_background_scope", "end_chainage": 1013210.0, "kind": "INTERVAL", "start_chainage": 1013110.0}`

## Why 5 m and 10 m pass

The 10 m baseline shares the native review-boundary alignment. The 5 m grid refines
those boundaries, so a native 10 m role region can be represented by two cells without
mixing adjacent roles. A 20 m cell aggregates across those boundaries and cannot preserve
the one-cell/one-role support contract.

Therefore 20 m is an intentionally retained coarse-resolution stress test and not a valid
alternative estimator for headline comparison.
