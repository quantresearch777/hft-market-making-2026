# Task 2 Attack Plan

This is the living plan for Task 2. Update it when the baseline, server results or submission requirements change.

## Goal

Build a simple baseline trade filter for Binance trades.

For each trade:

```text
0 = keep trade
1 = filter trade
```

Then evaluate whether the kept trades have better maker markout PnL than all trades, while satisfying:

```text
KeptTurnoverPerDay >= 500,000 USD/day
```

## What This Task Is

This is a lightweight signal backtest / markout evaluator.

It is not a full event-driven backtester with:

- order manager;
- portfolio lifecycle;
- queue position simulation;
- inventory optimization;
- full order book replay.

The task assumes we evaluate Binance trades as potential maker fills and classify them as kept or filtered.

## Submission Core

Main submission file:

```text
src/task2_solution.py
```

Required function:

```python
predict(trades, bbo, liq_binance, liq_bybit) -> dict[int, np.ndarray]
```

Expected output:

```text
{
    30: flags_30s,
    120: flags_120s,
    300: flags_300s,
}
```

Each `flags_*` array must have the same length as `trades`.

## Current Strategy

The current implementation is a horizon-specific hybrid selected after rule grids,
public-regime checks and exact stress tests.

For 30s, use a symbol-specific short-term return reversal signal:

```text
side_aware_return_5s = trade_side * mid_return_over_previous_5_seconds

BTC keep if side_aware_return_5s > 50 bps
ETH keep if side_aware_return_5s > 100 bps
```

For 120s and 300s, use a more selective 2-second liquidation-pressure signal.
For 120s only, add a soft 5-second return-reversal guard.

Liquidation feature:

```text
signed_pressure =
    Binance liquidation pressure over last 2s
  + Bybit liquidation pressure over last 2s shifted by +200ms
```

Side-aware pressure:

```text
pressure_i = trade_side_i * signed_pressure_i
```

Where:

```text
trade_side_i = +1 for taker buy / maker sell
trade_side_i = -1 for taker sell / maker buy
```

Liquidation rule:

```text
filter_i = 1 if pressure_i <= threshold
keep_i   = 0 otherwise
```

120s return guard:

```text
return_guard_i = trade_side_i * mid_return_5s_i > 20 bps
120s keep_i = liquidation_keep_i AND return_guard_i
```

Current liquidation threshold:

```text
threshold = 2,000,000
```

Interpretation:

```text
30s uses short-term reversal after a large side-aware move, with stricter ETH selection.
120s keeps trades when both recent 2s liquidation pressure and softer 5s return reversal agree.
300s keeps trades when recent 2s liquidation pressure is favorable enough for the maker side.
```

## Evaluator

Main evaluator file:

```text
src/task2_evaluate.py
```

For each Binance trade:

```text
1. find future Binance BBO mid at t + horizon
2. compute maker PnL in bps
3. apply keep/filter signal
4. aggregate metrics
```

Horizons:

```text
30s, 120s, 300s
```

Maker PnL:

```text
pnl_i = -s_i * (future_mid_i - trade_price_i) / trade_price_i * 10_000 + 0.5
```

Where:

```text
s_i = +1 for taker buy / maker sell
s_i = -1 for taker sell / maker buy
```

Metrics:

```text
PnL_all
PnL_kept
PnL_filtered
Score = PnL_kept - PnL_all
KeptTurnoverPerDay
```

## Data Handling

Do not duplicate the dataset.

Use existing Task 1 dataset path on the server:

```text
/root/CMF/Task_1
```

The evaluator accepts:

```bash
--data-root /root/CMF/Task_1
```

It can find data under:

```text
liquidation_task/data
liquidation_task/liquidation_task/data
liquidation_task_0520/data
liquidation_task_0520/liquidation_task/data
```

## Compute Plan

Local machine:

```text
write code
prepare reports
prepare notebook
avoid heavy parquet computations
```

Server:

```text
run Polars parquet scans
process day/symbol chunks
use NumPy searchsorted for markout and rolling pressure
write CSV metrics
```

