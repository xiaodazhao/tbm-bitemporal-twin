# TBM Bitemporal Twin

Formal post-Stage-2 route:

```text
Stage 2 Geology V2 Freeze
-> Applicability V2
-> Stage 3 ConstructionStateVersion
```

Stage 3 must read only:

```text
artifacts/stage2_geology_v2_freeze_candidate/
artifacts/stage2d_applicability_v2/
```

See [docs/STAGE2_FROZEN_PIPELINE.md](docs/STAGE2_FROZEN_PIPELINE.md) and
[docs/ARCHIVE_INDEX.md](docs/ARCHIVE_INDEX.md).

本项目研究TBM动态施工证据如何形成事件对齐、可追溯和可版本化的施工状态，并为后续来源约束的工程Claim推理提供可靠事实对象。

## 研究问题

PLC数据是不规则采样的，地质证据也会动态到达。本项目的长期问题是：如何把来源、时间、空间和认识性质不同的证据组织为可追溯状态对象，并在未来判断工程Claim是否被允许成立。

当前仓库实现到 Stage 2：从原始PLC CSV建立 `SourceAsset`、YAML驱动的 `ChannelCatalog`、标准化PLC观测、质量诊断、透明 `OperationPhase` 弱标签、`ExcavationEpisode` 和质量感知 `SpatialFootprint`；随后在Episode上构造机械响应证据、规则化地质证据，并给出证据对Episode的非布尔适用性判断。

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
```

## 当前不做

本阶段不实现日报、LLM、Prompt、API、前端、数据库服务、固定10 m Cell、GRCI/RAI/GRS、Evidence Pack、双时间仓库或Claim推理。机械响应只用于施工过程弱标签，不被解释为地质原因。

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

`ExcavationEpisode` 是主要施工过程对象；日期只是查询和聚合条件。`SpatialFootprint` 是质量感知空间范围估计，不是真实轨迹恢复。未确认单位的通道会保留并诊断，但不得用于物理量解释。所有派生对象保存来源引用、方法版本、质量等级、原因码和警告。

## Roadmap

Stage 2: ResponseEvidence, GeologicalEvidence, EvidenceApplicability（已实现到研究验证）

Stage 3: EvidenceApplicability and bitemporal state versioning（未实现）

Stage 4: Typed ClaimContract and ClaimAssessment（未实现）

Stage 5: state evolution and provenance analysis（未实现）
