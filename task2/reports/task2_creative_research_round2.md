# Task 2 Creative Research Round 2

This note records the deeper research pass after the first hybrid improvement.

## Update After Round 3

This note is historical. The first hybrid was later upgraded to:

```text
30s  -> BTC return5s_gt_50, ETH return5s_gt_100
120s -> liq2s_d200_gt_2m AND return5s_gt_20
300s -> liq2s_d200_gt_2m
```

The upgrade came from the public 6-month stride=10 V3 check: the symbol-specific
30s rule improved public_extra, and the combined 2s liquidation-pressure rule was
more robust than the Bybit-only long-horizon candidate.

See:

```text
reports/task2_experiment_log.md
reports/task2_candidate_improvement_round3.md
```

## Research Questions

I checked three things:

- Does the 30s return-reversal filter generalize outside train/validation?
- Where does the hybrid win or fail by symbol and by day?
- Is a simple sklearn model worth replacing the rule-based solution?

## Exact 6-Month Hybrid Check

The hybrid was evaluated on the full public period:

```text
2025-11-01 -> 2026-04-28
179 days
```

Overall hybrid result:

| horizon | score | pnl_kept | kept turnover/day |
|---:|---:|---:|---:|
| 30s | 20.0623 | 19.9842 | $31.9M |
| 120s | 7.1584 | 7.1432 | $319.8M |
| 300s | 7.9808 | 8.0161 | $319.8M |

Compared with the previous 6-month liquidation-only baseline:

| horizon | old score | hybrid score |
|---:|---:|---:|
| 30s | 3.7693 | 20.0623 |
| 120s | 7.1584 | 7.1584 |
| 300s | 7.9808 | 7.9808 |

So the 30s hybrid remains materially better over the full public dataset.

## Public-Extra Regime Check

The public-extra period is not uniform:

| period | 30s score |
|---|---:|
| November 2025 | 4.7133 |
| March-April 2026 | -2.7648 |
| Public-extra combined | -0.6631 |

Interpretation:

```text
The 30s return-reversal idea works on official train/validation and November,
but weakens in March-April.
```

This does not break the full public result, but it means the signal is regime-dependent.

## Symbol Diagnostics

Official-period hybrid by symbol:

| horizon | symbol | score | pnl_kept | kept turnover/day |
|---:|---|---:|---:|---:|
| 30s | BTCUSDT | 18.2860 | 18.1502 | $3.2M |
| 30s | ETHUSDT | 30.5702 | 30.5886 | $40.0M |
| 120s | BTCUSDT | 6.8791 | 6.8166 | $195.6M |
| 120s | ETHUSDT | 17.6105 | 17.7269 | $159.5M |
| 300s | BTCUSDT | 6.8766 | 6.8401 | $195.6M |
| 300s | ETHUSDT | 19.2712 | 19.4705 | $159.5M |

ETH contributes more of the 30s hybrid turnover and score. BTC still works, but it is thinner for 30s after the return filter.

Official day-symbol diagnostics:

```text
Hybrid 30s negative day-symbol rows: 14 / 180
```

That is acceptable for aggregate score, but the next robustness improvement should focus on avoiding very low-turnover day-symbol pockets.

## ML Research

I tested a simple `sklearn` `HistGradientBoostingRegressor` as a sampled time-split ranker.

Setup:

```text
train:      sampled Dec-Jan
validation: sampled Feb
sample_every: 3 days
trade_stride: 5000
features: returns, liquidation pressure, trade flow, spread, imbalance, notional, symbol
target: clipped future maker PnL
```

Best sampled validation scores:

| horizon | best keep fraction | validation score |
|---:|---:|---:|
| 30s | 10% | 1.5948 |
| 120s | 5% | 5.9329 |
| 300s | 5% | 1.4319 |

This is positive, but it is not strong enough to replace the rule-based hybrid. The model may become useful later as a secondary ranker, especially for 120s, but it needs a stronger validation protocol before being used in `predict`.

## ML Research Round 2

I then ran a faster but denser linear ML screen:

```text
models: ridge_regressor_clip100, ridge_classifier_positive
train: Dec-Jan, 600,426 sampled rows per horizon
validation: Feb, validation_stride=10, about 50.7 million rows per horizon/model
thresholds: selected on train only by keep fraction
```

Best validation screen rows:

| horizon | model | keep fraction | score | pnl kept | sampled kept turnover/day |
|---:|---|---:|---:|---:|---:|
| 30s | ridge_classifier_positive | 0.1% | 24.0283 | 23.9887 | $19.9M |
| 120s | ridge_regressor_clip100 | 0.1% | 20.8555 | 20.8191 | $8.7M |
| 300s | ridge_regressor_clip100 | 0.1% | 17.3818 | 17.4202 | $33.0M |

Decision:

```text
ML does not beat the exact 30s hybrid rule.
ML is promising for 120s/300s, but it needs exact full-stream validation before replacing the simpler liquidation rule.
```

Detailed note:

```text
reports/task2_ml_professional_research.md
```

## Decision

Keep the current production-style solution:

```text
30s  -> side-aware 5s return reversal
120s -> liquidation-pressure baseline
300s -> liquidation-pressure baseline
```

Do not replace it with ML yet.

## Best Next Ideas

The next serious improvement should be a regime switch for 30s:

- use return-reversal when the regime looks favorable;
- fall back to liquidation baseline when return-reversal turnover is too thin or recent volatility/liquidation behavior looks unstable.

Candidate regime features:

- daily or rolling count of return-filter kept trades;
- recent realized volatility;
- spread regime;
- liquidation cluster intensity;
- symbol-specific thresholding for BTC vs ETH.

This is more promising than a blind ML replacement.
