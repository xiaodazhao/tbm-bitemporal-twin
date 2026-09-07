# Final Research Handoff Bundle v1

这是论文写作和后续接手的唯一入口。目录内容来自冻结实现与 artifact 的只读汇总，不重跑实验，也不修改任何历史结果。

## 推荐阅读顺序

`00_PROJECT_OVERVIEW.md` → `01_TECHNICAL_PIPELINE.md` → `03_DATASET_AND_SYSTEM_SCALE.md` → `04_EXPERIMENT_MASTER_REGISTRY.csv` → `06_CLAIM_ADMISSIBILITY.md` → `07_BITEMPORAL_RESULTS.md` → `08_ABLATION_RESULTS.md` → `09_SENSITIVITY_RESULTS.md` → `11_SCIENTIFIC_BOUNDARIES.md` → `13_PAPER_RESULTS_CHAPTER_OUTLINE.md`。

## 论文只能引用的 canonical 文件

- 数字总索引：`14_RESULT_TRACEABILITY.csv`。
- 表格数据：`paper_tables/table_*.csv` 及各 README。
- 图数据：`paper_figures/figure_*.csv` 与 `PAPER_FIGURE_PLAN.md`。
- 方法公式：`02_METHOD_DEFINITION_REGISTRY.csv`，并以其中列出的源码/配置为最终依据。
- 废弃结果：`10_SUPERSEDED_RESULT_REGISTRY.csv`。其中任何 `must_not_use_in_paper=true` 的值不得引用。
- 科学边界：`11_SCIENTIFIC_BOUNDARIES.md`。

## 审计入口

`final_handoff_hard_check.csv` 必须全部 PASS；`SOURCE_INVENTORY.csv` 给出读取源及 SHA-256；`file_hashes.sha256` 校验本目录；`freeze_manifest.json` 记录数量和 Git 身份。
