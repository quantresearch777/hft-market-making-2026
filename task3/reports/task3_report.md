# Task 3: Large Liquidation Reaction Filter

## Goal

Build and evaluate a filter for Binance trades after large liquidation events.

The submitted filter marks a trade as filtered (`f_i = 1`) when:

- a large Binance or Bybit liquidation happened before the trade;
- the trade falls inside the selected reaction window;
- the passive maker fill direction matches the liquidation direction;
- equivalently, because `trades.side` is taker side, the taker trade side is opposite to the liquidation side;
- Bybit liquidation timestamps are shifted by `+200 ms` before matching.

## Data

Raw market data is not committed to this repository. The notebook and scripts expect the course dataset to be available locally, and the dataset location should be configured through the `--data-root` argument when reproducing the full run.

## Large Liquidation Thresholds

Train-set liquidation notional percentiles:

```text
 symbol exchange  event_count        q90        q95         q99  max_notional
    all      all       361875 16684.1334 38929.5275 196940.3595  1.548257e+07
btcusdt  binance        63660 16820.3480 39357.2719 171672.7320  1.219688e+07
btcusdt    bybit       124465 18679.6330 43865.2000 237942.0570  3.439243e+06
ethusdt  binance        76634 13563.8116 31441.5122 157971.0000  1.548257e+07
ethusdt    bybit        97116 16288.3790 38134.1440 208399.3401  3.031573e+06
```

## Reaction EDA

For each large liquidation, I measured average Binance trade maker markout with `tau = 30s` from `0` to `300` seconds after liquidation. The curves are split into:

- trades in the same direction as liquidation;
- trades in the opposite direction.

Largest absolute same-direction reaction in the generated event study: `q90` around `20-30` seconds, average 30s markout `21.2847` bps.

Interpretation:

`trades.side` is the taker side, while markout is measured for the passive maker fill. On the full train event study, taker-same-direction trades have positive average 30s maker markout (`4.7468` bps across bins), while taker-opposite-direction trades are negative on average (`-3.9152` bps across bins). Therefore the final filter uses the maker-side interpretation: filter trades where the maker fill direction matches the liquidation direction, equivalently where taker trade side is opposite to liquidation side.

## Metrics

The score is:

```text
Score(tau) = PnL_kept(tau) - PnL_all(tau)
```

`no_filter` has score `0` by construction because `PnL_kept = PnL_all` when no trades are filtered.

Best Task 3 candidate selected from full train/validation robustness: `task3_final_horizon_specific`.

Final horizon-specific parameters:

```text
30s  -> q99 notional threshold ~= 196,940 USD, 60s reaction window
120s -> q95 notional threshold ~= 38,930 USD, 30s reaction window
300s -> q95 notional threshold ~= 38,930 USD, 30s reaction window
```

```text
                    strategy      split  horizon_s   pnl_all  pnl_kept  pnl_filtered     score  kept_turnover_per_day  constraint_ok
                   no_filter      train         30 -0.069644 -0.069644           NaN  0.000000           2.206225e+10           True
                   no_filter      train        120  0.055228  0.055228           NaN  0.000000           2.206225e+10           True
                   no_filter      train        300  0.106595  0.106595           NaN  0.000000           2.206225e+10           True
                   no_filter validation         30 -0.046404 -0.046404           NaN  0.000000           2.716903e+10           True
                   no_filter validation        120 -0.032598 -0.032598           NaN  0.000000           2.716903e+10           True
                   no_filter validation        300  0.024515  0.024515           NaN  0.000000           2.716903e+10           True
task3_final_horizon_specific      train         30 -0.069644 -0.023063     -1.049745  0.046581           2.106128e+10           True
task3_final_horizon_specific      train        120  0.055228  0.174961     -1.500202  0.119733           2.048534e+10           True
task3_final_horizon_specific      train        300  0.106595  0.171888     -0.741612  0.065293           2.048534e+10           True
task3_final_horizon_specific validation         30 -0.046404 -0.009730     -0.870818  0.036674           2.601189e+10           True
task3_final_horizon_specific validation        120 -0.032598  0.079595     -1.336677  0.112193           2.501678e+10           True
task3_final_horizon_specific validation        300  0.024515  0.228977     -2.352067  0.204462           2.501678e+10           True
              task2_baseline      train         30 -0.069644  4.488060     -0.144576  4.557704           3.568544e+08           True
              task2_baseline      train        120  0.055228 11.802612     -0.137908 11.747383           3.568544e+08           True
              task2_baseline      train        300  0.106595 12.470397     -0.096676 12.363802           3.568544e+08           True
              task2_baseline validation         30 -0.046404  6.980600     -0.138396  7.027003           3.510792e+08           True
              task2_baseline validation        120 -0.032598 11.523165     -0.183877 11.555762           3.510792e+08           True
              task2_baseline validation        300  0.024515 12.607652     -0.140213 12.583137           3.510792e+08           True
```

