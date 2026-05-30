# Task 2 Research Follow-up

This note records the second research pass after the initial liquidation-pressure baseline.

## Update After Later Research

This document is historical. The first hybrid described below was later improved.

Current implemented rule:

```text
30s  -> BTC return5s_gt_50, ETH return5s_gt_100
120s -> liq2s_d200_gt_2m AND return5s_gt_20
300s -> liq2s_d200_gt_2m
```

The later candidate and its public-regime checks are documented in:

```text
reports/task2_experiment_log.md
reports/task2_candidate_improvement_round3.md
```

## What Was Tested

I tested four families of ideas:

- Liquidation pressure windows: 100 ms, 250 ms, 500 ms, 1 s, 2 s, 5 s.
- Bybit delay variants: 0 ms, 100 ms, 200 ms, 500 ms, 1 s.
- Non-liquidation microstructure features: recent trade-flow, recent side-aware return, spread, top-of-book imbalance, notional filters.
- Rule combinations: return OR liquidation, return AND liquidation, and horizon-specific rules.

The broad search was done with sampled trades for speed. The promising ideas were then checked with heavier exact runs.

## Main Finding

The most useful new idea was a short-term reversal filter for the 30-second horizon:

```text
side_aware_return_5s = trade_side * mid_return_over_previous_5_seconds
keep if side_aware_return_5s > 50 bps
```

Interpretation:

```text
For a taker buy / maker sell, keep only after a strong upward move.
For a taker sell / maker buy, keep only after a strong downward move.
```

This is not future-looking: it uses only BBO history before the trade timestamp.

## Important False Lead

On sampled validation, the 5-second return rule looked very strong for all horizons.

However, an exact one-day smoke run showed that using it for 120s and 300s can be dangerous:

```text
2026-02-01 exact smoke:
30s   positive
120s  strongly negative
300s  strongly negative
```

So I did not use the return rule for all horizons. This is a useful lesson: sampled research is good for idea discovery, but exact markout checks decide the final implementation.

## Final Hybrid Rule

The current `predict` uses:

```text
30s  -> side-aware 5-second return reversal
120s -> original liquidation-pressure baseline
300s -> original liquidation-pressure baseline
```

This keeps the robust original behavior for longer horizons while improving the short horizon.

## Official Exact Results

Official period:

```text
train:      2025-12-01 -> 2026-01-31
validation: 2026-02-01 -> 2026-02-28
```

Old baseline overall:

| horizon | score | pnl_kept | kept turnover/day |
|---:|---:|---:|---:|
| 30s | 5.3162 | 5.2548 | 355.1M |
| 120s | 11.6928 | 11.7166 | 355.1M |
| 300s | 12.4354 | 12.5126 | 355.1M |

Hybrid overall:

| horizon | score | pnl_kept | kept turnover/day |
|---:|---:|---:|---:|
| 30s | 29.7368 | 29.6755 | 43.2M |
| 120s | 11.6928 | 11.7166 | 355.1M |
| 300s | 12.4354 | 12.5126 | 355.1M |

Validation split for the hybrid:

| horizon | score | pnl_kept | kept turnover/day |
|---:|---:|---:|---:|
| 30s | 42.5688 | 42.5224 | 84.2M |
| 120s | 11.5558 | 11.5232 | 351.1M |
| 300s | 12.5831 | 12.6077 | 351.1M |

## Conclusion

The 30-second horizon benefits from a short-term reversal filter. The longer horizons remain better served by the original liquidation-pressure baseline.

I would not move to ML yet. The rule-based hybrid is easier to explain, avoids model-training leakage risk, and already improves the official exact 30s score materially while preserving 120s and 300s.

## Full Public Follow-up

A later exact run over all 179 public days confirmed that the hybrid still improves the 30s aggregate:

| horizon | baseline score | hybrid score |
|---:|---:|---:|
| 30s | 3.7693 | 20.0623 |
| 120s | 7.1584 | 7.1584 |
| 300s | 7.9808 | 7.9808 |

The caveat is that March-April is weaker for the 30s return-reversal rule. See `reports/task2_creative_research_round2.md` for the regime diagnostics.
