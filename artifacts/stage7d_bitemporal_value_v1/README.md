# Stage7D Bitemporal Value Experiment

This artifact is a deterministic single-variable ablation. `EXACT_AS_OF` uses
the knowledge version active at each frozen Stage7A task boundary;
`FINAL_HISTORY` uses the latest version for the same valid date and cell.

The final-history arm is not an unrestricted future-data dump. Valid time,
space, role, metrics, Claim Contract, and deterministic admissibility code are
what changes when later knowledge is used retrospectively as if it had been
known earlier.

The frozen 48-task benchmark produced a valid null result: every task's
knowledge boundary already selected the latest state version. Therefore no
affected-task case could be selected without changing the frozen sample. The
separate corpus-level descriptive audit still reports all 53 revision chains.

No LLM or external API is used. The 91-date corpus analysis is descriptive and
does not establish cross-project generalization.
