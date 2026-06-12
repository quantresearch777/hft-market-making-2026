# HFT HW 1, Task 3

Task 3 builds a **large liquidation reaction filter** for Binance trades.

The idea is simple:

1. define a large liquidation by train-set notional percentiles;
2. visualize how Binance trade markouts behave during the next 300 seconds;
3. filter trades that happen shortly after a large liquidation in the same direction;
4. measure train/validation Score for `tau = 30s, 120s, 300s`;
5. compare with no-filter and Task 2 baselines.

## Files

- `src/task3_solution.py` - submission entry point. It exposes `predict(trades, bbo, liq_binance, liq_bybit)`.
- `src/task3_common.py` - data loading, markout, scoring, and evaluation helpers.
- `src/task3_research.py` - full EDA/event-study/grid-search script.
- `src/task3_age_band_grid.py` - experimental age-band grid for post-liquidation reaction windows.
- `src/task3_guard_candidates.py` - focused experimental return-guard candidate runner.
- `tests/test_task3_solution.py` - unit tests for same-direction filtering, window boundary, and Bybit +200 ms delay.
- `reports/task3_report.md` - final readable report.
- `reports/experiments/experiment_log.md` - record of tried alternatives and decisions.
- `reports/tables/` - generated metrics tables.
- `reports/figures/` - generated event-study plots.
- `notebooks/task3_large_liquidation_reaction_filter_executed.ipynb` - executed notebook handoff.

## Final Result

The filter was tested with train q90/q95/q99 liquidation-notional thresholds and 30s/60s windows on full train/validation. I tested both interpretations of "direction":

- taker trade side equals liquidation side;
- maker fill side equals liquidation side, meaning taker trade side is opposite to liquidation side.

The best final candidate is horizon-specific:

```text
30s threshold = train global q99 notional ~= 196,940 USD, window = 60s
120s threshold = train global q95 notional ~= 38,930 USD, window = 30s
300s threshold = train global q95 notional ~= 38,930 USD, window = 30s
direction = maker fill side matches liquidation side
```

Important finding: `trades.side` is taker side, but the score is maker PnL. The event study shows taker-same-direction trades after large liquidations have positive maker markout, while taker-opposite-direction trades are toxic. Therefore the final filter uses the maker-side interpretation and improves `no_filter` on full validation for 30s, 120s, and 300s:

```text
30s:  +0.0367 bps
120s: +0.1122 bps
300s: +0.2045 bps
```

This is documented in `reports/task3_report.md`.

Additional research branches are saved under `reports/experiments/`. The final report includes robustness tables by split, horizon, symbol, and daily score distribution.

## Data Requirements

Raw market data is not committed to this repository. The notebook and scripts expect the course dataset to be available locally, and the dataset location should be passed through the `--data-root` argument when reproducing the full run.

## Run

Smoke run:

```bash
python src/task3_research.py \
  --data-root /path/to/course_dataset \
  --output-dir reports \
  --event-start 2025-12-01 \
  --event-end 2025-12-03 \
  --start 2025-12-01 \
  --end 2025-12-03 \
  --smoke
```

Full train/validation run:

```bash
bash scripts/run_task3_full_server.sh
```
