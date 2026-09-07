# Canonical Research Path

This repository exposes one active research route. A directory is listed here
only when it is a formal input, a final result, an active human-evaluation
packet, or a compact paper/audit index.

## Formal computational route

| Stage | Authoritative local artifact |
| --- | --- |
| Geological evidence | `artifacts/stage2_geology_v2_freeze_candidate/` |
| Operational evidence | `artifacts/stage2_plc_operational_freeze_v2/` |
| Evidence applicability | `artifacts/stage2d_applicability_v2_1/` |
| Initial construction state | `artifacts/stage3a_initial_epistemic_state_v1_1/` |
| Bitemporal state | `artifacts/stage3b_bitemporal_epistemic_state_v1_1/` |
| Metric foundation | `artifacts/stage4a1_metric_foundation_v1/` |
| Metric method contract | `artifacts/stage4a1_1_metric_method_freeze_v1/` |
| State metrics | `artifacts/stage4_bitemporal_state_metrics_v1_1/` |
| Typed Claim contract | `artifacts/stage5a_typed_claim_contract_v1_1/` |
| Deterministic Claim universe | `artifacts/stage5b_deterministic_claim_builder_v1/` |
| Expressibility analysis | `artifacts/stage5c_claim_expressibility_analysis_v1/` |
| FactLock and evidence pack | `artifacts/stage6a_fact_lock_evidence_pack_v1/` |
| Controlled realization | `artifacts/stage6b_controlled_realization_v1/` |

## Formal experimental route

| Stage | Authoritative artifact | Role |
| --- | --- | --- |
| Stage 7A | `artifacts/stage7a_experimental_protocol_v1_3/` | Held-out protocol and exact as-of binding |
| Stage 7B | `artifacts/stage7b_main_comparison_v1/` | Three-method real-model execution |
| Stage 7C automatic | `artifacts/stage7c_main_auto_eval_v1_2/` | Final deterministic boundary evaluation |
| Stage 7C human | `artifacts/stage7c_human_eval_packet_v1_1/` | Active blinded packet; scoring pending |
| Stage 7D diagnostic | `artifacts/stage7d_bitemporal_value_v1/` | Main-benchmark overlap diagnostic |
| Stage 7D census | `artifacts/stage7d_bitemporal_value_v1_1/` | Full 53-event revision census |
| Stage 7D interpretation | `artifacts/stage7d_bitemporal_value_v1_1a_correction/` | Final added-opportunity interpretation |
| Stage 7E protocol | `artifacts/stage7e_ablation_protocol_v1_2/` | Final executable ablation definition |
| Stage 7E execution | `artifacts/stage7e_ablation_execution_v1/` | Frozen raw model responses; corrected derived values must not be cited |
| Stage 7E result | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/` | Authoritative machine summary |
| Stage 7F protocol | `artifacts/stage7f_sensitivity_protocol_v1_1/` | Corrected sensitivity contract |
| Stage 7F result | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/` | Authoritative validity-boundary interpretation |

## Paper and audit entry points

- `artifacts/final_research_handoff_v1/`: compact cross-stage result index.
- `paper_writing_evidence_bundle_v1_1/`: current manuscript-facing evidence bundle.
- `paper_artifacts/`: paper-facing result manifest.
- `audit/`: final technical reproducibility checks.
- `supplementary/`: frozen geological mapping supplementary material.

## Repository and data boundary

The ordinary GitHub repository stores source code, configuration, tests,
documentation, and selected compact frozen outputs. Large local artifacts and
copyright-sensitive or paid inputs are not duplicated blindly into Git. Their
identity is maintained by freeze manifests and SHA-256 inventories. Review ZIPs
and superseded candidates are not active research inputs.

Minimal frozen comparison inputs under `configs/frozen_inputs/` and the three
Stage 7F pairwise-statistic tables are retained only where the final builders or
paper traceability registry depends on them. They are not parallel result sets.

The local recovery archive is documented in `docs/ARCHIVE_INDEX.md`. Nothing in
that archive may be used by the formal pipeline unless it is deliberately
promoted through a new reviewed method version.
