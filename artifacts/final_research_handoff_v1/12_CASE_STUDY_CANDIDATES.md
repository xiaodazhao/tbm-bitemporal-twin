# 工程案例候选

## 1. Case A (recommended primary)

- 日期：`2023-10-07`
- 空间：`1013470.0-1013480.0 state cell; Episode footprint 1013474.0-1013475.0`
- Cell：`cell_3d2558b73586465c51997f14`
- Episode：`episode-414013a8fd906387a7aa03d9`
- Evidence IDs：`1b83fee0c5460b3631e0959c, 222754ad26034807e5e9b222, 57a1a9c18c276eb54418d4f1, 58149eb9a9566be1999d43bc, dcbb1d932e9b197bff68709a, doc_d1c24a2c5d644ba47f3ef2ec_e0004`
- State IDs：`state_version_6a356d329dc94fa848660e62, bitemporal_version_0fe4f28f30bcde0cc1b2cf31`
- Metrics：`{"RAI": 0.315043708909733, "GRS": 0.5416666666666666, "GRCI": 0.1706486756594387}`
- Claim IDs：`typed_claim_13dbac6cceca3cf843421b98, typed_claim_e4c7b6475a059c36c0231e5d, typed_claim_ff910119a249cb2e340c4296, typed_claim_6301ad9571de9a33e55b38eb, typed_claim_986a6bed7d92f8b13cf1022e, typed_claim_74102aa0e5351516e6dcf4b9, typed_claim_e9af4c5efb0af35fad4a0232, typed_claim_2730af786ea3aa5a46c472a6, typed_claim_f31931ac1d469de46df32266, typed_claim_8d63f1d19eb9064c0e7451e0`
- FactLocks：`fact_lock_01caee92f4c8babe430a4bfe, fact_lock_88b73f0df05f54d5aca69e33, fact_lock_8c638ec26ace682fa875a6df, fact_lock_9013b06e4db4a637be9ea2ed, fact_lock_97c681a2a7bd315e6a7e2fa9, fact_lock_9dd28fce34896d2835104f64, fact_lock_a3b19b85b45835fed58bff40, fact_lock_b32aea54bf2ead49d23c13e6, fact_lock_d464487bee4b7a46002d6055, fact_lock_f3b6d2030977246170028d65`
- Claim transitions：`{}`
- 选择原因：此案例可完整展示 PLC/geology→state→metrics→Claim→FactLock→controlled realization，并同时保留 FORECAST 与 UNKNOWN 边界。
- 冻结文本：## 地质观测事实

## 地质预报事实

2023-10-07, 针对里程 1013466.0-1013506.0, 既有地质预报资料中地质结论字段记录为: 该段围岩较前段稍有变好。岩性 为板岩夹变质砂岩，弱风化，岩 质软硬不均，节理裂隙发育，岩 体破碎，围岩整体稳定性较差。该表述保持为预报来源记录, 不作为实际揭露结论。

2023-10-07, 针对里程 1013466.0-1013506.0, 既有地质预报资料中风化程度记录为: 弱风化。该表述保持为预报来源记录, 不作为实际揭露结论。

2023-10-07, 针对里程 1013466.0-1013506.0, 既有地质预报资料中岩性记录为: 板岩夹变质砂岩。该表述保持为预报来源记录, 不作为实际揭露结论。

2023-10-07, 针对里程 1013466.0-1013506.0, 既有地质预报资料中节理裂隙发育记录记录为: 节理裂隙发育。该表述保持为预报来源记录, 不作为实际揭露结论。

2023-10-07, 针对里程 1013466.0-1013506.0, 既有地质预报资料中建议围岩等级字段记录为: Ⅳ级。该表述保持为预报来源记录, 不作为实际揭露结论。

2023-10-07, 针对里程 1013466.0-1013506.0, 既有地质预报资料中岩体状态记录为: 岩体破碎。该表述保持为预报来源记录, 不作为实际揭露结论。

2023-10-07, 针对里程 1013466.0-1013506.0, 既有地质预报资料中风险提示字段记录为: 里程+492 附 近有掉块风 险。该表述保持为预报来源记录, 不作为实际揭露结论。

## 施工响应关注度

2023-10-07, 里程 1013470.0-1013480.0施工响应关注度 RAI 为 0.315。该值为非概率关注指标, 不表示地质原因。

## 地质证据关注度

2023-10-07, 里程 1013470.0-1013480.0地质证据关注度 GRS 为 0.542。该值为非概率关注指标。

## 耦合关注度

2023-10-07, 里程 1013470.0-1013480.0 GRCI 为 0.171, 表示非概率性的地质证据—施工响应耦合关注程度。

## 前方关注度

## 证据不足边界

## 证据不足边界

UNKNOWN_SOURCE_VALUE: 来源存在但目标属性值未形成可表达事实, 不作补充推断。
- 来源：`artifacts/stage7a_experimental_protocol_v1_3/stage7_main_benchmark_manifest.json`；`artifacts/stage3a_initial_epistemic_state_v1_1/initial_construction_state_versions.jsonl`；`artifacts/stage4_bitemporal_state_metrics_v1_1/state_metric_summary.jsonl`；`artifacts/stage6a_fact_lock_evidence_pack_v1/fact_locks.jsonl`；`artifacts/stage7b_main_comparison_v1/runs/stage7b_main_execution_3ae0f791811a2e711cb9f488/P_final_outputs.jsonl`

