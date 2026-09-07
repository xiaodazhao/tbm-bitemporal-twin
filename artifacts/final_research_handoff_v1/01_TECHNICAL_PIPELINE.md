# 完整技术路线

## 1. 资产与证据治理

**输入**：91 个 PLC 监测施工日期对应的 CSV、227 个原始地质 PDF 资产。  
**方法**：SHA-256 去重、左右线范围治理、SourceAsset 登记、分页文本、source timezone 本地化后转 UTC、submitted/document/observed 时间分离。PDF 主表由 `pdfplumber` 解析并以真实页码和 bbox 形成 SourceSpan。  
**输出**：标准 PLC Observation；223 个 canonical GeologicalDocument；659 条 Primary Geological Evidence；122 条 ReportAssertion；4713 个 SourceSpan。  
**约束**：表头、方法原理和仪器说明不是地质 Evidence；FORECAST/OBSERVED 由来源语义决定；无法定位的条款不扩展到文档范围。

## 2. 施工过程对象

**输入**：按时间排序的 PLC Observation。  
**方法**：状态机识别 IDLE、STARTUP、EXCAVATING、COASTDOWN、UNKNOWN，随后将相邻相位聚合为 `ExcavationEpisode`。Episode 的核心时间只由首末 EXCAVATING 区间定义；上下文时间、内部中断、文件边界截断和覆盖率独立保存。  
**输出**：1119 个 Episode、对应 SpatialFootprint 与 5595 条通道级 ResponseEvidence。  
**约束**：文件首尾截断不能伪装成真实起止；0 m 推进冲突保留；单位未验证字段不能用于物理计算；机械响应不解释为地质原因。

## 3. 空间足迹与适用性

**输入**：Episode footprint、地质 point/interval evidence、available time。  
**方法**：把 10 m ConstructionStateCell 作为空间索引；按区间重叠、点边界唯一归属、target date 与 knowledge availability 判定 Evidence role。  
**输出**：59969 条 Primary Evidence Applicability assignments，并区分 DAILY_REVIEW、FORWARD_ATTENTION、LOCAL_BACKGROUND、NOT_APPLICABLE。  
**约束**：未来网格只是索引，不是施工事实；前方预报进入 DAILY_REVIEW 后仍是 FORECAST；LOCAL_BACKGROUND 不能直接支持事实 Claim。

## 4. 初始施工认识状态

**输入**：Episode、ResponseEvidence、Applicability assignments。  
**方法**：为每个 PLC-monitored construction date 构建 DailyConstructionState，把实际开挖关联到 156 个固定 Cell，再生成 1322 个 InitialStateVersion。  
**输出**：2685 条地质链接、5510 条 Cell-level response 链接；另保留 95 条 located point daily-only 与 75 条 spatially unlocated response coverage。  
**约束**：5595/5595 ResponseEvidence 必须有唯一覆盖类；不可定位对象不静默丢失，也不猜测空间。

## 5. 双时间认识状态

**输入**：初始状态、后到地质证据的 available time、历史 applicability。  
**方法**：valid date 表示被描述的施工日；knowledge interval 表示该版本在何时可被系统知道。新证据到达时，新版本通过 `supersedes_bitemporal_version_id` 连接旧版本。  
**输出**：1375 个 bitemporal versions、53 个 revision events、72 条 revision evidence links。  
**约束**：版本方向来自 version_number 与 supersession lineage，不来自 ID 字典序；历史数据库 transaction log 不可得，knowledge time 是可审计的认识可用性重建。

## 6. RAI：施工响应关注度

对每个通道，先以只使用此前观测的因果历史窗口计算 robust z：

```text
z_c = (x_c - median_history,c) / (1.4826 * MAD_history,c)
d_c = median_episode(|z_c|)
```

LOAD_RESPONSE 包含 total_thrust 与 cutterhead_torque；ADVANCE_KINEMATIC_RESPONSE 包含 advance_speed 与 penetration。族内取两通道 `d_c` 的最大值，族关注度为 `min(d_family / 3, 1)`，最终 `RAI=max(A_LOAD,A_KINEMATIC)`。两族必须都完整；cutterhead_rpm 仅作诊断，不进入标量 RAI。

## 7. GRS：地质证据关注度

冻结的 44 个来源值映射到六个维度：异常、围岩等级、岩体完整性、节理发育、稳定/掉块和水。维度内使用最值得关注的映射值：

```text
G_d = max(mapped_attention values in dimension d)
GRS = mean_non_null_dimension_attention(G_d)
```

缺失维度不当作 0。证据角色和 FORECAST/OBSERVED 状态完整保留。

## 8. GRCI：联合关注度

仅在 DAILY_REVIEW_CELL 且 RAI、GRS 同时可用时：

```text
GRCI = RAI * GRS
```

它是非概率 conjunctive attention，不是风险概率，也不是地质—机械因果估计。

## 9. Claim opportunity 与 admissibility

Stage5B 对每个双时间状态、主体和属性槽位确定性枚举 Claim opportunity。Stage5A Claim Contract 要求权威 support kind、state role、epistemic status、metric availability、qualifiers 与 spatial subject binding，并禁止 probability/causality 等越界语义。全部满足则物化 TypedEngineeringClaim；否则输出 ABSTAIN 与单一主原因码。

## 10. FactLock、Evidence Pack 与受控实现

每个 EXPRESSIBLE Claim 转为 FactLock，记录原值、范围、认识状态、支持对象、允许修饰语和禁止变换。Evidence Pack 按日期/Cell/产品切片，并用 hash 锁定。模型只能对 RealizationUnit 返回 pure-JSON 计划；随后由确定性 materializer、validator、composer 与 post-audit 生成文本。任何结构错误均 fail closed，不进行 JSON repair。

## 11. 实验与追溯

Stage7A 冻结 held-out benchmark；Stage7B 运行 B0/B1/P；Stage7C 做确定性错误审计；Stage7D 分析双时间修订价值；Stage7E 做消融；Stage7F 做参数敏感性。每个核心数字在 `14_RESULT_TRACEABILITY.csv` 中映射到 frozen source、commit、tag 与字段。
