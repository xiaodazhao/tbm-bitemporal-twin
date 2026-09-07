# 论文图数据计划

## Figure 1：Claim Gate 输出分布

使用 `figure_claim_gate.csv` 绘制 EXPRESSIBLE 与各 ABSTAIN reason 的堆叠条形图。分母固定为 8679 opportunities；不要把 ABSTAIN 标为错误率。

## Figure 2：双时间修订效应

使用 `Figure_Bitemporal_Revision_Data.csv` 绘制 RAI/GRS/GRCI change incidence、ABSTAIN→EXPRESSIBLE，以及 540/454/86 的新增机会计数。48-task null alignment 应作为独立注释，不与 53-event census 混分母；新增机会是 transition-row 计数，不绘制为 540/975 的主结果百分比。

## Figure 3：主实验流程与确定性端点

使用 `Figure_Main_Experiment_Data.csv` 只绘制 48 planned tasks 的输出可用性、P fail-closed 和 P post-audit pass。人工语义 endpoints 用灰色 `DEFERRED_TO_HUMAN` 标识，不能补零，也不能从执行计数推断语义优越性。

## Figure 4：消融覆盖

使用 `figure_ablation.csv` 展示 A3 strict/secondary 与 A4 trace/numeric coverage。A1 用 `NOT_EXECUTABLE` 单独标记，旧 numeric drift 149 不进入图。

## Figure 5：敏感性与有效性边界

使用 `figure_sensitivity.csv` 分三面板展示 Cell size、history 和 saturation。20m 必须用 stress-test 样式并标注 90/23/76 质量问题；不要用一条“robust”折线概括全部 arms。