## 2. Case A (revision census)

- 日期：`2023-11-28`
- 空间：`1014230.0-1014240.0`
- Cell：`cell_7f60fb415d2265a3f3a9e060`
- Episode：`不适用`
- Evidence IDs：`doc_1bccaf9b3397c0d25601b19d_e0002, doc_1bccaf9b3397c0d25601b19d_e0003, doc_1bccaf9b3397c0d25601b19d_e0004`
- State IDs：`bitemporal_version_42fcba905c311194b662c06a, bitemporal_version_d3a220b4d0ca6257cd8a2e17`
- Metrics：`{"RAI": {"before": "", "after": "", "changed": false}, "GRS": {"before": "", "after": "0.625", "changed": true}, "GRCI": {"before": "", "after": "", "changed": false}}`
- Claim IDs：`见 revision transition rows`
- FactLocks：`不适用`
- Claim transitions：`{"OPPORTUNITY_ADDED": 24, "ABSTAIN_TO_EXPRESSIBLE": 1, "UNCHANGED_ABSTAIN": 1}`
- 选择原因：MAX_LATER_EVIDENCE_LINK_COUNT
- 冻结文本：Not a text-generation case; it audits state and Claim semantics before/after later evidence.
- 来源：`artifacts/stage3b_bitemporal_epistemic_state_v1_1/knowledge_revision_events.jsonl`；`artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_metric_pairs.csv`；`artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_claim_transition_rows.csv`；`artifacts/stage7d_bitemporal_value_v1_1/stage7d_case_knowledge_revision_event_6b0d8288fd43937664e27e4e.md`

## 3. Case B (revision census)

- 日期：`2023-09-22`
- 空间：`1013300.0-1013310.0`
- Cell：`cell_59d7ded1be93617fff859fd7`
- Episode：`不适用`
- Evidence IDs：`doc_042ef22be43ba006975946e2_e0002`
- State IDs：`bitemporal_version_14c0d3c3c5bae0f959927e2b, bitemporal_version_89c9c8c5cc5c29a3ecc3eab1`
- Metrics：`{"RAI": {"before": "", "after": "", "changed": false}, "GRS": {"before": "", "after": "0.5416666666666666", "changed": true}, "GRCI": {"before": "", "after": "", "changed": false}}`
- Claim IDs：`见 revision transition rows`
- FactLocks：`不适用`
- Claim transitions：`{"OPPORTUNITY_ADDED": 8, "ABSTAIN_TO_EXPRESSIBLE": 1, "UNCHANGED_ABSTAIN": 1}`
- 选择原因：MAX_EXISTING_CLAIM_DECISION_SWITCH_COUNT
- 冻结文本：Not a text-generation case; it audits state and Claim semantics before/after later evidence.
- 来源：`artifacts/stage3b_bitemporal_epistemic_state_v1_1/knowledge_revision_events.jsonl`；`artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_metric_pairs.csv`；`artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_claim_transition_rows.csv`；`artifacts/stage7d_bitemporal_value_v1_1/stage7d_case_knowledge_revision_event_8aeca0de8248562abb07a638.md`

## 4. Case C (revision census)

- 日期：`2023-09-22`
- 空间：`1013270.0-1013280.0`
- Cell：`cell_a7a9faa90556b5f0054f0fd0`
- Episode：`不适用`
- Evidence IDs：`doc_042ef22be43ba006975946e2_e0001, doc_042ef22be43ba006975946e2_e0002`
- State IDs：`bitemporal_version_3b61ba040c33594ef18e9eca, bitemporal_version_b80fc9058f82768576705a0c`
- Metrics：`{"RAI": {"before": "", "after": "", "changed": false}, "GRS": {"before": "1.0", "after": "1.0", "changed": false}, "GRCI": {"before": "", "after": "", "changed": false}}`
- Claim IDs：`见 revision transition rows`
- FactLocks：`不适用`
- Claim transitions：`{"OPPORTUNITY_ADDED": 12, "UNCHANGED_EXPRESSIBLE": 8, "UNCHANGED_ABSTAIN": 2, "RESOLVED_SUPPORT_CHANGED": 1}`
- 选择原因：MAX_OBSERVED_OPPORTUNITY_ADDED_COUNT
- 冻结文本：Not a text-generation case; it audits state and Claim semantics before/after later evidence.
- 来源：`artifacts/stage3b_bitemporal_epistemic_state_v1_1/knowledge_revision_events.jsonl`；`artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_metric_pairs.csv`；`artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_claim_transition_rows.csv`；`artifacts/stage7d_bitemporal_value_v1_1/stage7d_case_knowledge_revision_event_9177a8cf2b831a3ad8fc81ec.md`

## 最终推荐

- **论文主案例**：Case A（2023-10-07）。它在同一任务中闭合 Episode、5 通道响应证据、HSP FORECAST、状态、三指标、10 个 FactLocks 与最终文本，并可用于对照检查 B0/B1 的因果与认识边界表述。
- **论文修订案例**：revision census Case A（2023-11-28）。三条后到 FORECAST 证据使前方 Cell 的 GRS 从不可用变为 0.625，新增 24 个 FORECAST geological opportunities，并使 1 条 FORWARD_GEOLOGICAL_ATTENTION 从 ABSTAIN 转为 EXPRESSIBLE。
