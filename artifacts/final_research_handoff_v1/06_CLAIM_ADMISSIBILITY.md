# Claim 可表达性与正式拒答

## 冻结 universe

Stage5B 基于 1375 个双时间状态版本确定性生成 8679 个 Claim opportunities。Stage5C 不重新生成 Claim，也不使用文本启发式改变决定，而是分析冻结 proposal/decision/typed-claim 对象。

## 总体结果

- EXPRESSIBLE：6279（72.347%）。
- ABSTAIN：2400（27.653%）。

可表达率表示：在当前 Claim Contract、状态角色、权威支持、空间主体绑定、knowledge time 和 metric availability 下，有多少冻结机会满足表达条件。它不是模型准确率、风险识别率或 LLM 正确率。ABSTAIN 也不是失败，而是防止越界陈述的正式输出。

## ABSTAIN 分类

- `UNKNOWN_SOURCE_VALUE`：1078（44.917%），来源存在但目标值未物化，禁止补全。
- `CONTEXT_ONLY_ROLE`：880（36.667%），证据仅具上下文角色，不能直接支持事实 Claim。
- `STATE_ROLE_NOT_ALLOWED`：305（12.708%），状态空间角色不允许该 Claim 类型。
- `REQUIRED_EPISTEMIC_STATUS_MISSING`：105（4.375%），缺少合同要求的 OBSERVED/FORECAST 权威认识状态。
- `REQUIRED_METRIC_UNAVAILABLE`：32（1.333%），所需指标状态不可用，不能以 0 替代。

其中政策/上下文边界类 `CONTEXT_ONLY_ROLE + STATE_ROLE_NOT_ALLOWED` 共 1185 条，占全部 ABSTAIN 的 49.375%。这部分拒答反映的是设计边界，不是数据解析失败。

## Gate 的执行顺序

1. 由权威状态对象确定 Claim 主体、valid date、Cell 与 role。
2. 根据 contract 解析 required/allowed/forbidden support kinds。
3. 对地质事实验证 source epistemic status；FORECAST 和 OBSERVED 不混层。
4. 对指标 Claim 验证 metric name、status、value 和非概率语义。
5. 验证 spatial subject binding 与 resolved support context。
6. 检查禁用语义，包括因果、概率、UNKNOWN→normal 和 forecast→observed。
7. 通过才生成 TypedEngineeringClaim；否则保存 ABSTAIN reason。

模型不参与上述任何步骤。