Task 2 baseline is included as a reference because it was the previous homework filter. It is not used as the Task 3 final answer: Task 3 is specifically about the large-liquidation reaction rule, while the Task 2 filter is a broader short-term reversal/liquidation-pressure filter and keeps a much smaller turnover slice.

## Robustness Checks

The final rule is positive on both train and validation for all three horizons. Positive symbol-day rate is above 60% for each split/horizon, so the result is not driven by a single day.

```text
     split  horizon_s    score  pnl_filtered  kept_turnover_per_day  positive_symbol_day_rate  daily_score_p10  daily_score_median  daily_score_p90
     train         30 0.046581     -1.049745           2.106128e+10                  0.669355        -0.088669            0.022440         0.235042
     train        120 0.119733     -1.500202           2.048534e+10                  0.677419        -0.258720            0.057547         0.486522
     train        300 0.065293     -0.741612           2.048534e+10                  0.661290        -0.898617            0.156068         0.847691
validation         30 0.036674     -0.870818           2.601189e+10                  0.642857        -0.111619            0.042919         0.196734
validation        120 0.112193     -1.336677           2.501678e+10                  0.607143        -0.358331            0.056227         0.556846
validation        300 0.204462     -2.352067           2.501678e+10                  0.660714        -0.619772            0.148309         1.194031
```

Symbol-level summary:

```text
     split  symbol  horizon_s     score  pnl_filtered  positive_symbol_day_rate
     train btcusdt         30  0.036931     -0.883838                  0.629032
     train btcusdt        120  0.029448     -0.388577                  0.596774
     train btcusdt        300 -0.005281      0.104484                  0.645161
     train ethusdt         30  0.056448     -1.218435                  0.709677
     train ethusdt        120  0.212488     -2.582786                  0.758065
     train ethusdt        300  0.137919     -1.565603                  0.677419
validation btcusdt         30  0.061733     -1.452558                  0.607143
validation btcusdt        120  0.077305     -1.042959                  0.607143
validation btcusdt        300  0.209499     -2.509782                  0.714286
validation ethusdt         30  0.006120     -0.036014                  0.678571
validation ethusdt        120  0.151829     -1.705063                  0.607143
validation ethusdt        300  0.197361     -2.154257                  0.607143
```

One residual risk is BTC train at 300s, where the symbol-level score is slightly negative. I kept the horizon-specific q95/30s rule because the aggregate train 300s score is positive, validation BTC/ETH 300s are both strongly positive, and more aggressive q90 validation winners had negative train scores.

## Additional Research

All experiment branches are saved in `reports/experiments/experiment_log.md`.

Main alternatives tested:

- broader source/threshold/window grid;
- Binance-only q99 full-period check;
- symbol-specific liquidation thresholds;
- return-guard overlays;
- synthetic incremental `30-60s` reaction window.

The late `30-60s` window did not beat the final early-reaction rule:

```text
                   strategy  horizon_s     score  pnl_filtered  kept_turnover_per_day
synthetic_maker_q90_30s_60s         30 -0.027288      0.463463           2.578882e+10
synthetic_maker_q90_30s_60s        120 -0.049960      0.900900           2.578882e+10
synthetic_maker_q90_30s_60s        300  0.010397     -0.169751           2.578882e+10
synthetic_maker_q95_30s_60s         30 -0.009951      0.197461           2.610382e+10
synthetic_maker_q95_30s_60s        120 -0.012908      0.283720           2.610382e+10
synthetic_maker_q95_30s_60s        300  0.017383     -0.401460           2.610382e+10
synthetic_maker_q99_30s_60s         30  0.004105     -0.309763           2.675202e+10
synthetic_maker_q99_30s_60s        120 -0.006654      0.394298           2.675202e+10
synthetic_maker_q99_30s_60s        300 -0.009505      0.634270           2.675202e+10
```

## Deliverables

- `src/task3_solution.py` - submission function `predict(trades, bbo, liq_binance, liq_bybit)`.
- `src/task3_research.py` - EDA and grid-search script.
- `reports/tables/` - reproducible metric tables.
- `reports/figures/` - event-study plots.
- `notebooks/task3_large_liquidation_reaction_filter.ipynb` - notebook handoff.
