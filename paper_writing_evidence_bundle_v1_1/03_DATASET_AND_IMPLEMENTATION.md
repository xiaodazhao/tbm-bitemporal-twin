# 数据集与实现规模

## 1. 工程数据范围

研究使用单一 TBM 隧道工程进口右线资料。PLC 数据覆盖 **2023-09-15 至 2023-12-30 之间的 91 个有监测施工日期**；这不是 91 个连续日历日，期间存在无数据日期和无有效 Episode 日期。

## 2. PLC 与施工过程对象

- 规范化 PLC 观测：328,217 条
- OperationPhase 区间：4,343 条
- ExcavationEpisode：1,119 个
- Operational Response Evidence：5,595 条
- provenance references：1,046,273 条
- 可用空间足迹 Episode：1,104 个
- 空间不可用 Episode：15 个

Episode 来自确定性相位分割和质量治理，不是人工逐条 ground truth。每个合格 Episode 最多形成总推力、刀盘扭矩、刀盘转速、掘进速度、贯入度五个响应证据。

## 3. 地质资料

- canonical documents：223
- Primary Geological Evidence：659
- ReportAssertion：122
- unlocated clauses：496
- SourceSpan：4,713，冻结审计 4,713/4,713 通过

按来源类型：

- FACE_SKETCH：322（点观测 167、预测区间 100、已开挖观测区间 55）
- SONIC/HSP：263（掌子面观测 49、预测区间 214）
- TSP：74（掌子面观测 7、预测区间 67）

按认识状态：FORECAST 381，OBSERVED 278。预测状态在全链中保持不变。

## 4. 状态、指标与 Claim 规模

- ConstructionStateCell：156 个，基线 10 m
- DailyConstructionState：91 个
- initial state versions：1,322 个
- bitemporal versions：1,375 个
- revision events：53 个，涉及 14 个日期、51 个 Cell
- RAI 可用：174/1,375
- GRS 可用：1,211/1,375
- GRCI 可用：174/1,375
- Claim opportunities：8,679
- EXPRESSIBLE：6,279
- ABSTAIN：2,400

## 5. 实现与复现边界

核心方法是确定性 Python 管线。PDF 主表格使用 pdfplumber；状态、指标、Claim、FactLock 和审计对象均保存方法版本与哈希。大模型只出现在受控表达实验中，使用同一冻结 benchmark、同一模型和三种方法条件。当前机器实验来自单工程、单模型，不能据此宣称跨项目或跨模型泛化。
