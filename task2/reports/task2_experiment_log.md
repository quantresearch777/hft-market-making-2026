# Task 2 Experiment Log

This is the running research log. Each experiment records:

```text
hypothesis -> protocol -> result -> pros/cons -> decision
```

The goal is not to collect many random experiments. The goal is to improve the final solution while keeping it robust and explainable.

## Current Best Working Solution

Current `predict` rule:

```text
30s  -> symbol-specific side-aware 5s return reversal
        BTC keep if > 50 bps, ETH keep if > 100 bps
120s -> side-aware 2s liquidation pressure AND side-aware 5s return > 20 bps
300s -> side-aware 2s liquidation pressure, keep if > 2m
```

Why this replaced the previous hybrid:

```text
The previous hybrid used return5s_gt_50 for 30s and the 1s liquidation baseline
for 120s/300s. The new candidate improves every horizon on the public 6-month
stride=10 screen and, importantly, improves public_extra too.
```

Public 6-month stride=10 screen:

| split | horizon | previous hybrid score | current candidate score |
|---|---:|---:|---:|
| overall | 30s | 20.6530 | 35.1926 |
| overall | 120s | 6.9457 | 27.7020 |
| overall | 300s | 7.7372 | 18.6190 |
| public_extra | 30s | -2.9740 | 6.8345 |
| public_extra | 120s | -0.8506 | 4.6857 |
| public_extra | 300s | -2.2403 | 3.1897 |

Exact first-week check for implemented `predict`:

```text
Period: 2026-02-01 -> 2026-02-07
Mode: exact, trade_stride=1
```

| horizon | score | pnl kept | kept turnover/day |
|---:|---:|---:|---:|
| 30s | 76.4753 | 76.5131 | $65.3M |
| 120s | 42.8648 | 42.9284 | $31.4M |
| 300s | 18.2710 | 18.3293 | $71.1M |

Risk note:

```text
Average score improves materially, but long-horizon day-symbol tails are worse
than the old baseline in some rows. This is an explicit score-vs-tail-risk trade-off.
The 30s rule is also more sniper-like: some day-symbol rows have no kept trades,
although the horizon-level turnover constraint is passed with a large margin.
```

Decision:

```text
Adopt as the current working best solution.
Continue research from this baseline, especially tail-risk guards for 120s/300s.
```

## Experiment 1: Liquidation-Pressure Baseline

Hypothesis:

```text
Recent liquidation pressure is a proxy for toxic maker fills.
```

Protocol:

```text
Rule: keep if trade_side * (Binance liq 1s + delayed Bybit liq 1s) > 100k
Bybit delay: +200ms
Evaluation: exact official train/validation
```

Result:

| horizon | official overall score | pnl kept | kept turnover/day |
|---:|---:|---:|---:|
| 30s | 5.3162 | 5.2548 | $355.1M |
| 120s | 11.6928 | 11.7166 | $355.1M |
| 300s | 12.4354 | 12.5126 | $355.1M |

Pros:

- simple and explainable;
- works on all horizons;
- very high turnover;
- directly uses the unique liquidation dataset.

Cons:

- 30s score is much weaker than later return-reversal variant.

Decision:

```text
Keep as the stable baseline for 120s/300s.
Replace only 30s with a stronger exact-validated signal.
```

## Experiment 2: 30s Return-Reversal Hybrid

Hypothesis:

```text
After a large side-aware move, maker fills have better 30s reversal markout.
```

Protocol:

```text
30s rule: keep if trade_side * previous_5s_mid_return > 50 bps
120s/300s: keep liquidation baseline
Evaluation: exact official train/validation + full public 6-month check
```

Result:

| horizon | old score | hybrid score |
|---:|---:|---:|
| 30s | 5.3162 | 29.7368 |
| 120s | 11.6928 | 11.6928 |
| 300s | 12.4354 | 12.4354 |

Pros:

- large 30s improvement;
- no future leakage;
- still simple enough to explain;
- passes 6-month public aggregate.

Cons:

- weaker in March-April public-extra regime;
- negative pockets appear on some low-turnover day-symbol rows.

Decision:

```text
Adopt as current best for 30s.
Search for a regime guard / sniper variant to reduce weak-period risk.
```

## Experiment 3: Broad Rule Grid

Hypothesis:

```text
Other windows, delays, returns, trade-flow and BBO filters may improve the rule.
```

Protocol:

```text
Test liquidation windows, Bybit delays, returns, trade-flow, spread, imbalance, and rule combinations.
Use sampled/dense screens first, then exact checks for candidates.
```

Important findings:

- `return5s_gt_100` can look excellent but may fail train turnover or be too narrow.
- `return5s_gt_50` is a better turnover/quality compromise for 30s.
- longer-horizon return rules can look great in aggregate screens but have dangerous bad days.
- `bybit5s_d200_gt_2m` and `liq2s_d200_gt_2m` look promising for 300s, but must be checked for day-level risk.

