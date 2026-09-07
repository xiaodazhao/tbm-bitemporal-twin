# 研究方法

## 1. 总体方法链

```text
PLC 原始序列 + TSP/HSP/掌子面素描
  -> 标准化观测与分页地质证据
  -> OperationPhase -> ExcavationEpisode -> SpatialFootprint
  -> Operational / Geological Evidence
  -> Evidence Applicability（角色与时空适用性）
  -> ConstructionStateCell + DailyConstructionState
  -> Bitemporal Epistemic Construction State
  -> RAI / GRS / GRCI
  -> Claim Opportunity -> Claim Contract
  -> EXPRESSIBLE 或 ABSTAIN
  -> FactLock + Evidence Pack
  -> 大模型仅规划表达单元顺序
  -> 确定性物化、校验、组合与事后审计
```

## 2. 原始输入与证据治理

### 2.1 PLC

PLC 序列经字段映射、时区标准化和质量审计后形成规范观测。运行阶段检测将观测分为施工相位，再构造 `ExcavationEpisode`。未核实单位的字段不能用于物理推导。

### 2.2 地质来源

地质来源包括 TSP 地震波反射法报告、HSP/SONIC 水平声波预报和掌子面素描。表格解析保留文档、页码、单元格边界框、原文和解析角色。正式 Primary Evidence 只保留掌子面/已开挖观测与明确预报区段；报告级总结作为 ReportAssertion，无法空间定位的句子独立保存。

### 2.3 证据基本维度

每条证据至少保留：来源引用、valid time、knowledge time、空间范围、epistemic status 和 evidence role。`OBSERVED` 与 `FORECAST` 是来源认识性质，不因后续使用而改变。角色包括 `DAILY_REVIEW`、`FORWARD_ATTENTION` 和 `LOCAL_BACKGROUND`。

## 3. ExcavationEpisode

`ExcavationEpisode` 是由 PLC 推断的施工过程对象，不是人工标注真值。核心有效推进时间由首末 `EXCAVATING` 区间定义；前后启动/衰减和内部中断保存在上下文中。文件边界截断、零进尺冲突和空间不可用均显式标记，不通过猜测修复。

空间足迹依据可信里程观测构造，可以是区间、点或不可定位。日期只用于查询和聚合，不替代 Episode 身份。

## 4. ConstructionStateCell 与 DailyConstructionState

基线采用 10 m `ConstructionStateCell`，它是对齐和索引单元，不是原子地质真值。点证据执行唯一边界归属，区间证据按实际重叠关联。`DailyConstructionState` 只在 91 个有 PLC 监测的施工日期构造，不把日期间隔补成连续施工事实。

## 5. 双时间认识施工状态

- **有效时间（valid time）**：证据或状态所描述的工程现实时间。
- **知识时间（knowledge time）**：证据进入可用知识状态的重建边界。

地质资料优先以明确提交日期形成 available time，没有提交日期时保守使用文档日期。Stage3B 按证据可用时间建立修订链：v1 保留当时已知内容，后来资料只进入后续版本。由于历史事务日志不存在，knowledge time 是可审计的认识可用性重建，不是原生数据库 transaction time。

## 6. RAI：施工响应关注指标

RAI 使用严格早于目标 Episode 的同通道因果历史建立稳健基线。对通道 `c`：

```text
z_c = (x_c - median(history_c)) / (1.4826 * MAD(history_c))
d_c = median_episode(|z_c|)
```

荷载族由总推力与刀盘扭矩构成，运动族由掘进速度与贯入度构成。族内去重复聚合取通道偏离的最大值：

```text
d_LOAD = max(d_total_thrust, d_cutterhead_torque)
d_KINEMATIC = max(d_advance_speed, d_penetration)
attention_family = min(d_family / 3, 1)
RAI = max(attention_LOAD, attention_KINEMATIC)
```

只有两族均完整且历史样本数至少为 30 时 RAI 才可用。饱和尺度为 robust-z=3。刀盘转速仅作为测量制度诊断通道，不进入 RAI 标量。RAI 是非概率关注度，不能推出地质原因。

## 7. GRS：地质证据关注指标

结构化地质属性经人工冻结的 ordinal mapping 映射到六个关注维度。聚合规则必须区分两个层次：

```text
维度内：max_mapped_attention
状态级：mean_non_null_dimension_attention
```

即同一维度中取已映射值的最大关注度，再对所有可用且非空维度取均值。未映射值保持不可用，不补为零。GRS 是证据关注指标，不是地质灾害概率。

## 8. GRCI：耦合关注指标

```text
GRCI = RAI × GRS
```

算子名为 `NONPROBABILISTIC_CONJUNCTIVE_PRODUCT`。它只在 `DAILY_REVIEW_CELL_ONLY` 且 RAI 与 GRS 同时可用时定义。GRCI 不是概率、因果诊断或危险度。

## 9. Claim Opportunity 与准入

冻结状态与 Claim Contract 枚举六类候选：

1. `OPERATIONAL_RESPONSE_ATTENTION`
2. `GEOLOGICAL_EVIDENCE_ATTENTION_REVIEW`
3. `COUPLED_ATTENTION_REVIEW`
4. `FORWARD_GEOLOGICAL_ATTENTION`
5. `OBSERVED_GEOLOGICAL_CONDITION`
6. `FORECAST_GEOLOGICAL_CONDITION`

Claim admissibility 是类型化确定性领域合同，不是关键词过滤，也不由大模型判断。只有权威支持、主体绑定、空间角色、认识状态、指标状态和限定语全部满足时才输出 `EXPRESSIBLE`；否则输出带原因码的 `ABSTAIN`。ABSTAIN 是正式系统输出。

## 10. FactLock、Evidence Pack 与受控实现

每个 EXPRESSIBLE Typed Claim 被确定性转换为 FactLock，锁定主语、值、单位、范围、认识状态、支持引用及禁止变换。Evidence Pack 按任务切片组织 FactLock、RealizationUnit 和证据不足边界，并以内容哈希绑定。

大模型只返回最小表达计划：选择既有表达单元并安排顺序。它不创造工程事实、不计算指标、不判断 Claim 准入，也不写权威事实值。随后由确定性物化器生成规范句子，验证器检查计划，组合器拼接段落，post-audit 核对覆盖、引用、数值和认识边界。任何不符合结构合同的计划均 fail closed。

## 11. 全链可追溯性

派生对象保存 source IDs、method version 和稳定 ID。论文结果可从 `FINAL_RESULT_REGISTRY.csv` 回溯到冻结 artifact；案例可沿 State -> Metric -> Claim -> FactLock -> Output 逐层核验。
