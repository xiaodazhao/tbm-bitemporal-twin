# Stage 2 Validation

Stage 2.1验证从Stage 1产物和地质输入构造三类输出：

- `response_evidence.json` 和 `response_evidence_summary.csv`
- `geological_evidence.json` 和 `geological_evidence_summary.csv`
- `applicability_assignments.json` 和多张适用性诊断表

运行示例：

```bash
python scripts/validate_stage2_evidence.py \
  --stage1-artifact-dir artifacts/stage1_validation \
  --geology-input <geology.csv-or-json> \
  --dates 2023-12-30,2023-12-28,2023-09-15 \
  --output-dir artifacts/stage21_validation
```

报告重点检查：

- ResponseEvidence是否只使用核心推进观测；
- FORECAST、OBSERVED、BACKGROUND、UNKNOWN是否被保留；
- `available_time` 未知数量；
- 空间范围未知数量；
- 未来证据泄漏数量必须为0；
- 证据级 `applicable_to_at_least_one_episode`、`qualified_for_at_least_one_episode`、`undetermined_for_all_episodes`、`not_applicable_to_all_episodes`、`mixed_applicability_results`；
- Assignment级 `evidence_type × epistemic_status × temporal_status × spatial_status × result` 矩阵；
- 硬排除 reason 分布；
- 适用性结果是否保持非布尔状态。

如果真实地质证据全部缺少可确认的 `available_time`，报告必须输出 `real_data_temporal_applicability_validation=NOT_EVALUABLE`。此时 `detected_future_leakage_count=0` 只说明未知时间证据没有被无条件使用，不构成历史时间适用性的实证验证。
