# Stage7D v1.1 Revision-Census Report

## Population

- Revision events: 53
- Valid dates: 14
- Revised cells: 51
- Event-evidence links: 72
- Unique later evidence: 34

## Primary endpoints

- RAI-sensitive events: 0 / 53
- GRS-sensitive events: 36 / 53
- GRCI-sensitive events: 1 / 53
- Existing-Claim decision-switch events: 27 / 53
- Opportunity-created events: 53 / 53
- Any Claim semantic-change events: 53 / 53
- Observed-opportunity-created events: 9 / 53

## Claim row transitions

```json
{
  "ABSTAIN_TO_EXPRESSIBLE": 27,
  "CLAIM_VALUE_CHANGED": 10,
  "OPPORTUNITY_ADDED": 540,
  "RESOLVED_SUPPORT_CHANGED": 26,
  "UNCHANGED_ABSTAIN": 84,
  "UNCHANGED_EXPRESSIBLE": 288
}
```

## Interpretation

The results quantify sensitivity of structured knowledge and Claim
admissibility to knowledge time. They do not identify errors, hallucinations,
hazard probabilities, or generated-text failures. POST knowledge is legitimate
later knowledge; bitemporal storage preserves the earlier PRE state as well.

Single project; 91 PLC-monitored dates; 88 dates with materialized cell state.
API calls: 0. LLM calls: 0.
