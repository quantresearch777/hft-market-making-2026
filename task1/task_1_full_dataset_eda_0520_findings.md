# Task 1 Extended Full-Dataset EDA Findings

Dataset version: `liquidation_task_0520`, 2025-11-01 to 2026-04-28.

Primary deliverables:

- `notebooks/task_1_full_dataset_eda_0520_executed.ipynb`
- `notebooks/task_1_full_dataset_eda_0520.html`
- `outputs_full_eda_0520/tables/*.csv`

## Coverage

The extended EDA uses the full archive, not a 1-3 day sample.

Total rows scanned: 2,598,616,800 across 8 parquet files.

Date coverage from parquet metadata:

- first timestamp: 2025-11-01 00:00:00.015 UTC
- last timestamp: 2026-04-28 23:59:59.990 UTC

Rows by stream:

- Binance trades BTCUSDT: 804,035,257
- Binance trades ETHUSDT: 1,370,451,261
- Binance BBO BTCUSDT: 202,748,814
- Binance BBO ETHUSDT: 220,134,233
- Binance liquidations BTCUSDT: 236,067
- Binance liquidations ETHUSDT: 270,796
- Bybit liquidations BTCUSDT: 438,216
- Bybit liquidations ETHUSDT: 302,156

## What The Notebook Answers

The notebook covers the starting questions from the assignment:

- Shape of the data: rows per source, symbol, day, and hour.
- Event timing: event-rate patterns, gaps, repeated timestamps, burstiness.
- Distributions: prices, sizes, notionals, spreads, side balance, heavy tails.
- Cross-source relationships: Binance trades versus Binance BBO; liquidation events versus Binance mid-price and trade flow; Binance and Bybit liquidation alignment.
- Conventions: timestamp units, trade side meaning, liquidation side meaning, and the required +200ms Bybit delay.
- Weird points: repeated trade timestamps, sparse and heavy-tailed liquidations, BBO gaps, and the need for as-of joins.

## Key Findings

ETH has far more raw trade events than BTC, while total traded notional is comparable in scale:

- BTC Binance trade notional: about 2.40T USDT
- ETH Binance trade notional: about 2.17T USDT

Trade and liquidation notionals are strongly heavy-tailed. For example, median daily p99.9 trade notional is much larger than the median trade size, and liquidation tails are even more extreme.

The Binance trade side convention is confirmed empirically:

- BTC taker buys are closer to ask about 98.16% of the time.
- BTC taker sells are closer to bid about 98.21% of the time.
- ETH taker buys are closer to ask about 97.53% of the time.
- ETH taker sells are closer to bid about 97.51% of the time.

Liquidations are sparse compared with trades and BBO updates, but they cluster during stress. They usually occur after strong same-direction price movement.

Post-liquidation behavior is conditional. It is not a simple "liquidation means continuation" rule. Some buckets show continuation, while others show exhaustion or reversal depending on symbol, source, side, size, and horizon.

Bybit liquidations are useful as cross-exchange stress context only after applying the required +200ms availability shift. The alignment tables show measurable liquidation notional on the other exchange around events.

## Implementation Notes

The raw dataset is too large for naive pandas-first EDA. The pipeline uses Polars/parquet scans on the server and writes compact CSV tables for the notebook.

The relationship analysis is full-data but split by month and symbol for memory stability. This is not sampling; it is chunked full-dataset processing.

Main pipeline scripts:

- `src/task1_full_eda.py`
- `scripts/run_full_eda_extended_parallel.sh`
- `scripts/combine_full_eda_outputs.py`
- `scripts/make_task1_full_eda_notebook.py`

## Caveats

The dataset contains BBO only, not full depth or queue position. Any future maker-fill analysis is therefore an approximation.

Same-timestamp trades are common and expected in high-frequency exchange feeds. They should not be treated as automatic exact duplicates.

Bybit liquidation timestamps must be shifted by +200ms before being used as Binance-time predictors.

For modeling or trade filtering, validation must be temporal. Random splits would leak market regimes across train and validation.