Pros:

- discovered the current 30s improvement;
- found several 120s/300s candidates for deeper exact testing.

Cons:

- sampled screens can be misleading;
- high-score narrow rules may be regime traps.

Decision:

```text
Use grid search for idea discovery only.
Require exact validation before changing final predict.
```

## Experiment 4: Sampled HGB ML Ranker

Hypothesis:

```text
A nonlinear tabular model may combine return, liquidation, flow and BBO features better than manual rules.
```

Protocol:

```text
Model: HistGradientBoostingRegressor
Train/validation by time
Features: returns, liquidation pressure, trade-flow, spread, imbalance, notional, symbol
```

Best sampled validation:

| horizon | best keep fraction | score |
|---:|---:|---:|
| 30s | 10% | 1.5948 |
| 120s | 5% | 5.9329 |
| 300s | 5% | 1.4319 |

Pros:

- useful sanity check for feature families;
- validates that microstructure features contain signal.

Cons:

- weaker than rule-based hybrid;
- too sampled to be production-relevant.

Decision:

```text
Do not use HGB in final solution.
Keep as research background only.
```

## Experiment 5: Dense Linear ML Ranker

Hypothesis:

```text
A simple linear ranker may be faster and more robust than nonlinear ML, while still combining features better than manual thresholds.
```

Protocol:

```text
Models: ridge_regressor_clip100, ridge_classifier_positive
Train: Dec-Jan, 600,426 sampled rows per horizon
Validation: Feb with validation_stride=10, about 50.7M validation rows per horizon/model
Thresholds selected on train only by keep fraction
```

Best dense validation screen:

| horizon | model | keep fraction | score | pnl kept | sampled kept turnover/day |
|---:|---|---:|---:|---:|---:|
| 30s | ridge_classifier_positive | 0.1% | 24.0283 | 23.9887 | $19.9M |
| 120s | ridge_regressor_clip100 | 0.1% | 20.8555 | 20.8191 | $8.7M |
| 300s | ridge_regressor_clip100 | 0.1% | 17.3818 | 17.4202 | $33.0M |

Pros:

- professional time-split protocol;
- thresholds fixed from train;
- model highlights sensible features: 30s returns, Bybit liquidation pressure, spread and notional.

Cons:

- not yet exact full-stream;
- narrow turnover compared with current 120s/300s baseline;
- would require exporting coefficients and medians/scales into `predict`.

Decision:

```text
Promising for 120s/300s, but not adopted yet.
Next step: exact full-stream validation for the 120s/300s ridge candidates.
```

## Experiment 6: Exact One-Day Rule Stress Check

Hypothesis:

```text
Rules that look strong in February screens should survive a bad-day exact stress check.
```

Protocol:

```text
Date: 2026-02-01
Mode: exact, trade_stride=1
Rules: core return/liquidation/combo candidates
```

Key result:

| rule | horizon | score | comment |
|---|---:|---:|---|
| return5s_gt_50 | 30s | 14.0477 | positive |
| return5s_gt_50 | 120s | -58.7439 | dangerous |
| return5s_gt_50 | 300s | -75.8143 | dangerous |
| neg_return30s_gt_50 | 120s | 13.4337 | interesting stress-day hedge |
| bybit5s_d200_gt_2m | 300s | 70.6704 | very strong but narrow |
| liq2s_and_return5s_gt_20 | 30s | 52.5993 | strong sniper candidate |

Pros:

- quickly reveals day-level blow-ups;
- protects against misleading aggregate screens.

Cons:

- one day is not enough to accept a rule;
- can reject rules that work in other regimes if used too aggressively.

Decision:

```text
Do not use return5s for 120s/300s directly.
Continue exact weekly/monthly checks for sniper 30s and 300s liquidation candidates.
```

## Running / Next Experiments

### Experiment 7: Exact First-Week February Rule Check

Status:

```text
completed
```

Goal:

```text
Check whether the one-day behavior persists over 2026-02-01 -> 2026-02-07.
```

Candidates to watch:

- `liq2s_and_return5s_gt_20` for 30s;
- `bybit5s_d200_gt_2m` for 300s;
- `liq2s_d200_gt_2m` for 300s;
- `neg_return30s_gt_50` for 120s stress-day behavior;
- current hybrid as benchmark.

Decision rule:

```text
Only promote a candidate if it improves score without creating obvious day-level fragility.
```

Result:

```text
2026-02-01 -> 2026-02-07, exact trade_stride=1
```

Key scores:

