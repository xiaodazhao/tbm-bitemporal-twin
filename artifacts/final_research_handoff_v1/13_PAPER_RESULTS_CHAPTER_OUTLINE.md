# 论文结果章节骨架

## 4.1 Experimental setup

- **Research question**：三种 realization 方法在同一 as-of 输入下的可审计行为有何差异？
- **Data**：48 held-out tasks × B0/B1/P。
- **Metrics**：输出可用率、结构 fail-closed、E2-E14 自动 endpoints、人工评价状态。
- **Table/Figure**：Table 3；Figure main experiment。
- **Main finding**：P 45/48 通过严格计划门，3 个结构错误被拦截；自动可判定文本项零 fail。
- **Allowed**：受控层提供可观察、可拦截的结构行为。
- **Forbidden**：在人工评价完成前宣称整体语义显著优于 baseline。

## 4.2 Dataset and implementation

- **Research question**：证据和状态系统的实际规模与覆盖是什么？
- **Data**：Stage2-6 frozen manifests。
- **Metrics**：observations、Episode、Evidence、State、Metric、Claim 数量。
- **Table/Figure**：Table 1；技术路线图。
- **Main finding**：异构证据被统一到可追溯的时空认识状态。
- **Allowed**：报告单工程内部覆盖与质量门。
- **Forbidden**：称 91 天为连续日期或将单工程规模外推。

## 4.3 Main comparison

- **Research question**：直接、结构化提示、Claim-gated controlled realization 的机器行为差异。
- **Data**：Stage7B raw/final outputs 与 Stage7C deterministic audits。
- **Metrics**：输出率、自动错误、结构拦截。
- **Table/Figure**：Table 3；Figure 3。
- **Main finding**：P 将不可接受 plan fail closed，并保持数值/认识边界。
- **Allowed**：确定性 endpoints。
- **Forbidden**：把 check-instance count 当 task accuracy。

## 4.4 Claim admissibility analysis

- **Research question**：证据与合同边界如何塑造可表达空间？
- **Data**：8679 frozen opportunities。
- **Metrics**：EXPRESSIBLE/ABSTAIN、reason taxonomy。
- **Table/Figure**：Table 2；Claim gate bar chart。
- **Main finding**：72.347% 可表达，27.653% 正式拒答；近半拒答源于 policy/context boundary。
- **Allowed**：contract-governed expressibility。
- **Forbidden**：解释成 accuracy 或 failure rate。

## 4.5 Bitemporal knowledge revision

- **Research question**：later evidence 如何改变指标与 Claim？
- **Data**：48-task null alignment + 53-event full census。
- **Metrics**：metric change、decision switch、opportunity addition。
- **Table/Figure**：Table 4；revision transition figure。
- **Main finding**：地质修订主要改变 GRS 和 geological Claim，不改变 RAI。
- **Allowed**：说明双时间保留 as-known 历史的必要性。
- **Forbidden**：用 benchmark null 否定双时间价值。

## 4.6 Ablation study

- **Research question**：gate、qualifier、plan structure、FactLock trace 的作用。
- **Data**：Stage7E final corrected machine summary。
- **Metrics**：A1 status、A2 affected、A3 strict/secondary、A4 coverage。
- **Table/Figure**：Table 5；ablation coverage figure。
- **Main finding**：数值漂移为 0；严格 schema 暴露 22 个 fence failures；trace 并非全覆盖。
- **Allowed**：结构与 trace 的机器证据。
- **Forbidden**：把 numeric exact/trace coverage 当语义正确率。

## 4.7 Sensitivity and robustness

- **Research question**：三类参数扰动如何改变结果与有效性边界？
- **Data**：7 个 OFAT arms。
- **Metrics**：native quality gate、availability、Claim transitions、rank/value behaviour。
- **Table/Figure**：Table 6；sensitivity panel。
- **Main finding**：5 m 有效；20 m 越界；history 改变早期可用性；saturation 改值不改 Claim。
- **Allowed**：有限条件下的敏感性描述。
- **Forbidden**：宣布 5-20 m 等稳健或自动选择最优参数。

## 4.8 Engineering case study

- **Research question**：完整证据链和知识修订在具体里程上如何工作？
- **Data**：2023-10-07 主案例；2023-11-28 修订案例。
- **Metrics**：RAI/GRS/GRCI、Claim/FactLock/输出与 revision transitions。
- **Table/Figure**：案例链路图、pre/post 状态图。
- **Main finding**：controlled realization 保留 FORECAST 与非概率边界；later evidence 扩展可表达空间而不覆盖旧认识。
- **Allowed**：逐对象 trace-backed 解释。
- **Forbidden**：把个案写成因果证明或跨工程结论。
