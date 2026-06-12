# Task 3 Experiment Log

This log records the main research branches tried for the large-liquidation reaction filter.

## Final Candidate

Final submitted rule: `task3_final_horizon_specific`.

| horizon | rule | validation score | decision |
|---:|---|---:|---|
| 30s | maker-side liquidation filter, global q99 notional, 60s window | 0.036674 | keep |
| 120s | maker-side liquidation filter, global q95 notional, 30s window | 0.112193 | keep |
| 300s | maker-side liquidation filter, global q95 notional, 30s window | 0.204462 | keep |

The final rule is chosen for positive train and validation scores at all three horizons, high kept turnover, and simple interpretation.

## Experiments

### exp00_current_final

Path: `reports/experiments/exp00_current_final/`

Snapshot of the first stable Task 3 solution, report, figures, and key tables.

### exp01_advanced_week

Path: `reports/experiments/exp01_advanced_week/`

Tested broader source/threshold/window choices on a quick train-week screen:

- sources: both, Binance-only, Bybit-only;
- quantiles: q85, q90, q95, q97, q99;
- windows: 10, 20, 30, 45, 60, 90, 120 seconds.

Useful finding: very short windows could improve 30s on a week sample, and Binance q99 looked interesting for 300s. Not promoted directly because week-only results were unstable for 120s/300s.

### exp02_full_binance_q99

Path: `reports/experiments/exp02_full_binance_q99/`

Full-period check of the promising Binance-only q99 family.

Best validation scores:

| horizon | best Binance q99 variant | validation score |
|---:|---|---:|
| 30s | `adv_binance_q99_win45` | 0.011651 |
| 120s | `adv_binance_q99_win60` | 0.049008 |
| 300s | `adv_binance_q99_win90` | 0.073833 |

Decision: not promoted. It is positive, but weaker than final horizon-specific rule.

### exp03_symbol_week

Path: `reports/experiments/exp03_symbol_week/`

Tested symbol-specific liquidation thresholds for BTC and ETH.

Decision: not promoted. Symbol thresholds improved some short-horizon week cases, but were weak or negative for 120s and 300s in the quick screen.

### exp04_guard_week

Path: `reports/experiments/exp04_guard_week/`

Tested return-guard overlays on top of q95/q99 liquidation filters.

Useful finding: some guards improved 30s on the quick train-week screen, especially `ret10s < 0` or `ret10s < -20`.

Decision: not promoted. The promising effect was mostly short-horizon and week-local; full-period focused run was stopped because the full trade stream made this branch too expensive relative to the time budget.

### exp05_incremental_windows

Path: `reports/experiments/exp05_incremental_windows/`

Used existing full-grid daily metrics to synthetically reconstruct the incremental `30-60s` reaction window from `0-30s` and `0-60s` filters.

Best validation scores:

| strategy | 30s | 120s | 300s |
|---|---:|---:|---:|
| `synthetic_maker_q90_30s_60s` | -0.027288 | -0.049960 | 0.010397 |
| `synthetic_maker_q95_30s_60s` | -0.009951 | -0.012908 | 0.017383 |
| `synthetic_maker_q99_30s_60s` | 0.004105 | -0.006654 | -0.009505 |

Decision: not promoted. The late `30-60s` slice alone is weak; the signal is mainly in the early post-liquidation reaction.

### Full Guard Candidate Attempt

Script: `src/task3_guard_candidates.py`

Tried to launch a full-period focused guard-candidate run on the server. It was stopped because even the focused version was bottlenecked by full-day trade/BBO loading and markout computation. The partial run did not produce a complete metrics table, so it is recorded as an attempted branch, not as an evaluated candidate.

## Current Decision

Keep the horizon-specific liquidation-only rule. It is not the highest possible score if one reuses the Task 2 reversal filter, but it is the cleanest answer to Task 3 because it directly implements and evaluates the requested large-liquidation reaction filter.
