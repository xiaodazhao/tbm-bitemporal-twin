# GRS Mapping One-Step Sensitivity

This is an offline deterministic audit. It does not modify frozen outputs.
Aliases sharing dimension, rank, scale, and ordering basis move together by
one legal rank. Null and unmappable values are not perturbed.

- Perturbation arms: **38**
- Arms with numerical GRS change: **38**
- Maximum changed GRS states in one arm: **879**
- Maximum absolute GRS delta: **0.333333333333**
- Arms with claim-decision migration: **0**
- Total decision migrations across all arms: **0**
- Arms changing a frozen revision conclusion: **2**

Numerical sensitivity is expected because GRS is ordinal-value based. Claim-level
stability only shows that these bounded local perturbations do not cross current
admissibility boundaries; it does not scientifically validate the mapping.
Two arms each change one event's binary GRS-revision classification. See
the same event from changed to unchanged (36/53 to 35/53). See
`grs_mapping_sensitivity_revision_audit.csv`; Claim decisions remain unchanged.
