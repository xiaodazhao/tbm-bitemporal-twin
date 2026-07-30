# Geological Evidence

`GeologicalEvidence` 从CSV或JSON记录规则化生成，不使用LLM抽取事实。输入字段通过 `configs/geology_sources.yaml` 的别名表映射，文本中仅用正则和关键词生成可审计的结构化属性。

时间语义分为 `observed_time`、`issued_time` 和 `available_time`。`available_time` 是适用性判断使用的证据可用时间；缺失时保持 `UNKNOWN`，不得用入库时间或Episode时间回填。

空间语义使用 `ChainageInterval`，保留原始起止里程、原始方向和归一化后的起止里程。若原始方向递减，会记录归一化原因，而不是丢弃方向信息。

认识性质显式区分 `FORECAST`、`OBSERVED`、`BACKGROUND` 和 `UNKNOWN`。预报资料不会因为后续空间重叠而变成现场观测；UNKNOWN也不会被悄悄并入背景资料。

Stage 2.1 使用显式映射表：

- `TSP_REPORT`、`HSP_REPORT`、`SONIC_FORECAST` -> `FORECAST`
- `FACE_SKETCH`、`FIELD_OBSERVATION`、`EXCAVATED_FACE_RECORD` -> `OBSERVED`
- `DESIGN_GEOLOGY`、`REGIONAL_GEOLOGY`、`DESIGN_BACKGROUND` -> `BACKGROUND`
- 无法识别 -> `UNKNOWN`

如果原始 `source_type` 与标题或明确来源提示冲突，会记录 `EPISTEMIC_SOURCE_CONFLICT` 并降低质量；必要时认识性质设为 `UNKNOWN`。

里程解析保留原始起止值和归一化值。若检测到 `IMPLAUSIBLE_INTERVAL_LENGTH`、`CHAINAGE_SCALE_MISMATCH`、`CHAINAGE_PREFIX_MISMATCH`、`CHAINAGE_PARSE_CONFLICT` 或 `CHAINAGE_DIRECTION_CONFLICT`，则 `spatial_scope_usable=false`。系统可以输出 `suggested_normalization` 作为复核建议，但不会自动补桩号前缀或把建议值当成真实空间范围。
