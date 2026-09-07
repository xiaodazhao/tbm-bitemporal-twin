# 主实验：三方法真实模型比较

## 设计

Stage7A.3 冻结 48 个 held-out tasks。每个任务以完全相同的 as-of evidence snapshot 构造三种条件，总计 144 个执行项，均使用 `deepseek-v4-flash`、temperature=0、top_p=1、max_retries=0。

- **B0**：把 pre-Claim 原始结构输入直接交给模型生成。
- **B1**：同一 pre-Claim 信息配合结构化提示生成。
- **P**：冻结 Claim Gate、FactLock、Evidence Pack 和 deterministic composer；模型只规划 RealizationUnit 顺序。

## 执行结果

B0 产生 48/48 输出，B1 产生 48/48 输出。P 收到 48 个 raw plans，其中 45 个通过严格 schema 与 section-order 校验并形成最终文本；任务 `022`、`026`、`042` 因 `INVALID_SECTION_ORDER` 被 fail closed，因此 P 最终输出为 45/48。三项不是 transport failure，也没有重试或 JSON repair。

## 确定性评价

Stage7C.1 v1.2 对 E2/E3/E4/E5/E7/E10/E12/E13/E14 做离线规则审计。P 的 45 份实际文本在自动可判定项上没有 fail；B0 出现 2 个 E5 自动 fail；B1 没有自动 fail。这里的分母是 check instances，不是 48 个任务的“准确率”。P 的 3 个无输出任务保留在 condition denominator 中，但不被算作 prose semantic failure。

## 尚未完成的评价

E7 的语义完整性、E14 的整体工程可接受性，以及许多 E2/E4/E5/E10/E12 边界样本仍标记 `DEFERRED_TO_HUMAN`。因此现有机器结果能够支持“结构、数值、边界和 trace 的确定性约束更强”，不能支持“P 的工程语义质量已经被人工证明优于 B0/B1”。

## 复现身份

正式 run 为 `stage7b_main_execution_3ae0f791811a2e711cb9f488`，execution manifest hash=`75f2f9976b2cc85bdcf79a790baf07a8c623fa3fa24c2de16cdbdef9eafe34cc`，protocol hash=`19c1bb629765198316c44951bddfbdf7547f017da6793c698c6f98f376260cbf`。
