# 实验设计

## 实验 1：受控生成主对照

**科学问题**：在相同工程证据、相同任务和相同模型下，架构级控制能否减少可自动检测的工程语义/结构违规？这种控制付出的输出可用性代价是什么？

- B0：Direct LLM，自由直接生成。
- B1：Prompt-constrained LLM，以结构化提示约束。
- P：Proposed architecture，Claim Gate + FactLock + 受控实现。
- 样本：48 个 held-out tasks × 3 条件 = 144 条真实请求。
- P 输出：45 个有效输出；task_022、task_026、task_042 因 `INVALID_SECTION_ORDER` fail closed。
- 人工工程语义比较：`DEFERRED_TO_HUMAN`。

## 实验 2：Claim admissibility 全量分析

**科学问题**：在冻结状态、证据角色和认识边界下，哪些候选主张可以合法物化，哪些必须拒绝？

对 8,679 个冻结 opportunity 逐一应用 Claim Contract，统计 EXPRESSIBLE/ABSTAIN 和原因。该实验衡量合同内可表达性，不是模型准确率、风险识别率或事实真值率。

## 实验 3：双时间价值

**科学问题**：后到证据如何改变 as-known 状态、指标和主张准入，同时避免污染更早知识状态？

A. 48-task benchmark alignment：真实 pre-revision exposure 为 0，因此是 `BENCHMARK_ALIGNMENT_NULL_RESULT`，只说明 held-out benchmark 没覆盖修订事件。

B. 全量 revision census：检查 53 个修订事件，比较 pre/post 状态、RAI/GRS/GRCI、已有 Claim 决策和新增 opportunity。

## 实验 4：架构消融

**科学问题**：Claim Gate、显式不足表达、FactLock 结构接口和最终自由实现各自承担什么机制作用？

- A1 Claim Gate generation ablation：冻结 benchmark 无具体 gate-bypass 候选，状态为 `NOT_EXECUTABLE_ON_FROZEN_48_TASK_BENCHMARK`。
- A2 去除架构化 abstention：观察 31 个目标段落是否被非空文本取代；语义正确性留给人工。
- A3 去除 FactLock，以 Typed Claims 直接要求模型输出结构化结果：区分严格 primary parser 和 fence-only secondary parser。
- A4 自由最终实现：测量 FactLock 覆盖和被引用数值的精确保持，区分“遗漏”与“值损坏”。

## 实验 5：敏感性与表示有效性边界

**科学问题**：空间分辨率、历史充分性和 robust-z 饱和尺度变化时，指标排序、可用性和 Claim 决策如何变化？

采用 OFAT：

- Cell size：5/10/20 m；10 m 基线，5 m 为有效敏感性臂，20 m 为粗分辨率压力测试。
- RAI minimum history：20/30/40；30 为基线。
- RAI saturation robust-z：2/3/4；3 为基线。

比较可用率、Spearman 相关、绝对差、Claim transitions 和空间质量门。不同 Cell 网格改变了 universe，不能直接用总 Claim 数判断优劣。

## 共同设计约束

- 冻结输入和 frozen IDs 不因评价而修改。
- 所有机器端点为确定性复算或冻结输出审计。
- 人工语义端点未完成时显式 deferred。
- 不把自动结构/覆盖指标解释为工程语义正确率。
