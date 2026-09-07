# GRS Frozen Mapping Registry

- Frozen entries: **44**
- Numeric entries: **36**
- Reviewed-unmappable entries: **8**
- Entries observed in frozen geology: **44**
- Additional raw-evidence values in configured source fields but absent from mapping: **11**
- Unmapped values that actually enter frozen snapshot scoring: **0**
- Engineering rationale: **RATIONALE_NOT_RECORDED** for every entry. The repository
  records ordering labels (`mapping_basis`), not a per-value engineering justification.

| Source field | Value | Dimension | Rank | Attention | Evidence occurrences | Snapshot uses |
|---|---|---|---:|---:|---:|---:|
| anomaly_level | NONE | EXPLICIT_ANOMALY | 0 | 0.0 | 421 | 1767 |
| anomaly_level | LOW | EXPLICIT_ANOMALY | 1 | 0.3333333333333333 | 21 | 203 |
| anomaly_level | MODERATE | EXPLICIT_ANOMALY | 2 | 0.6666666666666666 | 39 | 548 |
| anomaly_level | HIGH | EXPLICIT_ANOMALY | 3 | 1.0 | 49 | 54 |
| anomaly_level | UNKNOWN | EXPLICIT_ANOMALY | None | None | 6 | 24 |
| suggested_grade | III级 | SURROUNDING_ROCK_GRADE | 1 | 0.3333333333333333 | 25 | 178 |
| suggested_grade | IV级 | SURROUNDING_ROCK_GRADE | 2 | 0.6666666666666666 | 176 | 1396 |
| suggested_grade | V级 | SURROUNDING_ROCK_GRADE | 3 | 1.0 | 74 | 285 |
| suggested_surrounding_rock_grade | III级 | SURROUNDING_ROCK_GRADE | 1 | 0.3333333333333333 | 28 | 70 |
| suggested_surrounding_rock_grade | IV级 | SURROUNDING_ROCK_GRADE | 2 | 0.6666666666666666 | 114 | 317 |
| suggested_surrounding_rock_grade | V级 | SURROUNDING_ROCK_GRADE | 3 | 1.0 | 25 | 24 |
| rock_mass_state | 岩体较破碎 | ROCK_MASS_INTEGRITY | 1 | 0.25 | 202 | 326 |
| rock_mass_state | 岩体较破碎-破碎 | ROCK_MASS_INTEGRITY | 2 | 0.5 | 45 | 112 |
| rock_mass_state | 岩体破碎 | ROCK_MASS_INTEGRITY | 3 | 0.75 | 224 | 1628 |
| rock_mass_state | 岩体破碎-极破碎 | ROCK_MASS_INTEGRITY | 4 | 1.0 | 54 | 556 |
| rock_mass_state | null | ROCK_MASS_INTEGRITY | None | None | 107 | 171 |
| joint_development | 节理裂隙较发育 | JOINT_DEVELOPMENT | 1 | 0.25 | 128 | 417 |
| joint_development | 节理裂隙较发育-发育 | JOINT_DEVELOPMENT | 2 | 0.5 | 32 | 112 |
| joint_development | 节理裂隙发育 | JOINT_DEVELOPMENT | 3 | 0.75 | 181 | 1215 |
| joint_development | 节理裂隙发育密集 | JOINT_DEVELOPMENT | 4 | 1.0 | 71 | 751 |
| joint_development | null | JOINT_DEVELOPMENT | None | None | 156 | 171 |
| block_fall_or_collapse | 轻微掉块 | STABILITY_BLOCK | 1 | 0.5 | 32 | 165 |
| block_fall_or_collapse | 掉块 | STABILITY_BLOCK | 2 | 1.0 | 58 | 430 |
| block_fall_or_collapse | null | STABILITY_BLOCK | None | None | 249 | 282 |
| stability | 自稳性较差 | STABILITY_BLOCK | 2 | 1.0 | 29 | 187 |
| stability | null | STABILITY_BLOCK | None | None | 275 | 620 |
| form_water_status | <10湿润 | WATER_ATTENTION | 1 | 0.2 | 4 | 2 |
| form_water_status | 10~25偶有渗水 | WATER_ATTENTION | 2 | 0.4 | 19 | 126 |
| form_water_status | 25~125涌出或喷出 | WATER_ATTENTION | 5 | 1.0 | 26 | 149 |
| form_water_status | 其它500 | WATER_ATTENTION | None | None | 15 | 91 |
| form_water_status | 其它2000 | WATER_ATTENTION | None | None | 4 | 43 |
| water_type | 湿润 | WATER_ATTENTION | 1 | 0.2 | 3 | 7 |
| water_type | <10湿润 | WATER_ATTENTION | 1 | 0.2 | 4 | 2 |
| water_type | 滴渗水 | WATER_ATTENTION | 2 | 0.4 | 34 | 399 |
| water_type | 渗滴水 | WATER_ATTENTION | 2 | 0.4 | 10 | 58 |
| water_type | 10~25偶有渗水 | WATER_ATTENTION | 2 | 0.4 | 3 | 10 |
| water_type | 线状出水 | WATER_ATTENTION | 3 | 0.6 | 82 | 38 |
| water_type | 滴渗水;线状出水 | WATER_ATTENTION | 3 | 0.6 | 16 | 89 |
| water_type | 渗滴水;线状出水 | WATER_ATTENTION | 3 | 0.6 | 2 | 5 |
| water_type | 滴渗水;滴渗水-线状出水;线状出水 | WATER_ATTENTION | 3 | 0.6 | 6 | 36 |
| water_type | 线-股状出水 | WATER_ATTENTION | 4 | 0.8 | 13 | 31 |
| water_type | 股状出水 | WATER_ATTENTION | 5 | 1.0 | 10 | 3 |
| water_type | 线-股状出水;股状出水 | WATER_ATTENTION | 5 | 1.0 | 8 | 43 |
| water_type | null | WATER_ATTENTION | None | None | 96 | 156 |

## Values outside the 44-entry frozen registry

These values occur in raw Evidence in one of the configured source fields, but are
not scoring entries. None enters the role-selected frozen GRS snapshot inputs; this
audit does not add mappings.

| Source field | Value | Occurrences | Obs | Forecast | Snapshot uses |
|---|---|---:|---:|---:|---:|
| block_fall_or_collapse | 掉块风险 | 32 | 0 | 32 | 0 |
| form_water_status | 25~125经常渗水 | 52 | 52 | 0 | 0 |
| form_water_status | null | 46 | 46 | 0 | 0 |
| form_water_status | 其它; | 1 | 1 | 0 | 0 |
| joint_development | 节理发育 | 12 | 0 | 12 | 0 |
| joint_development | 节理裂隙极发育 | 5 | 0 | 5 | 0 |
| rock_mass_state | 岩体极破碎 | 2 | 0 | 2 | 0 |
| suggested_grade | null | 6 | 0 | 6 | 0 |
| water_type | 25~125经常渗水 | 47 | 47 | 0 | 0 |
| water_type | 其它; | 1 | 1 | 0 | 0 |
| water_type | 滴渗水-线状出水 | 15 | 0 | 15 | 0 |
