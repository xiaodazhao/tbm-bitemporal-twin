# Stage7B Main Comparison v1

Stage7B executed the frozen Stage7A v1.3 held-out benchmark with three methods.
It does not perform human evaluation, significance testing, prompt tuning, or Stage7C.

## Frozen Inputs

- Stage7A manifest hash: `e9ef8e3f9bd25f345f89f79dc753040e3bfc1f95e562902aea625a8e50334f6f`
- Stage7A as-of binding hash: `92bdea500aef7bedb27e6133e92ec058f03ccfd48810e84aed11388838d12bc4`
- Product contract hash: `ad599756f428514cf731bb982ecccf21b0705e14579ebf64095524a674ecc98d`

## Provider

- Provider: `deepseek`
- Model: `deepseek-v4-flash`
- Temperature: `0.0`
- Top-p: `1.0`
- Reasoning effort: `none`
- Max retries: `0`

## Execution Summary

- Execution ID: `stage7b_main_execution_3ae0f791811a2e711cb9f488`
- Execution protocol hash: `19c1bb629765198316c44951bddfbdf7547f017da6793c698c6f98f376260cbf`
- Execution items: `144`
- Benchmark tasks: `48`
- Real API attempts: `144`
- Transport successes: `144`
- Transport failures: `0`
- B0 outputs: `48`
- B1 outputs: `48`
- P raw plans: `48`
- P valid/composed outputs: `45`
- P post-audit failures: `0`

## Notes

The proposed method composes only plans that pass deterministic schema and domain validation.
Invalid plans are preserved as raw model outputs and are not repaired, retried, or composed.