Why not C++/Rust yet:

- Task 2 is not full event replay.
- Bottleneck is parquet IO and vectorized joins/searches.
- Polars already uses Rust internally.
- Python + Polars + NumPy is faster to develop and sufficient for this task.

Rust/C++ may become useful later for:

- full event replay;
- queue simulation;
- latency modeling;
- live execution;
- custom high-performance feature generation.

## Validation Splits

Official split from `description.md`:

```text
train:      2025-12-01 -> 2026-01-31
validation: 2026-02-01 -> 2026-02-28
```

Full public dataset from `liquidation_task_0520`:

```text
2025-11-01 -> 2026-04-28
```

Evaluator split labels:

```text
train
validation
public_extra
```

## Success Criteria

Baseline is acceptable if:

```text
Score > 0
PnL_kept > PnL_all
PnL_filtered < PnL_kept
KeptTurnoverPerDay >= 500,000 USD/day
```

Check this by:

- horizon;
- split;
- symbol if needed;
- day-level robustness.

## If Baseline Is Weak

Improve in this order:

1. Try more pressure windows:

```text
200ms, 1s, 5s, 30s
```

2. Try source variants:

```text
Binance-only
Bybit-only
combined
```

3. Try horizon-specific thresholds:

```text
threshold_30s
threshold_120s
threshold_300s
```

4. Add BBO features:

```text
spread
top imbalance
microprice offset
```

5. Add recent trade-flow features:

```text
signed trade notional
buy/sell imbalance
short-term returns
volatility
```

6. Try simple ML:

```text
logistic regression
LightGBM / CatBoost if available
```

Do not optimize classification accuracy. Optimize markout metrics and turnover constraint.

## Current Files

```text
README.md
TASK2_ATTACK_PLAN.md
src/task2_solution.py
src/task2_evaluate.py
notebooks/task2_baseline.ipynb
reports/task2_baseline_report.md
reports/task2_papers_notes.md
reports/market_making_research_2026.md
scripts/run_task2_smoke_server.sh
scripts/run_task2_full_server.sh
```

## Next Step

Server access is working.

Completed:

```text
1. copied Task 2 code to /root/CMF/Task_2
2. ran smoke test on 2026-02-01
3. ran official train/validation evaluation on 2025-12-01 -> 2026-02-28
4. downloaded outputs to D:\Python\CMF\HFT_School\Task_2\outputs_official
5. updated reports/task2_baseline_report.md with actual metrics
6. ran missing public-extra months and combined full public 6-month metrics
7. downloaded outputs to D:\Python\CMF\HFT_School\Task_2\outputs_public_6m
```

Official run result:

```text
Score is positive for 30s, 120s and 300s on both train and validation.
KeptTurnoverPerDay is about $355m/day overall, far above the $500k/day constraint.
```

Full public 6-month result:

```text
Score is positive for 30s, 120s and 300s over all 179 public days.
KeptTurnoverPerDay is about $320m/day overall.
Public-extra months are positive in aggregate, but March-April alone is weaker for 120s/300s.
```

Latest research update:

```text
1. broad grid search tested liquidation windows, Bybit delays, trade-flow, BBO features and return features
2. sampled validation suggested return features were strong
3. exact smoke showed return features are risky for 120s/300s
4. final hybrid uses return reversal only for 30s and keeps liquidation baseline for 120s/300s
5. dense ML screen found promising 120s/300s ridge-ranker candidates, but not enough evidence yet to replace the exact-validated rule
```

Hybrid official exact result:

```text
30s score improved from 5.3162 to 29.7368.
120s and 300s stayed unchanged versus the liquidation baseline.
```

ML follow-up:

```text
reports/task2_ml_professional_research.md

Best dense validation screen:
30s  ridge_classifier_positive score 24.0283
120s ridge_regressor_clip100   score 20.8555
300s ridge_regressor_clip100   score 17.3818

Decision:
Keep the exact-validated hybrid for now.
Treat ML 120s/300s as the next candidate for a full exact validation run.
```