| rule | 30s | 120s | 300s |
|---|---:|---:|---:|
| baseline_liq1s_d200_gt_100k | 9.5405 | 14.7523 | 13.7577 |
| return5s_gt_50 | 50.6189 | 52.3736 | 55.4634 |
| return5s_gt_100 | 82.8085 | 74.5749 | 83.9142 |
| bybit5s_d200_gt_2m | 13.8786 | 25.0348 | 16.0456 |
| liq2s_d200_gt_2m | 15.4247 | 26.6917 | 18.2710 |

Main lesson:

```text
Aggressive return rules are excellent on average in this exact week, but can have severe worst-row losses.
Bybit/liquidation long-window rules improve aggregate long-horizon scores, but also increase worst-row tail risk versus the original baseline.
```

### Experiment 8: Exact ML Candidate Check

Status:

```text
planned
```

Goal:

```text
Export ridge_regressor_clip100 features/coefficients for 120s and 300s, implement direct NumPy scoring, and run exact validation/public checks.
```

Decision rule:

```text
Adopt only if it beats the current 120s/300s exact hybrid on validation and does not fail public-regime diagnostics.
```

### Experiment 9: Symbol-Specific 30s Return Threshold

Status:

```text
official stride=10 screen completed; public stride=10 check running
```

Hypothesis:

```text
BTC and ETH have different 30s return-reversal regimes.
ETH can use a stricter >100 bps threshold, while BTC should keep the current >50 bps threshold.
```

Why this is interesting:

```text
On the existing stride=10 official screen:
current 30s return5s_gt_50:
  train score      9.8344
  validation score 43.7334

symbol-specific ETH>100 / BTC>50:
  train score      25.6756
  validation score 70.6669
```

Main risk:

```text
Turnover is narrower, so exact/public checks are required before adopting it.
```

Decision rule:

```text
Promote only if exact validation and full public diagnostics remain robust.
```

### Experiment 10: Stronger Long-Horizon Liquidation Windows

Status:

```text
running as official stride=10 variant screen
```

Hypothesis:

```text
The original 1s liquidation baseline is robust, but longer / more selective liquidation windows may give better 120s and 300s markout.
```

Promising screen rules:

| horizon | candidate rule | train score | validation score |
|---:|---|---:|---:|
| 120s | bybit5s_d200_gt_2m | 36.8118 | 25.4643 |
| 120s | liq2s_d200_gt_2m | 29.9519 | 25.8182 |
| 120s | current baseline | 11.3917 | 11.7256 |
| 300s | bybit5s_d200_gt_2m | 35.2120 | 20.9432 |
| 300s | liq2s_d200_gt_2m | 28.7360 | 20.6031 |
| 300s | current baseline | 11.9466 | 12.5785 |

Best combined screen candidate:

```text
eth100_btc50_bybit_long

30s  -> BTC return5s > 50, ETH return5s > 100
120s -> bybit5s_d200 > 2m
300s -> bybit5s_d200 > 2m
```

Official stride=10 screen versus current hybrid:

| split | horizon | current score | candidate score |
|---|---:|---:|---:|
| train | 30s | 9.8344 | 25.6756 |
| train | 120s | 11.3917 | 36.8118 |
| train | 300s | 11.9466 | 35.2120 |
| validation | 30s | 43.7334 | 70.6669 |
| validation | 120s | 11.7256 | 25.4643 |
| validation | 300s | 12.5785 | 20.9432 |

Main risks:

- 30s symbol-specific rule has narrower turnover;
- 120s/300s stronger liquidation rules can have bad individual days;
- exact and public-extra checks may be weaker than the official screen.

Official stride=10 day-symbol diagnostics:

```text
negative rows out of 180:
current_hybrid 30s  = 14
candidate      30s  = 6
current_hybrid 120s = 36
candidate      120s = 20
current_hybrid 300s = 42
candidate      300s = 31
```

The candidate improves aggregate score and reduces the count of negative rows, but some worst-row scores are worse. Public-regime validation is still required.

Public 6-month stride=10 result:

```text
eth100_btc50_bybit_long improves full-period aggregate:
30s  35.1926 vs current 20.6530
120s 19.3317 vs current 6.9457
300s 18.6068 vs current 7.7372
```

But public-extra reveals a regime problem:

```text
30s symbol-specific remains better:
  6.8345 vs current -2.9740

120s Bybit weakens:
  -9.3474 vs current -0.8506

120s liq2 is better on public_extra:
  4.6600 vs current -0.8506

300s Bybit weakens:
  -18.4875 vs current -2.2403
```

Current decision:

```text
30s symbol-specific threshold is the best candidate.
120s should prefer liq2 over Bybit if public robustness matters.
300s needs an additional liq2/public check before changing the current baseline.
```

Decision rule:

```text
Promote this candidate only after exact weekly stress and public-regime checks.
```

### Experiment 11: Public-Regime V3 Candidate Selection

Status:

