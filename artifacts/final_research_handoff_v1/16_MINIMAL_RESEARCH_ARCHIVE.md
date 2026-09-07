# 最小研究归档集合

未来若清理工作区，必须先完成离线校验并保留以下集合：

1. **Git 身份**：完整 repository history、所有 frozen tags、最终 handoff tag；至少保留一份可校验的 bare mirror。
2. **实现**：`src/`、`scripts/`、`configs/`、`tests/`、`pyproject.toml` 和 lock file。
3. **论文证据索引**：整个 `artifacts/final_research_handoff_v1/`，包括 traceability、superseded registry、paper tables/figures 与 hashes。
4. **冻结核心成果**：Stage2 geology/PLC/applicability，Stage3A/3B，Stage4，Stage5A/B/C，Stage6A/B，Stage7A-F 的正式 manifest、summary、hard-check、hash 文件。
5. **不可重建原始资料**：PLC 原始 CSV 与地质 PDF。因体积和版权可不进入 Git，但必须外部加密归档并保存 SHA-256、目录清单、访问说明和至少两份副本。
6. **真实模型原始响应**：Stage6B smoke、Stage7B main、Stage7E ablation 的 raw response 是付费调用的实验原始记录，必须保留。建议 Git LFS 或外部只读归档，不能只保留解析后的文本。
7. **环境**：lock file、Python 版本、pdfplumber/PyMuPDF/SDK 版本以及 provider/model/protocol identity；API key 永不归档。

可通过 Git 历史保留但不必长期放在当前 worktree 的，是已被正式目录替代的 candidate 与旧 schema。review ZIP、cache 和可重建虚拟环境在人工核验后可清理。任何删除都必须依据 `15_REPOSITORY_RETENTION_PLAN.csv` 另行执行；本轮没有删除文件。
