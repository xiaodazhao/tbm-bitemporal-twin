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

当前仓库主线已冻结到 Stage 6A：从原始PLC CSV建立 `SourceAsset`、YAML驱动的 `ChannelCatalog`、标准化PLC观测、质量诊断、透明 `OperationPhase` 弱标签、PLC-inferred `ExcavationEpisode` 和质量感知 `SpatialFootprint`；随后冻结机械响应证据、规则化地质证据，并给出地质证据对91天PLC日期范围的非布尔适用性判断；再生成91天日终初始认识状态、10m Cell索引和地质/机械证据到Cell的可追溯连接；基于知识可用日期建立双时间认识状态修订链；生成非概率性的 RAI、GRS 和 GRCI 状态指标；冻结 Stage5A v1.1 Typed Claim Schema 与 Claim Contract；由 Stage5B 确定性批量物化 `ClaimOpportunity`、`ClaimProposal`、`ClaimDecision`、`TypedEngineeringClaim` 和 `ClaimAbstention`；Stage5C 冻结批量 Claim expressibility / abstention 分析；Stage6A 冻结将 EXPRESSIBLE `TypedEngineeringClaim` 投影为 deterministic FactLock，并生成受控 Evidence Pack 与 machine-readable Rendering Contract。

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
→ Stage 5C Claim Expressibility Analysis v1
→ Stage 6A Deterministic Fact Lock / Controlled Evidence Pack v1
```

## 当前不做

本阶段不实现日报、LLM、Prompt、API、前端、数据库服务或自然语言Claim生成。机械响应只用于施工过程弱标签、状态连接和非概率指标，不被解释为地质原因。
Stage6A 只生成结构化 FactLock、Controlled Evidence Pack 和 Rendering Contract；它不调用 LLM、不生成自然语言、不进行实验解释。Stage6B 才会研究受控 Claim realization。

## 目录结构与文件职责

```text
tbm-bitemporal-twin/
├─ README.md                         # GitHub主页说明：研究目标、冻结链路、命令和目录结构
├─ pyproject.toml                    # Python项目元数据、依赖、ruff/mypy/pytest配置
├─ AGENTS.md                         # Codex协作规则：研究边界、测试要求、禁止事项
├─ .env.example                      # 本地环境变量示例；不包含真实密钥
├─ .gitignore                        # 忽略本机缓存、真实数据、artifacts等大型生成产物
│
├─ configs/                          # ★ 方法配置与合同，不写入业务结果，只驱动构建
│  ├─ plc_channels.yaml              # PLC字段目录和单位/语义审计入口
│  ├─ episode_detection.yaml         # OperationPhase与ExcavationEpisode识别参数
│  ├─ response_evidence.yaml         # ResponseEvidence通道选择、质量和聚合配置
│  ├─ geology_sources.yaml           # 地质PDF/证据来源治理配置
│  ├─ evidence_applicability.yaml    # EvidenceApplicability空间/时间/角色规则
│  ├─ construction_state.yaml        # Stage3 10m Cell、日期窗口和状态构建配置
│  ├─ metric_foundation.yaml         # Stage4A1机械响应baseline和偏离组件配置
│  ├─ operational_measurement_regime_review.yaml # 机械通道制度、可用性和排除规则
│  ├─ geological_attention_dimension_contract.yaml # GRS地质关注维度合同
│  ├─ geological_attention_mapping_v1.yaml        # 44项地质值到ordinal attention的人工冻结映射
│  └─ state_metric_definition_v1.yaml             # RAI/GRS/GRCI正式指标定义合同
│
├─ scripts/                          # ★ 可执行入口；每个Stage的正式构建都从这里启动
│  ├─ audit_channels.py              # Stage1 PLC字段审计
│  ├─ normalize_plc.py               # 原始PLC CSV标准化为时间序列观测
│  ├─ build_episodes.py              # 从标准化PLC构建OperationPhase和ExcavationEpisode
│  ├─ build_response_evidence.py     # 早期ResponseEvidence构建入口
│  ├─ normalize_geological_evidence.py # 早期地质证据标准化入口
│  ├─ validate_stage1_real_data.py   # 真实PLC三日/多日验证与Episode复核
│  ├─ validate_stage2_evidence.py    # Stage2 Evidence治理验证
│  ├─ validate_stage2_raw_geology.py # 地质PDF解析和证据冻结审计入口
│  ├─ build_stage2e_plc_operational_freeze.py # 91天PLC Operational Evidence冻结
│  ├─ run_stage2d_applicability_v2_1.py       # Applicability V2.1正式重建入口
│  ├─ build_stage3a_initial_state.py          # Stage3A初始认识状态与Cell Link冻结
│  ├─ build_stage3b_bitemporal_state.py       # Stage3B按knowledge time修订双时间状态
│  ├─ build_stage4a1_metric_foundation.py     # Stage4A1 baseline与response deviation基础
│  ├─ build_stage4a1_1_metric_method_freeze.py # Stage4A1.1测量制度和指标合同冻结
│  └─ build_stage4a2_bitemporal_state_metrics.py # Stage4正式RAI/GRS/GRCI生成与审计
│
├─ src/tbm_twin/                     # ★ 研究型Python包主体
│  ├─ assets/                        # SourceAsset、文件hash、输入资产登记
│  ├─ channels/                      # PLC ChannelCatalog、字段解析和语义解析
│  ├─ timeseries/                    # PLC读取、时间标准化、观测质量诊断
│  ├─ process/                       # OperationPhase弱标签、ExcavationEpisode模型和构建
│  ├─ trajectory/                    # SpatialFootprint与里程轨迹质量估计
│  ├─ geology/                       # 地质文档模型、里程/时间解析、PDF证据读取
│  │  └─ table_parser_v2/            # pdfplumber表格Parser V2：FaceSketch/HSP/TSP专用解析
│  ├─ evidence/                      # Geological/Response Evidence模型、质量和Applicability规则
│  ├─ operational_freeze/            # Stage2E PLC Operational Evidence冻结模型、构建和校验
│  ├─ state/                         # Stage3A Cell网格、DailyState、Evidence到Cell连接
│  ├─ bitemporal/                    # Stage3B knowledge-time修订链、as-of查询和快照物化
│  ├─ metrics/                       # Stage4 RAI、GRS、GRCI、baseline、mapping和方法合同
│  └─ validation/                    # 验证配置、诊断汇总、可视化和Stage级审计辅助
│
├─ tests/                            # ★ 单元测试和集成测试；每个冻结Stage都有回归保护
│  ├─ unit/                          # 模型、ID、时间语义、空间规则、指标公式等细粒度测试
│  ├─ integration/                   # Stage2E/Stage3A/Stage3B/Stage4真实冻结链路测试
│  ├─ fixtures/                      # 小型PLC、地质PDF和构造数据fixture
│  └─ manual_gold/                   # table_parser_v2人工Gold；禁止由Parser自动生成
│
├─ docs/                             # 方法说明和冻结路线文档
│  ├─ architecture.md                # 总体架构：证据→状态→双时间→指标→未来Claim边界
│  ├─ STAGE2_FROZEN_PIPELINE.md      # Stage2冻结链路和Stage3/4正式读取路径
│  ├─ evidence_applicability.md      # Applicability角色、时间门和空间门说明
│  ├─ response_evidence.md           # 机械响应证据边界：不直接解释地质原因
│  ├─ geological_evidence.md         # 地质证据结构化与来源约束
│  ├─ stage1_real_data_validation.md # Stage1真实PLC验证方法
│  ├─ stage2_validation.md           # Stage2验证记录
│  ├─ migration_notes.md             # 历史迁移记录
│  └─ ARCHIVE_INDEX.md               # 被替代/归档产物索引
│
├─ artifacts/                        # 本地生成产物目录，默认被Git忽略，不在GitHub源码中展开
│  ├─ stage2_geology_v2_freeze_candidate/       # Stage2地质Evidence冻结快照
│  ├─ stage2_plc_operational_freeze_v2/         # Stage2E PLC Operational Evidence冻结
│  ├─ stage2d_applicability_v2_1/               # Applicability V2.1冻结输出
│  ├─ stage3a_initial_epistemic_state_v1_1/     # Stage3A初始状态冻结
│  ├─ stage3b_bitemporal_epistemic_state_v1_1/  # Stage3B双时间状态冻结
│  └─ stage4_bitemporal_state_metrics_v1_1/     # Stage4正式RAI/GRS/GRCI冻结输出
│
└─ _archive/                         # 历史说明和人工审查包；不作为正式运行入口
   ├─ artifacts_stage2_history/      # Stage2历史产物说明
   └─ review_packages/               # 早期人工审查ZIP留档
```

主链路只认正式冻结路径：`Stage 2 Evidence / Stage2E Operational Freeze / Applicability V2.1 → Stage 3A → Stage 3B → Stage 4`。`artifacts/` 中的正式快照保留在本地用于复现和审计，但不随GitHub源码提交；GitHub仓库主要保存可复现这些快照的源码、配置、测试和文档。

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

Stage 6A Deterministic Fact Lock & Controlled Evidence Pack v1: FROZEN

Stage 6B Controlled Claim Realization / LLM Realization v1: FROZEN

Stage 7A Experimental Protocol / Held-Out Benchmark v1.3: FROZEN

Stage 7B Controlled Model Evaluation: NEXT
