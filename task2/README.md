# HFT HW 1, Task 2

Task 2 is a trade-filtering / markout problem. For every Binance trade the strategy returns:

```text
0 = keep the trade
1 = filter the trade
```

The goal is to keep trades with better maker markout PnL while satisfying the turnover constraint. This is not a full portfolio backtester; there is no explicit cash, inventory, fee or rebate model in my code. I optimize the task evaluator's markout metric directly.

## Executive Summary

How to read the numbers:

```text
pnl_all  = markout PnL if we keep every trade, i.e. no-filter baseline
pnl_kept = markout PnL on trades selected by the strategy
score    = pnl_kept - pnl_all
```

For the no-filter baseline, we keep every trade. Therefore the kept set is exactly the same as the full trade set:

```text
no-filter: kept trades = all trades
therefore: pnl_kept = pnl_all
therefore: score = pnl_kept - pnl_all = 0
```

This does not mean the no-filter PnL is zero. It means the no-filter strategy has zero improvement over itself. The final strategy is useful if `pnl_kept` is much better than `pnl_all`, while kept turnover stays above the required threshold.

Final submitted strategy:

| horizon | final rule | reason |
|---:|---|---|
| 30s | BTC `return5s > 50 bps`, ETH `return5s > 100 bps` | short-term maker reversal signal; ETH needs stricter selection |
| 120s | `liq2s_d200 > 2m` AND `return5s > 20 bps` | liquidation pressure plus a soft return guard improved 120s robustness |
| 300s | `liq2s_d200 > 2m` | plain 2s liquidation pressure was more robust than combo guards on public-extra |

Baseline vs final balanced strategy on the public 6-month stride=10 screen:

| horizon | no-filter pnl_all | balanced pnl_kept | improvement score |
|---:|---:|---:|---:|
| 30s | -0.0754 | 35.1172 | +35.1926 |
| 120s | -0.0200 | 27.6819 | +27.7020 |
| 300s | 0.0354 | 18.6545 | +18.6190 |

Comparison with the previous conservative hybrid:

| horizon | conservative score | balanced/final score |
|---:|---:|---:|
| 30s | 20.6530 | 35.1926 |
| 120s | 6.9457 | 27.7020 |
| 300s | 7.7372 | 18.6190 |

Exact first-week check, full trade stream:

```text
2026-02-01 -> 2026-02-07, trade_stride = 1
```

| horizon | no-filter pnl_all | balanced pnl_kept | improvement score | kept turnover/day |
|---:|---:|---:|---:|---:|
| 30s | 0.0378 | 76.5131 | +76.4753 | $65.3M |
| 120s | 0.0636 | 42.9284 | +42.8648 | $31.4M |
| 300s | 0.0583 | 18.3293 | +18.2710 | $71.1M |

## Strategy Variants

I treated the final strategy as the balanced submission. Other variants were useful for research but not selected.

| variant | description | public 6m 30s | public 6m 120s | public 6m 300s | public-extra note | decision |
|---|---|---:|---:|---:|---|---|
| No filter | keep all trades | 0 by construction | 0 by construction | 0 by construction | reference only | not a strategy |
| Conservative | old hybrid: 30s return filter, 120s/300s 1s liquidation baseline | 20.6530 | 6.9457 | 7.7372 | stable but weaker | replaced |
| Intermediate | BTC/ETH 30s + plain `liq2` for 120s/300s | 35.1926 | 18.4605 | 18.6190 | improves all horizons | improved further |
| Balanced / final | BTC/ETH 30s + `liq2 AND return20` for 120s + plain `liq2` for 300s | 35.1926 | 27.7020 | 18.6190 | best risk/reward found | selected |
| Aggressive | use `return5s > 50 bps` for 120s/300s too | 35.1926 | 30.0280 | 32.0859 | fails public-extra on 120s/300s | rejected |
| Bybit-heavy | strong Bybit-only liquidation pressure | 35.1926 | 19.3317 | 18.6068 | public-extra 120s/300s was negative | rejected |

Why the aggressive variant was not selected:

```text
It had the best overall 120s/300s score, but public-extra was bad:
120s = -9.8268
300s = -19.8047
```

So I selected the balanced version: slightly lower overall score than aggressive, but much better public-extra behavior.

## Current Rule Details

The final submission function is:

```text
src/task2_solution.py::predict(trades, bbo, liq_binance, liq_bybit)
```

The 30s feature is:

```text
side_aware_return_5s = trade_side_i * mid_return_over_previous_5_seconds

BTC: keep if side_aware_return_5s > 50 bps
ETH: keep if side_aware_return_5s > 100 bps
```

The liquidation feature is:

```text
pressure_i = trade_side_i * (binance_liq_signed_2s + bybit_liq_signed_2s_shifted_200ms)
liq2_keep_i = pressure_i > 2_000_000
```

For 120s only:

```text
return_guard_i = side_aware_return_5s > 20 bps
120s keep_i = liq2_keep_i AND return_guard_i
```

For 300s:

```text
300s keep_i = liq2_keep_i
```

Important conventions:

- trade side is the Binance taker side;
- liquidation side is treated as directional liquidation pressure;
- Bybit liquidations are shifted forward by 200 ms;
- all features use only information available before or at the trade timestamp;
- no explicit fees/rebates are added because the task evaluator is a markout filter evaluator.

## Files To Review

- `src/task2_solution.py` - final submission function.
- `notebooks/task2_strategy_handoff_github_preview.ipynb` - GitHub-preview-friendly notebook summary.
- `notebooks/task2_strategy_handoff.md` - Markdown fallback with the same summary.
- `notebooks/task2_strategy_handoff_executed.ipynb` - full executed notebook with tables and charts.
- `reports/task2_experiment_log.md` - full experiment log with hypotheses, results, pros/cons and decisions.
- `reports/task2_candidate_improvement_round3.md` - final candidate memo.
- `reports/tables/` - result tables used in the report.
- `tests/test_task2_solution.py` - unit tests for the signal logic.

## Reproducibility

The dataset is not committed. On the server I used the existing Task 1 data path:

```text
/root/CMF/Task_1  # existing dataset
/root/CMF/Task_2  # this task's code, reports, notebook, outputs
```

Example run:

```bash
python src/task2_evaluate.py \
  --data-root /root/CMF/Task_1 \
  --output-dir outputs \
  --start 2025-11-01 \
  --end 2026-04-29
```

Local checks:

```bash
python -m unittest discover -s tests -v
python -m py_compile src/task2_solution.py src/task2_evaluate.py src/task2_variant_research.py
```

Validation status:

```text
local tests: 8/8 passed
server tests: 8/8 passed
```
