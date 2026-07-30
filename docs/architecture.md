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

Stage 2 在 Episode 和 SpatialFootprint 上叠加 ResponseEvidence、GeologicalEvidence 和 EvidenceApplicability。当前代码只保存稳定ID、来源引用、有效时间、方法版本和质量原因，不提前创建双时间仓库或Claim推理类。

## Stage 2 Evidence Boundary

`ResponseEvidence` 是PLC核心推进观测上的统计证据，只描述施工机械响应，不解释地质原因。`GeologicalEvidence` 是规则化地质资料表示，显式保留 FORECAST、OBSERVED、BACKGROUND 和 UNKNOWN 认识性质。`EvidenceApplicabilityAssignment` 只回答某条证据在指定 evaluation_time 下对某个Episode是否可用、空间上如何相关、认识性质是否需要限定；空间重叠不表示因果，FORECAST也不会被升级为OBSERVED。
