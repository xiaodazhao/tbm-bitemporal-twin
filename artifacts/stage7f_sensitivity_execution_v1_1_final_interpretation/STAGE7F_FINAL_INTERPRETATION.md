# Stage7F Final Machine-Experiment Interpretation

## Spatial resolution

The 5 m versus 10 m comparison is the primary clean resolution sensitivity analysis. Metric rank patterns are broadly preserved, while Claim opportunity density and expressibility proportions remain resolution-dependent.

The 20 m arm completed deterministically but crossed the representation-validity boundary of the current spatial state model. Individual cells span daily-review, forward-attention, or local-background scopes, yielding 90 role conflicts, 23 point undercoverage cases, and 76 interval overlap mismatches. It is retained as a coarse-resolution stress test, not an interchangeable valid parameterization. Its per-100 m results use the actual 14,180 m coarse-cell exposure and are not an equal-spatial-support density comparison with the 13,220 m 5 m/10 m exposures.

The sensitivity adapter did not change cell construction, evidence values, metric formulas, or Claim rules. It only allowed native resolution-related quality failures to be recorded while the deterministic arm continued. Therefore the 20 m native Stage3A quality gate must not be described as passing.

中文边界：20 m 已越过当前空间状态表示的有效边界，保留为粗分辨率压力测试；5 m 与 10 m 才是主要的干净分辨率敏感性比较。

## RAI history sufficiency

The 20/30/40-observation arms have identical values on jointly available metric summaries. The change is concentrated at the availability boundary: 20 observations produce four ABSTAIN-to-EXPRESSIBLE transitions, while 40 produce four EXPRESSIBLE-to-ABSTAIN transitions. This is limited boundary sensitivity.

## RAI saturation scaling

The 2/3/4 robust-z arms change RAI and GRCI magnitudes as expected while preserving high rank consistency. Claim decisions do not transition. The stale `min_raw_deviation_divided_by_3` label is inherited metadata; the authoritative execution parameter is `rai.saturation_robust_z` as consumed by the implementation.

## Interpretation rule

No automatic robust/not-robust threshold, best parameter, or p-value claim is made. History sufficiency shows limited sensitivity; saturation is value-sensitive but decision-stable; finer 5 m resolution is broadly consistent; coarse 20 m resolution reaches the representation-validity boundary.
