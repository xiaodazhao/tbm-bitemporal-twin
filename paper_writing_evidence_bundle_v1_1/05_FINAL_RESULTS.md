# 最终结果总览

## RQ1：系统在冻结知识状态下允许表达多少工程主张？

**Finding**：8,679 个 Claim opportunities 中，6,279 个 EXPRESSIBLE，2,400 个 ABSTAIN；可表达率 72.347%，拒答率 27.653%。

**Evidence**：主要拒答原因为 UNKNOWN_SOURCE_VALUE 1,078、CONTEXT_ONLY_ROLE 880、STATE_ROLE_NOT_ALLOWED 305、REQUIRED_EPISTEMIC_STATUS_MISSING 105、REQUIRED_METRIC_UNAVAILABLE 32。

**Limitation**：这是给定合同与冻结证据下的可表达性，不是模型 accuracy，也不是工程风险识别准确率。

## RQ2：受控架构与直接/提示约束生成的机器行为有何差异？

**Finding**：B0 与 B1 均得到 48/48 输出；P 得到 45/48，有 3 个计划因 section order 不合法被确定性拦截并 fail closed。45 个 P 输出 post-audit 全部通过。

**Evidence**：Stage7B 共 48 tasks、144 条真实请求；P 的 invalid tasks 为 task_022、task_026、task_042，错误码均为 INVALID_SECTION_ORDER。

**Limitation**：工程语义正确性、实用性和误导风险仍为 DEFERRED_TO_HUMAN；不能用自动 check-instance 数代替任务级 accuracy。

## RQ3：双时间建模是否捕捉到后到知识的实际变化？

**Finding**：48-task benchmark 与 53 个 revision events 无重叠，因此 alignment 结果为 null；全量 census 显示 53/53 修订均引入新 FORECAST，其中 9 个也引入 OBSERVED。RAI 变化 0/53，GRS 变化 36/53，GRCI 变化 1/53；27 个事件发生 ABSTAIN→EXPRESSIBLE，新增 540 个地质 Claim opportunities，其中 454 可表达、86 仍拒答。

**Evidence**：完整 revision census 覆盖 14 个日期和 51 个 Cell。

**Limitation**：benchmark null 不能解释为双时间无效；knowledge time 是重建的证据可用时间，不是原生事务日志。

## RQ4：架构组件移除揭示了什么？

**Finding**：A1 因无可执行绕过样本而 NOT_EXECUTABLE。A2 的 31/31 目标段落均形成非空文本，但语义正确性 deferred。A3 strict primary 为 125/147 valid chunks、828/989 mappings、32/45 complete tasks；fence-only secondary 为 147/147、989/989、45/45。两种口径中被映射数值均 100% 精确（149/149 和 164/164，drift=0）。A4 覆盖 848/1022 FactLocks（82.9746%），数值覆盖 162/171（94.7368%），被引用的 162/162 数值均精确，9 个数值 FactLocks 被遗漏。

**Evidence**：Stage7E 最终 machine summary 和修正后的 Unicode-safe 数值审计。

**Limitation**：A3 主要暴露 structured-interface compliance；A4 主要暴露 coverage loss。两者均不能替代人工语义评价。

## RQ5：结论对参数变化是否稳定？

**Finding**：5 m 与 10 m 的 RAI median/max Spearman 为 0.9493/0.8383，GRCI 为 0.9347/0.8997；GRS 在角色与聚合口径间约 0.8894–0.9999。20 m 出现 90 个角色冲突、23 个点证据欠覆盖和 76 个区间覆盖不匹配，属于粗分辨率压力测试。历史 20/40 相对基线各只引起 4 个 availability-boundary Claim 翻转；共同可用值 rho=1、MAD=0。饱和尺度 2/4 对基线保持很高秩一致性，Claim transitions=0，monotonicity violations=0。

**Evidence**：Stage7F final interpretation 与三组 pairwise statistics。

**Limitation**：不能写“5–20 m 均匀稳健”；20 m 已越过当前表示方法的原生有效性边界。
