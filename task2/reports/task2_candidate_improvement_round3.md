# Task 2 Candidate Improvement Round 3

This note focuses only on candidates that could improve the current best solution.

## Adopted Candidate After Public-Regime Check

Final candidate now implemented in `src/task2_solution.py`:

```text
30s  -> BTC return5s_gt_50, ETH return5s_gt_100
120s -> liq2s_d200_gt_2m AND return5s_gt_20
300s -> liq2s_d200_gt_2m
```

Reason:

```text
The 30s symbol-specific return rule improved train, validation and public_extra.
The Bybit-only long-horizon rule looked stronger on official train/validation,
but failed on public_extra. The combined Binance+Bybit 2s liquidation-pressure
rule was weaker than Bybit on train, but much more robust on public_extra.
The later combo-guard screen improved 120s further by requiring both liq2
pressure and a softer 5s return signal.
```

Public 6-month stride=10 result versus previous current hybrid:

| split | horizon | previous current | adopted candidate |
|---|---:|---:|---:|
| overall | 30s | 20.6530 | 35.1926 |
| overall | 120s | 6.9457 | 27.7020 |
| overall | 300s | 7.7372 | 18.6190 |
| public_extra | 30s | -2.9740 | 6.8345 |
| public_extra | 120s | -0.8506 | 4.6857 |
| public_extra | 300s | -2.2403 | 3.1897 |

Exact first-week check of the implemented `predict`:

```text
2026-02-01 -> 2026-02-07
trade_stride = 1
```

| horizon | score | pnl kept | kept turnover/day |
|---:|---:|---:|---:|
| 30s | 76.4753 | 76.5131 | $65.3M |
| 120s | 42.8648 | 42.9284 | $31.4M |
| 300s | 18.2710 | 18.3293 | $71.1M |

Pros:

- improves the average score on train, validation, public_extra and full public-6m screen;
- keeps the rule explainable and leak-free;
- avoids the Bybit-only long-horizon public_extra failure;
- improves 120s further with a return guard while preserving public_extra;
- uses different signals for different horizons, which matches the empirical behavior.

Cons:

- 30s turnover is narrower than the old all-symbol 50 bps rule;
- long-horizon day-level tail losses are still worse than the old liquidation baseline in some rows;
- this is still a rule-based signal, not a fully calibrated portfolio/position-aware model.

Decision:

```text
Adopt this candidate as the working best solution.
Keep documenting tail-risk caveats and continue research from this baseline.
```

## Current Best

```text
30s  -> return5s_gt_50
120s -> baseline_liq1s_d200_gt_100k
300s -> baseline_liq1s_d200_gt_100k
```

Exact validation:

| horizon | score | pnl kept | kept turnover/day |
|---:|---:|---:|---:|
| 30s | 42.5688 | 42.5224 | $84.2M |
| 120s | 11.5558 | 11.5232 | $351.1M |
| 300s | 12.5831 | 12.6077 | $351.1M |

## Candidate A: Symbol-Specific 30s Return Threshold

Rule:

```text
BTC 30s -> return5s_gt_50
ETH 30s -> return5s_gt_100
```

Why:

```text
ETH has enough strong return-reversal events to use a stricter threshold.
BTC becomes too sparse at 100 bps, so BTC keeps the current 50 bps threshold.
```

Stride=10 official screen:

| split | current 30s score | candidate 30s score |
|---|---:|---:|
| train | 9.8344 | 25.6756 |
| validation | 43.7334 | 70.6669 |

Pros:

- materially better score on both train and validation screens;
- still simple and explainable;
- no future leakage, only prior BBO mid return.

Cons:

- narrower turnover;
- exact/public checks still required.

Status:

```text
promising, running deeper checks
```

## Candidate B: Stronger 120s Liquidation Window

Rules checked:

```text
liq2s_d200_gt_2m
bybit5s_d200_gt_2m
```

Stride=10 official screen:

| rule | train score | validation score |
|---|---:|---:|
| baseline_liq1s_d200_gt_100k | 11.3917 | 11.7256 |
| liq2s_d200_gt_2m | 29.9519 | 25.8182 |
| bybit5s_d200_gt_2m | 36.8118 | 25.4643 |

Pros:

- both stronger than current baseline on train and validation screens;
- still fully explainable as liquidation-pressure filters;
- turnover remains above the requirement in the screen.

Cons:

- bad-day risk exists;
- one-day exact stress showed some stronger rules can be worse than baseline on 2026-02-01.

Status:

```text
promising, but exact stress check is mandatory
```

## Candidate C: Stronger 300s Liquidation Window

Rules checked:

```text
liq2s_d200_gt_2m
bybit5s_d200_gt_2m
```

