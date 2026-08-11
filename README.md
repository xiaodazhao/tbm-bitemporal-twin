# TBM Bitemporal Twin

Formal post-Stage-2 route:

```text
Stage 2 Geology V2 Freeze
+ Applicability V2.1
+ PLC Operational Evidence Freeze V2
-> Stage 3A Initial Construction State v1.1
-> Stage 3B Bitemporal Epistemic State v1.1
-> Stage 4 Bitemporal State Metrics v1.1
-> Stage 5A Typed Claim Contract v1.1
-> Stage 5B Deterministic Claim Builder v1
```

Stage 3 must read only:

```text
artifacts/stage2_geology_v2_freeze_candidate/
artifacts/stage2d_applicability_v2_1/
artifacts/stage2_plc_operational_freeze_v2/
artifacts/stage3a_initial_epistemic_state_v1_1/
artifacts/stage3b_bitemporal_epistemic_state_v1_1/
```

Stage3B must read only `artifacts/stage3a_initial_epistemic_state_v1_1/` for
Stage3A state input. Do not use `artifacts/stage3a_initial_epistemic_state_v1/`
because it is `SUPERSEDED_BY_STAGE3A_V1_1` and `POINT_RESPONSE_INCOMPLETE`. Do
not use `artifacts/stage3a_initial_epistemic_state_v1_1_candidate/` as a formal
input.

Post-Stage3B metrics and Claim layers must read only
`artifacts/stage3b_bitemporal_epistemic_state_v1_1/`. Do not use
`artifacts/stage3b_bitemporal_epistemic_state_v1_candidate/` as a formal input;
it is retained only for promotion audit.

Stage5 and later layers must read Stage4 metrics only from:

```text
artifacts/stage4_bitemporal_state_metrics_v1_1/
```

Stage4 RAI, GRS and GRCI are non-probabilistic attention metrics. They are not
risk probabilities, hazard probabilities, causal estimates, or Typed Claims.

See [docs/STAGE2_FROZEN_PIPELINE.md](docs/STAGE2_FROZEN_PIPELINE.md) and
[docs/ARCHIVE_INDEX.md](docs/ARCHIVE_INDEX.md).

本项目研究TBM动态施工证据如何形成事件对齐、可追溯和可版本化的施工状态，并为后续来源约束的工程Claim推理提供可靠事实对象。

## 研究问题

PLC数据是不规则采样的，地质证据也会动态到达。本项目的长期问题是：如何把来源、时间、空间和认识性质不同的证据组织为可追溯状态对象，并在未来判断工程Claim是否被允许成立。

当前仓库主线冻结到 Stage 5B：从原始PLC CSV建立 `SourceAsset`、YAML驱动的 `ChannelCatalog`、标准化PLC观测、质量诊断、透明 `OperationPhase` 弱标签、PLC-inferred `ExcavationEpisode` 和质量感知 `SpatialFootprint`；随后冻结机械响应证据、规则化地质证据，并给出地质证据对91天PLC日期范围的非布尔适用性判断；再生成91天日终初始认识状态、10m Cell索引和地质/机械证据到Cell的可追溯连接；基于知识可用日期建立双时间认识状态修订链；生成非概率性的 RAI、GRS 和 GRCI 状态指标；冻结 Stage5A v1.1 Typed Claim Schema 与 Claim Contract；最后由 Stage5B 确定性批量物化 `ClaimOpportunity`、`ClaimProposal`、`ClaimDecision`、`TypedEngineeringClaim` 和 `ClaimAbstention`。

```text
Raw PLC CSV
→ SourceAsset
→ ChannelCatalog
→ Normalized PLC Observation
→ PLCQualityReport
→ OperationPhase
→ ExcavationEpisode
→ quality-aware SpatialFootprint
→ ResponseEvidence / GeologicalEvidence
→ EvidenceApplicabilityAssignment
→ PLC Operational Evidence Freeze
→ Stage 3A Initial Construction State v1.1
→ Stage 3B Bitemporal Epistemic State v1.1
→ Stage 4 Bitemporal State Metrics v1.1
→ Stage 5A Typed Claim Contract v1.1
→ Stage 5B Deterministic Claim Builder v1
```