```text
completed; adopted as intermediate candidate, then improved by Experiment 12
```

Hypothesis:

```text
The best final candidate should improve train/validation while also surviving
public_extra. Bybit-only liquidation pressure may be too exchange-specific,
so combined Binance+Bybit 2s liquidation pressure may be more robust.
```

Protocol:

```text
Period: 2025-11-01 -> 2026-04-28
Mode: public 6-month stride=10 screen
Compare: current_hybrid, eth100_btc50_bybit_long, eth100_btc50_liq2_long,
         plus intermediate horizon mixes.
```

Key result:

| variant | split | 30s | 120s | 300s |
|---|---|---:|---:|---:|
| current_hybrid | overall | 20.6530 | 6.9457 | 7.7372 |
| eth100_btc50_bybit_long | overall | 35.1926 | 19.3317 | 18.6068 |
| eth100_btc50_liq2_long | overall | 35.1926 | 18.4605 | 18.6190 |
| current_hybrid | public_extra | -2.9740 | -0.8506 | -2.2403 |
| eth100_btc50_bybit_long | public_extra | 6.8345 | -9.3474 | -18.4875 |
| eth100_btc50_liq2_long | public_extra | 6.8345 | 4.6600 | 3.1897 |

Pros:

- the candidate improves all horizons on overall public 6-month screen;
- unlike Bybit-only long, it also improves all horizons on public_extra;
- it stays simple enough to implement as a NumPy rule in `predict`;
- no future information is used.

Cons:

- it keeps fewer trades than the old liquidation baseline;
- 120s/300s worst day-symbol rows are worse than the old baseline;
- 30s BTC and ETH individually can be below the turnover threshold, although the combined horizon-level turnover passes in the evaluation.

Decision:

```text
Adopt eth100_btc50_liq2_long as the intermediate candidate:
30s = BTC return5s_gt_50, ETH return5s_gt_100
120s/300s = liq2s_d200_gt_2m

Then continue with combo-guard research for 120s tail/quality improvement.
```

Output tables:

```text
reports/tables/task2_variant_public6m_stride10_v3_summary_overall.csv
reports/tables/task2_variant_public6m_stride10_v3_summary_by_split.csv
reports/tables/task2_variant_public6m_stride10_v3_summary_by_symbol.csv
reports/tables/task2_candidate_exact_20260201_07_summary_overall.csv
reports/tables/task2_candidate_exact_20260201_07_summary_by_split.csv
reports/tables/task2_candidate_exact_20260201_07_daily_metrics.csv
```

### Experiment 12: Liquidation + Return Guard Variants

Status:

```text
completed and partially adopted
```

Hypothesis:

```text
The adopted liq2 long-horizon rule improves average score, but has worse tail
rows. Combining liquidation pressure with recent return filters may keep the
average improvement while reducing bad-regime exposure.
```

Variants prepared:

```text
eth100_btc50_baseline_and_ret20_long
eth100_btc50_baseline_or_ret50_long
eth100_btc50_liq2_and_ret20_long
eth100_btc50_liq2_or_ret50_long
eth100_btc50_bybit_or_ret50_long
eth100_btc50_ret5_long
```

Decision rule:

```text
Run public 6-month stride screen after the current exact candidate check.
Promote only if public_extra and tail diagnostics improve versus eth100_btc50_liq2_long.
```

Result:

| variant / rule | split | 120s | 300s |
|---|---|---:|---:|
| eth100_btc50_liq2_long | overall | 18.4605 | 18.6190 |
| eth100_btc50_liq2_and_ret20_long | overall | 27.7020 | 27.2266 |
| eth100_btc50_ret5_long | overall | 30.0280 | 32.0859 |
| eth100_btc50_liq2_long | public_extra | 4.6600 | 3.1897 |
| eth100_btc50_liq2_and_ret20_long | public_extra | 4.6857 | -1.1969 |
| eth100_btc50_ret5_long | public_extra | -9.8268 | -19.8047 |

Interpretation:

```text
ret5_long has the best overall 120s/300s score but fails public_extra again.
liq2_and_ret20 is a real 120s improvement: stronger overall, much stronger
validation, slightly better public_extra, and a better worst-row minimum.
For 300s, liq2_and_ret20 worsens public_extra, so 300s should remain plain liq2.
```

Final decision:

```text
Adopt only the 120s part:
30s  = BTC return5s_gt_50, ETH return5s_gt_100
120s = liq2s_d200_gt_2m AND return5s_gt_20
300s = liq2s_d200_gt_2m
```

Output tables:

```text
reports/tables/task2_variant_public6m_stride10_v4_combo_summary_overall.csv
reports/tables/task2_variant_public6m_stride10_v4_combo_summary_by_split.csv
reports/tables/task2_variant_public6m_stride10_v4_combo_summary_by_symbol.csv
```