Stride=10 official screen:

| rule | train score | validation score |
|---|---:|---:|
| baseline_liq1s_d200_gt_100k | 11.9466 | 12.5785 |
| liq2s_d200_gt_2m | 28.7360 | 20.6031 |
| bybit5s_d200_gt_2m | 35.2120 | 20.9432 |

Pros:

- strong improvement on both train and validation screens;
- one-day exact stress was also strong for 300s;
- Bybit liquidation pressure appears particularly useful at 300s.

Cons:

- narrower turnover than baseline;
- needs public-extra regime check.

Status:

```text
very promising for 300s
```

## Best Combined Candidate So Far

```text
eth100_btc50_liq2_120_bybit300
```

Mapping:

```text
30s  -> BTC return5s_gt_50, ETH return5s_gt_100
120s -> liq2s_d200_gt_2m
300s -> bybit5s_d200_gt_2m
```

Stride=10 official screen versus current:

| split | horizon | current score | candidate score |
|---|---:|---:|---:|
| train | 30s | 9.8344 | 25.6756 |
| train | 120s | 11.3917 | 29.9519 |
| train | 300s | 11.9466 | 35.2120 |
| validation | 30s | 43.7334 | 70.6669 |
| validation | 120s | 11.7256 | 25.8182 |
| validation | 300s | 12.5785 | 20.9432 |

Decision:

```text
Do not adopt yet.
Run exact week stress, exact/denser official validation, and public-extra checks first.
```

## Official Stride=10 Variant Screen Result

The expanded official train/validation variant screen completed.

Best practical candidate after checking split and day-risk:

```text
eth100_btc50_bybit_long

30s  -> BTC return5s_gt_50, ETH return5s_gt_100
120s -> bybit5s_d200_gt_2m
300s -> bybit5s_d200_gt_2m
```

Why this became the preferred candidate:

- `30s` symbol-specific threshold strongly improves score;
- `120s` Bybit 5s liquidation pressure has stronger score and fewer negative day-symbol rows than the current baseline in the screen;
- `300s` Bybit 5s liquidation pressure is also materially stronger than the current baseline.

Official stride=10 by split:

| split | horizon | current score | eth100_btc50_bybit_long score |
|---|---:|---:|---:|
| train | 30s | 9.8344 | 25.6756 |
| train | 120s | 11.3917 | 36.8118 |
| train | 300s | 11.9466 | 35.2120 |
| validation | 30s | 43.7334 | 70.6669 |
| validation | 120s | 11.7256 | 25.4643 |
| validation | 300s | 12.5785 | 20.9432 |

Day-symbol diagnostics, official stride=10:

| variant | horizon | negative rows / 180 | min score | p05 score |
|---|---:|---:|---:|---:|
| current_hybrid | 30s | 14 | -41.9267 | -19.8546 |
| eth100_btc50_bybit_long | 30s | 6 | -94.0596 | -16.0560 |
| current_hybrid | 120s | 36 | -47.8606 | -8.2239 |
| eth100_btc50_bybit_long | 120s | 20 | -66.4232 | -21.6781 |
| current_hybrid | 300s | 42 | -60.3012 | -11.3351 |
| eth100_btc50_bybit_long | 300s | 31 | -67.8824 | -37.5048 |

Interpretation:

```text
The candidate improves aggregate score and reduces the count of negative day-symbol rows.
However, its tail losses can be worse on the worst rows, so the public-regime check is mandatory.
```

Dangerous false lead:

```text
ret5_all has very high aggregate 120s/300s score in the stride=10 screen,
but the exact one-day stress check already showed severe 120s/300s failures.
Do not promote ret5_all without a regime guard.
```

Output tables:

```text
reports/tables/task2_variant_official_stride10_summary_overall.csv
reports/tables/task2_variant_official_stride10_summary_by_split.csv
reports/tables/task2_variant_official_stride10_summary_by_symbol.csv
```

## Running Checks

Currently running on the server:

```text
1. public 6-month stride=10 variant screen
```

## Exact First-Week February Stress Result

Period:

```text
2026-02-01 -> 2026-02-07
trade_stride = 1
```

Key exact results:

