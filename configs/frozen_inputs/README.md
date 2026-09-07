# Frozen protocol inputs

This directory contains only the minimal immutable inputs needed to rebuild the
current Stage 7 results after superseded artifact directories were archived.

- `stage7a_v1_main_benchmark_manifest.json` preserves the original 48-task
  benchmark selection consumed by the authoritative Stage 7A.3 builder.
- `stage7c_v1_failed_statement_baseline.csv` contains only the 127 failed rows
  needed to reproduce the v1 correction audit.
- `stage7c_v1_1_failed_statement_baseline.csv` contains only the eight failed
  rows needed to reproduce the v1.1 correction audit.
- `stage7c_human_v1_workload_baseline.json` preserves the single aggregate
  needed to audit the v1.1 packet's context reduction.
- `stage7e_v1_prompts/` preserves the eight small prompt templates required by
  the Stage 7E v1-to-v1.2 protocol regression tests.
- `stage7e_v1_a2_architectural_abstention_targets.csv`,
  `stage7e_v1_a4_request_message_sizes.json`, and
  `stage7e_v1_file_hashes.sha256` preserve only the v1 identities consumed by
  the authoritative v1.2 protocol comparison.
- `stage7e_v1_1_correction/` retains the two aggregate correction summaries
  consumed by the final Stage 7E metadata builder, plus their original hash
  manifest. Row-level intermediate audits remain externally archived.

These files are frozen comparison inputs, not active alternative results. The
complete superseded artifact directories are intentionally excluded from the
canonical repository tree.