## 当前不做

本阶段不实现日报、LLM、Prompt、API、前端、数据库服务、Evidence Pack或自然语言Claim生成。机械响应只用于施工过程弱标签、状态连接和非概率指标，不被解释为地质原因。
Stage5B 已经确定性批量物化 `ClaimOpportunity`、`ClaimProposal`、`ClaimDecision`、`TypedEngineeringClaim` 和 `ClaimAbstention`，但仍然不生成 Evidence Pack、不调用 LLM、不生成自然语言、不进行实验解释。

## 安装

```bash
pip install -e ".[dev]"
```

## 命令行示例

```bash
python scripts/audit_channels.py --input tests/fixtures/sample_plc.csv
```

```bash
python scripts/normalize_plc.py \
  --input tests/fixtures/sample_plc.csv \
  --output artifacts/sample_plc.parquet
```

```bash
python scripts/build_episodes.py \
  --input artifacts/sample_plc.parquet \
  --output artifacts/episodes.json
```

```bash
python scripts/build_response_evidence.py \
  --normalized-plc artifacts/sample_plc.parquet \
  --episodes artifacts/episodes.json \
  --output artifacts/response_evidence.json
```

```bash
python scripts/normalize_geological_evidence.py \
  --input <geology.csv-or-json> \
  --output artifacts/geological_evidence.json
```

```bash
python scripts/build_stage2e_plc_operational_freeze.py \
  --reconstruction-time 2026-07-30T14:30:00+08:00
```

```bash
python scripts/run_stage2d_applicability_v2_1.py \
  --generated-at 2026-07-30T14:30:00+08:00
```

```bash
python scripts/build_stage3a_initial_state.py \
  --generated-at 2026-07-30T14:30:00+08:00
```

```bash
python scripts/build_stage4a2_bitemporal_state_metrics.py \
  --generated-at 2026-08-09T12:00:00+08:00
```

## 测试

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest -q
```

## Real-data Validation

Stage 1.5 可对真实PLC数据生成字段审计、质量诊断、Episode复核CSV/PNG和跨日期汇总：

```bash
python scripts/validate_stage1_real_data.py \
  --plc-data-dir <PLC目录> \
  --dates 2023-12-30,2023-12-28,2023-09-15 \
  --artifact-dir artifacts/stage1_validation
```

PLC-informed proxy reference复核完成后，可用Episode时间区间IoU评价系统Episode：

```bash
python scripts/evaluate_episodes.py \
  --predictions artifacts/stage1_validation/episode_summary.csv \
  --annotations experiments/episode_annotation/episode_proxy_reference.csv \
  --output-dir artifacts/episode_evaluation
```

该评价不会输出采样点分类准确率，也不声称现场真实施工事件准确率。

## 领域边界

`ExcavationEpisode` 是PLC-inferred施工过程对象；日期只是查询和聚合条件。未来10m Cell只作为空间索引，不是当前冻结对象。`SpatialFootprint` 是质量感知空间范围估计，不是真实轨迹恢复。未确认单位的通道会保留并诊断，但不得用于物理量解释。`ResponseEvidence` 不解释地质原因。离线 `reconstructed_at` 不是历史 `ingestion_time`。所有派生对象保存来源引用、方法版本、质量等级、原因码和警告。

## Roadmap

Stage 2 Evidence Governance: FROZEN

Stage 3A Initial Epistemic State: FROZEN

Stage 3B Bitemporal Epistemic State: FROZEN

Stage 4 Bitemporal State Metrics: FROZEN

Stage 5A Typed Claim Schema / Claim Contract v1.1: FROZEN

Stage 5B Deterministic Claim Builder v1: FROZEN

Stage 5C Batch Claim Expressibility & Abstention Analysis v1: FROZEN

Stage 6 Controlled Claim Realization / Fact Lock / Evidence Pack / LLM Realization: NEXT

Stage 7 Experiments / Evaluation: NOT COMPLETED