| rule | horizon | score | pnl kept | kept turnover/day |
|---|---:|---:|---:|---:|
| return5s_gt_100 | 30s | 82.8085 | 82.8463 | $59.6M |
| return5s_gt_50 | 30s | 50.6189 | 50.6567 | $242.2M |
| baseline_liq1s_d200_gt_100k | 30s | 9.5405 | 9.5783 | $704.8M |
| return5s_gt_100 | 120s | 74.5749 | 74.6385 | $59.6M |
| return5s_gt_50 | 120s | 52.3736 | 52.4372 | $242.2M |
| bybit5s_d200_gt_2m | 120s | 25.0348 | 25.0984 | $151.8M |
| baseline_liq1s_d200_gt_100k | 120s | 14.7523 | 14.8159 | $704.8M |
| return5s_gt_100 | 300s | 83.9142 | 83.9725 | $59.6M |
| return5s_gt_50 | 300s | 55.4634 | 55.5217 | $242.2M |
| bybit5s_d200_gt_2m | 300s | 16.0456 | 16.1039 | $151.8M |
| baseline_liq1s_d200_gt_100k | 300s | 13.7577 | 13.8160 | $704.8M |

Tail diagnostics:

| rule | horizon | negative rows / 14 | min score | p05 score |
|---|---:|---:|---:|---:|
| baseline_liq1s_d200_gt_100k | 120s | 2 | -13.5868 | -6.8372 |
| bybit5s_d200_gt_2m | 120s | 2 | -24.1537 | -13.5618 |
| baseline_liq1s_d200_gt_100k | 300s | 6 | -8.4978 | -8.1276 |
| bybit5s_d200_gt_2m | 300s | 4 | -38.9642 | -30.2693 |
| return5s_gt_50 | 120s | 2 | -58.5219 | -30.8545 |
| return5s_gt_50 | 300s | 3 | -75.6858 | -64.0175 |

Symbol-specific 30s exact-week check:

| 30s rule | score | kept turnover/day | negative rows / 14 | min score |
|---|---:|---:|---:|---:|
| current return5s_gt_50 all symbols | 50.6189 | $242.2M | 1 | -1.4874 |
| BTC return5s_gt_50, ETH return5s_gt_100 | 76.4753 | $65.3M | 2 | -90.6531 |
| return5s_gt_100 all symbols | 82.8085 | $59.6M | 1 | -90.6531 |

Interpretation:

```text
The aggressive return rules are very strong on average, but their worst rows are much worse.
Bybit 5s improves aggregate 120s/300s but also worsens worst-row tail risk.
This is not an automatic rejection, because the task metric is average score, but it means public-regime checks matter.
```

## Public 6-Month Stride=10 Result

Period:

```text
2025-11-01 -> 2026-04-28
trade_stride = 10
179 days
```

Overall:

| variant | horizon | score | pnl kept | kept turnover/day |
|---|---:|---:|---:|---:|
| current_hybrid | 30s | 20.6530 | 20.5776 | $3.2M |
| eth100_btc50_bybit_long | 30s | 35.1926 | 35.1172 | $0.8M |
| current_hybrid | 120s | 6.9457 | 6.9257 | $32.0M |
| eth100_btc50_bybit_long | 120s | 19.3317 | 19.3116 | $7.1M |
| eth100_btc50_liq2_120_bybit300 | 120s | 18.4605 | 18.4405 | $3.7M |
| current_hybrid | 300s | 7.7372 | 7.7727 | $32.0M |
| eth100_btc50_bybit_long | 300s | 18.6068 | 18.6423 | $7.1M |

Public-extra split:

| variant | horizon | score | pnl kept | kept turnover/day |
|---|---:|---:|---:|---:|
| current_hybrid | 30s | -2.9740 | -3.0812 | $2.2M |
| eth100_btc50_bybit_long | 30s | 6.8345 | 6.7273 | $0.5M |
| current_hybrid | 120s | -0.8506 | -0.9409 | $23.4M |
| eth100_btc50_bybit_long | 120s | -9.3474 | -9.4377 | $3.5M |
| eth100_btc50_liq2_120_bybit300 | 120s | 4.6600 | 4.5698 | $2.3M |
| current_hybrid | 300s | -2.2403 | -2.3059 | $23.4M |
| eth100_btc50_bybit_long | 300s | -18.4875 | -18.5532 | $3.5M |

Interpretation:

```text
30s symbol-specific threshold is robustly better, including public_extra.
120s Bybit 5s is strong on train/validation but weak on public_extra.
120s liq2 looks more robust than Bybit on public_extra.
300s Bybit improves overall, but public_extra is much worse than the current baseline.
```

Decision after this screen:

```text
Do not blindly adopt eth100_btc50_bybit_long.
Promote 30s symbol-specific threshold as the strongest candidate.
Investigate liq2 for 120s/300s before changing long horizons.
```

Running next:

```text
public 6-month stride=10 v3 with eth100_btc50_liq2_long and related combinations
```

Next if the candidate survives:

```text
1. full public stride=10 check
2. exact validation for selected candidate horizons
3. update task2_solution.py only after the evidence is strong
```
