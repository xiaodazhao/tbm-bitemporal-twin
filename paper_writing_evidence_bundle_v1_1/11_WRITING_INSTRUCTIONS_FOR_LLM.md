# 给论文写作模型的强制说明

You are writing an academic manuscript based only on this bundle. 你必须先完整阅读顶层 Markdown、`traceability/FINAL_RESULT_REGISTRY.csv`、每张表的 NOTE 和 `07_SCIENTIFIC_BOUNDARIES.md`，再开始写作。

1. 不得编造引用；相关工作若无可核验文献，只留引用占位。
2. 不得编造实验结果或修改任何冻结数字。
3. 不得推测缺失的人工评价分数。
4. 只使用 `FINAL_RESULT_REGISTRY.csv` 中 status 为冻结/最终的值。
5. 若端点为 `DEFERRED_TO_HUMAN`，保留显式占位。
6. 不得把 91 个监测施工日期写成 91 个连续日历日。
7. 不得把 RAI、GRS、GRCI 写成概率、危险度或因果诊断。
8. 不得把前方预测证据写成已揭露地质事实。
9. 不得宣称跨项目泛化。
10. 不得把 20 m arm 写成与 5/10 m 可互换的有效配置。
11. 不得写 A1“效果为零”；应写冻结 benchmark 上无具体 GateBypass 候选，因此不可执行。
12. 不得写自由生成导致数值普遍篡改；被实际引用的数值在当前确定性审计中 drift=0。
13. 必须区分 coverage loss 与 value corruption。
14. 必须区分 machine deterministic audit 与 human semantic correctness。
15. 必须区分 source epistemic status 与 decision/resolution status。
16. 每个关键数字必须能对应到 FINAL_RESULT_REGISTRY 的 result_id。
17. 对 benchmark null alignment 的解释只能是样本未覆盖 revision events，不能写双时间“无效”。
18. 以 Advanced Engineering Informatics 的方法严谨度写作，突出信息建模、可追溯决策和受控生成，而非宣传性产品叙述。
