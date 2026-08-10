# Architecture

## Episode as the Primary Object

TBM施工状态首先表现为连续推进事件，而不是某一天或某个固定空间格。`ExcavationEpisode` 把时间连续性、弱工况标签、来源观测和质量标记绑定在一起，形成后续状态版本和Claim推理可以引用的事实对象。

## Dates Are Query Conditions

日期会用于筛选、汇总和展示，但不是施工事实对象。一个Episode可能跨午夜，也可能同一天包含多个Episode。把日期作为主对象会丢失长停机、数据缺口、跨日推进等过程结构。

## Quality-Aware SpatialFootprint

当前阶段只有PLC侧的盾首里程及若干未确认单位的支持信号，因此 `SpatialFootprint` 只能称为 quality-aware spatial footprint estimation。它使用首尾有效盾首里程估计范围，并用 daily/cumulative/cylinder signals 做一致性检查；遇到严重反向、跳变或冲突时返回 `INCONSISTENT` 或 `INSUFFICIENT`。

## Why Not Daily Reports

日报是叙事输出，不是适合承载来源、时间、空间和版本约束的状态事实。以日报为主架构会把生成文本、人工叙述和施工状态混在一起，削弱未来 as-of 查询和Claim许可判断的可解释性。

## Mechanical Response Is Not Geology

推进速度、推力、扭矩和转速可以帮助识别机器是否处于推进过程，但不能直接推出地质原因。本阶段所有质量报告和弱标签都禁止输出地质结论。

## Boundary for Future Bitemporal State

Stage 2 在 Episode 和 SpatialFootprint 上叠加 ResponseEvidence、GeologicalEvidence 和 EvidenceApplicability。Stage 2E V2 进一步把91天PLC operational evidence冻结为唯一、确定性、可追溯的 SourceAsset、NormalizedObservation manifest、PhaseInterval、PLC-inferred ExcavationEpisode、SpatialFootprint 和 ResponseEvidence，并用 chainage regime 区分 raw PLC range 与 trusted spatial scope。当前代码只保存稳定ID、来源引用、有效时间、方法版本和质量原因，不提前创建双时间仓库或Claim推理类。

## Stage 2 Evidence Boundary

`ResponseEvidence` 是PLC核心推进观测上的统计证据，只描述施工机械响应，不解释地质原因。`GeologicalEvidence` 是规则化地质资料表示，显式保留 FORECAST、OBSERVED、BACKGROUND 和 UNKNOWN 认识性质。`EvidenceApplicabilityAssignment` 只回答某条证据在指定 evaluation_time 下对某个Episode是否可用、空间上如何相关、认识性质是否需要限定；空间重叠不表示因果，FORECAST也不会被升级为OBSERVED。

Stage 3 的正式输入只能来自：

```text
artifacts/stage2_geology_v2_freeze_candidate/
artifacts/stage2d_applicability_v2_1/
artifacts/stage2_plc_operational_freeze_v2/
artifacts/stage3a_initial_epistemic_state_v1_1/
artifacts/stage3b_bitemporal_epistemic_state_v1_1/
```

Stage3A v1.1 的正式目录是 `artifacts/stage3a_initial_epistemic_state_v1_1/`。Stage3B 只能读取该目录作为 Stage3A 状态输入。禁止 Stage3B 读取 `artifacts/stage3a_initial_epistemic_state_v1/`，该旧版本为 `SUPERSEDED_BY_STAGE3A_V1_1` 且 `POINT_RESPONSE_INCOMPLETE`；也禁止 Stage3B 读取 `artifacts/stage3a_initial_epistemic_state_v1_1_candidate/`。

Stage3B v1.1 的正式目录是 `artifacts/stage3b_bitemporal_epistemic_state_v1_1/`。后续指标和 Claim 层只能读取该目录作为双时间认识状态输入。禁止后续正式链路读取 `artifacts/stage3b_bitemporal_epistemic_state_v1_candidate/`；该候选目录只保留作 promotion audit 对照。

Stage4 v1.1 的正式目录是：

```text
artifacts/stage4_bitemporal_state_metrics_v1_1/
```

Stage4 输出 RAI、GRS 和 GRCI 三类双时间状态指标。RAI 使用 LOAD_RESPONSE 与
ADVANCE_KINEMATIC_RESPONSE 两个 scalar family 的 robust deviation；RPM 保留为
diagnostic trace，不进入 scalar RAI。GRS 使用六个人工冻结的地质关注维度，缺失维度不补0且不进入分母。GRCI 只在 DAILY_REVIEW_CELL 中以非概率乘积 `RAI × GRS` 定义。Stage4 指标不是风险概率、灾害概率、因果估计或 Typed Claim。

Stage5 以后只允许读取 `artifacts/stage4_bitemporal_state_metrics_v1_1/` 作为指标输入。

Stage5A Typed Engineering Claim Schema & Claim Contract 的正式目录是：

```text
artifacts/stage5a_typed_claim_contract_v1/
```

Stage5A 只冻结 Claim schema、ClaimContract、source-constrained expressibility、
abstention、subject binding 和 authoritative resolved support 输出。Stage5A 不批量
生成 Claim，不生成 Evidence Pack，不调用 LLM。Stage5B Deterministic Claim Builder
为 `NOT IMPLEMENTED`。

`ConstructionStateVersion` 把10m Cell作为空间索引，但 Cell 身份只由 alignment、grid、cell index 和边界策略确定。Stage 2E 的 `reconstructed_at` 只表示离线冻结构建时间，不是历史摄取时间；`historical_ingestion_time` 在本轮保持未知。旧 Applicability V2、旧 PLC Operational Freeze 和旧 Stage3A v1 只保留作审计比较，不作为正式 Stage 3 输入。
