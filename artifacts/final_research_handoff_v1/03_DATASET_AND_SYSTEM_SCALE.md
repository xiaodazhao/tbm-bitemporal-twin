# 数据集与系统规模

## 输入边界

研究对象为单一 TBM 工程进口右线。PLC 覆盖 **91 PLC-monitored construction dates**，从 **2023-09-15** 跨度至 **2023-12-30**；这些日期并非连续日历天。原始地质资产治理结果为 227 个 raw assets，其中 225 个 in-scope assets，2 个 duplicate aliases 和 2 个 out-of-scope assets，形成 223 个 canonical documents。

## 证据规模

- PLC 标准观测：328217。
- ExcavationEpisode：1119。
- ResponseEvidence：5595。
- Primary Geological Evidence：659，其中 OBSERVED=278、FORECAST=381。
- ReportAssertion：122；SourceSpan：4713。

## 状态与指标规模

- 固定 10 m ConstructionStateCell：156。
- DailyConstructionState：91；InitialStateVersion：1322。
- BitemporalVersion：1375；RevisionEvent：53。
- RAI/GRS/GRCI 对每个双时间版本均有状态对象，各 1375 条；实际可用分别为 174、1211、174。

## Claim 规模

冻结 universe 有 8679 个 opportunity。6279 个满足合同并生成 Typed Claim，2400 个正式拒绝表达。可表达率 72.347% 只表示合同与证据边界内的 materialization rate，不是模型准确率。

完整逐层表见 `03_dataset_scale.csv`。
