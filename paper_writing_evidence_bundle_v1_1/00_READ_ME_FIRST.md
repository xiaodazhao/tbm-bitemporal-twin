# 论文写作证据包：请先阅读

## 项目与用途

- **项目**：`tbm-bitemporal-twin`
- **目标期刊**：Advanced Engineering Informatics（AEI）
- **资料包版本**：Paper Writing Evidence Bundle v1.1（Writer-Facing Table Clarification）
- **用途**：让未接触代码库的论文写作者在不运行程序、不访问外部服务的前提下，理解研究方法、实验设计、最终机器结果、认识边界和证据来源。

本包不是完整仓库，也不是原始复现归档。它是从冻结产物中抽取的论文写作证据层。权威数字见 `traceability/FINAL_RESULT_REGISTRY.csv`，失效结果见 `traceability/SUPERSEDED_RESULTS_DO_NOT_USE.csv`。

v1.1 只澄清论文-facing 表格、图数据与分母语义，不改变任何实验、方法、案例或人工评价状态。原 v1 继续由 `paper-writing-evidence-bundle-v1-frozen` 独立冻结。

## 研究主线

```text
动态施工证据
  -> 双时间认识施工状态
  -> 类型化工程主张准入
  -> EXPRESSIBLE / ABSTAIN
  -> FactLock（事实锁）
  -> 受控语言实现
```

研究关注的不是“让大模型自由生成施工日报”，而是：在工程有效时间和知识可用时间的共同约束下，先确定哪些工程主张有资格表达，再对已锁定事实进行受控语言实现。日报只是可能的下游产品之一。

## 不可越过的责任边界

- 大语言模型不计算工程事实。
- 大语言模型不判断地质风险。
- 大语言模型不是事实权威来源。
- 预测证据不能升级成观测事实。
- 机械响应不能自动解释成地质原因。
- 未知或缺失不能写成正常或零。
- RAI、GRS、GRCI 均为关注指标，不是灾害概率。

## 推荐阅读顺序

1. `00_READ_ME_FIRST.md`
2. `01_MANUSCRIPT_BRIEF.md`
3. `02_RESEARCH_METHOD.md`
4. `03_DATASET_AND_IMPLEMENTATION.md`
5. `04_EXPERIMENT_DESIGN.md`
6. `05_FINAL_RESULTS.md`
7. `06_RESULT_INTERPRETATION.md`
8. `07_SCIENTIFIC_BOUNDARIES.md`
9. `08_HUMAN_EVALUATION_STATUS.md`
10. `09_CASE_STUDIES.md`
11. `10_PAPER_OUTLINE.md`
12. `11_WRITING_INSTRUCTIONS_FOR_LLM.md`

随后按需查看 `tables/`、`figures/`、`experiments/`、`cases/` 和 `traceability/`。

## 结果状态

机器实验已经冻结。B0/B1/P 的人工工程语义评价和 Human Claim Gold 尚未执行。所有相关位置必须明确写成 `DEFERRED_TO_HUMAN` 或 `NOT_YET_EXECUTED`，不得补零、估计或推测。
