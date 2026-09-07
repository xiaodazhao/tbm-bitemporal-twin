# 项目总览

## 一句话定义

本项目研究的不是“让大语言模型自动写 TBM 日报”，而是构建一个**受证据、空间、有效时间和知识可用时间共同约束的施工认识状态系统**：在指定 knowledge time 下，系统只允许表达当时有权威证据支持的工程 Claim，并把不能表达的内容正式判为 `ABSTAIN`。

## 科学问题

施工数据具有三类根本异质性：PLC 是高频过程观测，地质预报是面向前方区间的预测认识，掌子面素描是后到或当下的观测认识。若只按“某天的日报”拼接文本，会把后来资料泄漏到过去、把 FORECAST 写成 OBSERVED、把缺失写成正常，并让机械异常被误解为地质原因。本研究因此追问：

> 对于特定施工空间单元、valid time 与 knowledge time，当时可获得的证据允许系统表达哪些工程认识？后到证据如何修订这种可表达性？

## 核心链路

```text
PLC/PDF 原始资产
  -> SourceAsset、分页文本、时区与哈希治理
  -> OperationPhase、ExcavationEpisode、SpatialFootprint
  -> 机械响应证据 + 地质 FORECAST/OBSERVED 证据
  -> time/space/epistemic Applicability
  -> ConstructionStateCell + DailyConstructionState
  -> valid time × knowledge time 的双时间认识状态
  -> RAI / GRS / GRCI 非概率关注指标
  -> Typed Claim opportunity + Claim Contract
  -> EXPRESSIBLE 或 ABSTAIN
  -> FactLock + Evidence Pack
  -> 模型仅规划表达顺序
  -> 确定性物化、校验、组合与审计
```

## 大语言模型的真实角色

大语言模型只出现在最后的 presentation planning 层。它看见的是冻结的 RealizationUnit 和表达约束，只能返回最小 JSON 计划；工程事实值、认识性质、空间范围、Claim 许可和最终规范句均由上游权威对象及确定性代码决定。模型不能计算施工事实、判断地质原因、补齐 UNKNOWN、把 attention 解释为概率，也不能绕过 FactLock。

## 冻结研究规模

- 328217 条 PLC 标准观测，形成 1119 个 ExcavationEpisode。
- 91 PLC-monitored construction dates，跨度 2023-09-15 至 2023-12-30，中间存在日历空档。
- 223 份 canonical geological documents，659 条 Primary Evidence。
- 1322 个初始状态与 1375 个双时间状态版本。
- 8679 个 Claim opportunities，其中 6279 EXPRESSIBLE、2400 ABSTAIN。
- 主实验为 48 个 held-out tasks × 3 种方法；机器实验已完成，人工语义评价保留为 `DEFERRED_TO_HUMAN`。

## 研究贡献的准确表述

本项目能够证明的是：证据治理、双时间状态、Claim Contract、受控实现和审计链在本工程数据上实现了内部一致、可追溯和确定性行为；后到证据确实能够在不污染历史认识的情况下改变 GRS、GRCI 与 Claim 可表达性。它不能证明跨项目普适性、灾害概率、因果诊断、人工工程正确率或对所有生成基线的普遍优越性。
