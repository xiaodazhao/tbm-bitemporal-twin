# Paper Results Single Source of Truth

| Metric | Value | Expected | Match | Authoritative source |
|---|---:|---:|---|---|
| `evidence.plc_observations` | 328217 | 328217 | True | `artifacts/stage2_plc_operational_freeze_v2/normalized_observations/*.parquet` |
| `evidence.excavation_events` | 1119 | 1119 | True | `artifacts/stage2_plc_operational_freeze_v2/excavation_episodes.jsonl` |
| `evidence.mechanical` | 5595 | 5595 | True | `artifacts/stage2_plc_operational_freeze_v2/response_evidence.jsonl` |
| `evidence.geological_documents` | 223 | 223 | True | `artifacts/stage2_geology_v2_freeze_candidate/geological_documents.jsonl` |
| `evidence.geological_total` | 659 | 659 | True | `artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl` |
| `evidence.geological_observed` | 278 | 278 | True | `artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl` |
| `evidence.geological_forecast` | 381 | 381 | True | `artifacts/stage2_geology_v2_freeze_candidate/primary_geological_evidence.jsonl` |
| `evidence.source_spans` | 4713 | 4713 | True | `artifacts/stage2_geology_v2_freeze_candidate/source_spans.jsonl` |
| `state.cells` | 156 | 156 | True | `artifacts/stage3a_initial_epistemic_state_v1_1/construction_state_cells.jsonl` |
| `state.initial_versions` | 1322 | 1322 | True | `artifacts/stage3a_initial_epistemic_state_v1_1/initial_construction_state_versions.jsonl` |
| `state.total_bitemporal_versions` | 1375 | 1375 | True | `artifacts/stage3b_bitemporal_epistemic_state_v1_1/bitemporal_state_versions.jsonl` |
| `state.revision_events` | 53 | 53 | True | `artifacts/stage3b_bitemporal_epistemic_state_v1_1/knowledge_revision_events.jsonl` |
| `state.revision_dates` | 14 | None | True | `artifacts/stage3b_bitemporal_epistemic_state_v1_1/knowledge_revision_events.jsonl` |
| `state.revised_cells` | 51 | None | True | `artifacts/stage3b_bitemporal_epistemic_state_v1_1/knowledge_revision_events.jsonl` |
| `metric.rai_available` | 174 | 174 | True | `artifacts/stage4_bitemporal_state_metrics_v1_1/state_rai.jsonl` |
| `metric.grs_available` | 1211 | 1211 | True | `artifacts/stage4_bitemporal_state_metrics_v1_1/state_grs.jsonl` |
| `metric.grci_available` | 174 | 174 | True | `artifacts/stage4_bitemporal_state_metrics_v1_1/state_grci.jsonl` |
| `claim.total_opportunities` | 8679 | 8679 | True | `artifacts/stage5b_deterministic_claim_builder_v1/claim_opportunities.jsonl` |
| `claim.allow` | 6279 | 6279 | True | `artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl` |
| `claim.reject` | 2400 | 2400 | True | `artifacts/stage5b_deterministic_claim_builder_v1/claim_decisions.jsonl` |
| `revision.total_events` | 53 | None | True | `artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json` |
| `revision.rai_changed` | 0 | None | True | `artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json` |
| `revision.grs_changed` | 36 | None | True | `artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json` |
| `revision.grci_changed` | 1 | None | True | `artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json` |
| `revision.reject_to_allow_events` | 27 | None | True | `artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json` |
| `revision.opportunity_added` | 540 | None | True | `artifacts/stage7d_bitemporal_value_v1_1/stage7d_secondary_endpoints.json` |
| `revision.opportunity_added_forecast` | 504 | None | True | `artifacts/stage7d_bitemporal_value_v1_1/stage7d_secondary_endpoints.json` |
| `revision.opportunity_added_observed` | 36 | None | True | `artifacts/stage7d_bitemporal_value_v1_1/stage7d_secondary_endpoints.json` |
| `revision.opportunity_added_allow` | 454 | None | True | `artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_claim_transition_rows.csv` |
| `revision.opportunity_added_reject` | 86 | None | True | `artifacts/stage7d_bitemporal_value_v1_1/stage7d_revision_claim_transition_rows.csv` |
| `revision.any_claim_change_events` | 53 | None | True | `artifacts/stage7d_bitemporal_value_v1_1/stage7d_primary_endpoints.json` |
| `ablation.a3.strict_blocks` | 147 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a3.strict_valid` | 125 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a3.strict_mappings` | 828 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a3.strict_complete_tasks` | 32 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a3.strict_numeric_exact` | 149 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a3.strict_numeric_total` | 149 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a3.strict_numeric_drift` | 0 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a3.fence_valid` | 147 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a3.fence_mappings` | 989 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a3.fence_complete_tasks` | 45 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a3.fence_numeric_exact` | 164 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a3.fence_numeric_total` | 164 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a3.fence_numeric_drift` | 0 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a4.factlocks_used` | 848 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a4.factlocks_total` | 1022 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a4.numeric_used` | 162 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a4.numeric_total` | 171 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a4.numeric_exact` | 162 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a4.factlock_coverage` | 0.8297455968688845 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `ablation.a4.numeric_factlock_coverage` | 0.9473684210526315 | None | True | `artifacts/stage7e_ablation_execution_v1_1a_metadata_cleanup/stage7e_final_machine_result_summary.json` |
| `rq2.planned_tasks` | 48 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.execution_items` | 144 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.transport_successes` | 144 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.B0_final_texts` | 48 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.B1_final_texts` | 48 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.P_raw_plans` | 48 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.P_parse_valid` | 48 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.P_schema_valid` | 48 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.P_valid_plans` | 45 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.P_fail_closed` | 3 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.P_final_texts` | 45 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.P_post_audit_pass` | 45 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.B0_automatic_failures` | 2 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.B1_automatic_failures` | 0 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `rq2.P_automatic_failures` | 0 | None | True | `artifacts/stage7b_main_comparison_v1/run_summary.json or stage7c_main_auto_eval_v1_2/method_automatic_summary.csv` |
| `sensitivity.cell.5m.count` | 312 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.cell.5m.role_conflicts` | 0 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.cell.5m.point_deficiencies` | 0 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.cell.5m.interval_inconsistencies` | 0 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.cell.10m.count` | 156 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.cell.10m.role_conflicts` | 0 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.cell.10m.point_deficiencies` | 0 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.cell.10m.interval_inconsistencies` | 0 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.cell.20m.count` | 79 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.cell.20m.role_conflicts` | 90 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.cell.20m.point_deficiencies` | 23 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.cell.20m.interval_inconsistencies` | 76 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.n_min.20.rai_available` | 176 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.n_min.20.grci_available` | 176 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.n_min.30.rai_available` | 174 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.n_min.30.grci_available` | 174 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.n_min.40.rai_available` | 172 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.n_min.40.grci_available` | 172 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.n_min.20.reject_to_allow` | 4 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.n_min.40.allow_to_reject` | 4 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.lambda.2.claim_opportunities` | 8679 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.lambda.3.claim_opportunities` | 8679 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.lambda.4.claim_opportunities` | 8679 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.lambda.2.decision_migrations` | 0 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `sensitivity.lambda.4.decision_migrations` | 0 | None | True | `artifacts/stage7f_sensitivity_execution_v1_1_final_interpretation/stage7f_final_machine_summary.json` |
| `claim.reject_reason.CONTEXT_ONLY_ROLE` | 880 | None | True | `artifacts/stage5b_deterministic_claim_builder_v1/claim_abstentions.jsonl` |
| `claim.reject_reason.REQUIRED_EPISTEMIC_STATUS_MISSING` | 105 | None | True | `artifacts/stage5b_deterministic_claim_builder_v1/claim_abstentions.jsonl` |
| `claim.reject_reason.REQUIRED_METRIC_UNAVAILABLE` | 32 | None | True | `artifacts/stage5b_deterministic_claim_builder_v1/claim_abstentions.jsonl` |
| `claim.reject_reason.STATE_ROLE_NOT_ALLOWED` | 305 | None | True | `artifacts/stage5b_deterministic_claim_builder_v1/claim_abstentions.jsonl` |
| `claim.reject_reason.UNKNOWN_SOURCE_VALUE` | 1078 | None | True | `artifacts/stage5b_deterministic_claim_builder_v1/claim_abstentions.jsonl` |
