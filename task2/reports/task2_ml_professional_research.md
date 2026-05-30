# Task 2 ML Research

This note records the more serious ML pass after the rule-based hybrid.

## Why ML Was Tested

The public research and Kaggle-style lessons suggested several useful directions:

- temporal validation instead of random splits;
- optimize the actual markout metric, not classification accuracy;
- use microstructure features: returns, order-flow pressure, spread, imbalance and notional;
- keep thresholds fixed from train when evaluating validation;
- prefer simple robust rankers before trying heavy deep models.

For this task, ML is used as a trade-quality ranker:

```text
higher score = more likely to keep the maker fill
```

## Protocol

Train period:

```text
2025-12-01 -> 2026-01-31
```

Validation period:

```text
2026-02-01 -> 2026-02-28
```

Models:

```text
ridge_regressor_clip100
ridge_classifier_positive
```

Features:

```text
side-aware 1s / 5s / 30s mid returns
side-aware 1s / 2s liquidation pressure
side-aware Bybit 5s liquidation pressure with the required +200ms delay
side-aware 1s / 5s recent trade-flow pressure
BBO imbalance
spread in bps
log notional
symbol flag
```

The model was trained on a sampled train set:

```text
600,426 train rows per horizon
```

Validation was evaluated on a much denser stream:

```text
validation_stride = 10
about 50.7 million validation rows per horizon/model
```

Thresholds were selected on train predictions only, by target keep fraction:

```text
0.1%, 0.2%, 0.5%, 1%, 2%, 5%, 10%, 20%
```

This avoids choosing a validation threshold after seeing validation PnL.

## Best Validation Screen Results

Best rows by horizon from the fast ML validation screen:

| horizon | model | keep fraction | validation score | pnl kept | sampled kept turnover/day |
|---:|---|---:|---:|---:|---:|
| 30s | ridge_classifier_positive | 0.1% | 24.0283 | 23.9887 | $19.9M |
| 120s | ridge_regressor_clip100 | 0.1% | 20.8555 | 20.8191 | $8.7M |
| 300s | ridge_regressor_clip100 | 0.1% | 17.3818 | 17.4202 | $33.0M |

Current exact hybrid validation result:

| horizon | exact hybrid validation score | exact hybrid pnl kept | exact hybrid kept turnover/day |
|---:|---:|---:|---:|
| 30s | 42.5688 | 42.5224 | $84.2M |
| 120s | 11.5558 | 11.5232 | $351.1M |
| 300s | 12.5831 | 12.6077 | $351.1M |

Interpretation:

- ML does not beat the current 30s return-reversal rule.
- ML looks promising for 120s and 300s on the dense validation screen.
- The ML 120s/300s edge is narrower-turnover and needs an exact full-stream check before replacing the simple production rule.

## Feature Insight

Largest absolute ridge-regressor coefficients:

| horizon | feature | coefficient |
|---:|---|---:|
| 300s | side_aware_return_30s | 1.3381 |
| 120s | side_aware_bybit_liq_5s | 1.1949 |
| 120s | side_aware_return_30s | 1.0524 |
| 300s | side_aware_bybit_liq_5s | 1.0115 |
| 30s | side_aware_return_30s | 0.4397 |
| 30s | side_aware_return_1s | -0.4051 |
| 30s | side_aware_return_5s | 0.3739 |
| 30s | side_aware_bybit_liq_5s | 0.3284 |

This is a useful sanity check: the model did not rely on arbitrary noise. It emphasized the same feature families found by manual research:

```text
returns + cross-exchange liquidation pressure + spread/notional context
```

## Decision

Do not replace the final submission rule with ML yet.

Current final rule remains:

```text
30s  -> side-aware 5s return reversal
120s -> liquidation-pressure baseline
300s -> liquidation-pressure baseline
```

Reason:

- The current hybrid has exact full-stream validation and 6-month public checks.
- The ML result is promising but still a screen, not an exact production replacement.
- A hidden-test submission should prefer the simpler, more robust rule unless the ML variant passes full exact validation and public-regime checks.

## Next ML Step

The next exact candidate is:

```text
120s -> ridge_regressor_clip100, keep top 0.1%
300s -> ridge_regressor_clip100, keep top 0.1%
```

Before using it in `predict`, export the learned medians/scales/intercepts/coefficients, implement the linear score directly in NumPy, and run:

```text
exact validation
full public 6-month check
per-symbol diagnostics
per-regime diagnostics
```

Only then should ML replace the rule-based 120s/300s logic.
