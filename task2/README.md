# HFT HW 1, Task 2

Task 2 builds a simple signal that filters Binance trades before evaluating maker markout PnL.

## Files

- `src/task2_solution.py` - submission function. It exposes `predict(trades, bbo, liq_binance, liq_bybit)`.
- `src/task2_evaluate.py` - local/server evaluator for public train and validation data.
- `reports/task2_baseline_report.md` - short explanation of the baseline and expected metrics.
- `reports/task2_research_followup.md` - follow-up grid search and hybrid-rule notes.
- `reports/task2_creative_research_round2.md` - robustness, regime and ML research summary.
- `reports/task2_ml_professional_research.md` - denser ML-ranker experiment and decision note.
- `reports/task2_experiment_log.md` - running experiment log with hypotheses, results, pros/cons and decisions.
- `reports/task2_candidate_improvement_round3.md` - current candidate improvements under deeper testing.
- `notebooks/task2_baseline.ipynb` - notebook wrapper for explanation and server execution.

## Important Data Note

The dataset is not duplicated in this folder. On the server, run the evaluator against the existing Task 1 dataset path.

Server layout:

```text
/root/CMF/Task_1  # existing dataset
/root/CMF/Task_2  # this task's code, reports, notebook, outputs
```

Example:

```bash
python src/task2_evaluate.py \
  --data-root /root/CMF/Task_1 \
  --output-dir outputs \
  --start 2025-11-01 \
  --end 2026-04-29
```

`--data-root` can point either to the folder that contains `liquidation_task_0520/`, `liquidation_task_0520_unpacked/`, `liquidation_task/`, or directly to the `data/` directory.

The evaluator reports three split labels:

- `train`: 2025-12-01 to 2026-01-31
- `validation`: 2026-02-01 to 2026-02-28
- `public_extra`: dates outside the official train/validation split in the 6-month public dataset

## Current Rule

The current submission function is horizon-specific:

```text
30s  -> symbol-specific side-aware 5-second return reversal
120s -> side-aware 2-second liquidation pressure with 5-second return guard
300s -> side-aware 2-second liquidation pressure
```

The 30s feature is:

```text
side_aware_return_5s = trade_side_i * mid_return_over_previous_5_seconds
BTC: filter_i = 1 if side_aware_return_5s <= 50 bps else 0
ETH: filter_i = 1 if side_aware_return_5s <= 100 bps else 0
```

The 120s/300s liquidation feature is:

```text
pressure_i = trade_side_i * (binance_liq_signed_2s + bybit_liq_signed_2s_shifted_200ms)
filter_i = 1 if pressure_i <= 2_000_000 else 0
```

For 120s only, the trade must also pass a softer return-reversal guard:

```text
return_guard_i = side_aware_return_5s > 20 bps
120s keep_i = liq2_keep_i AND return_guard_i
```

Where:

- trade side is the Binance taker side;
- liquidation side is the liquidation order side;
- Bybit liquidations are shifted forward by 200 ms before feature construction;
- the pure 2-second liquidation binary filter is returned for 300s.

This is intentionally a simple explainable hybrid rather than an overfit model.

## Current Checkpoints

Exact first-week check:

```text
2026-02-01 -> 2026-02-07, trade_stride = 1
```

| horizon | score | pnl kept | kept turnover/day |
|---:|---:|---:|---:|
| 30s | 76.4753 | 76.5131 | $65.3M |
| 120s | 42.8648 | 42.9284 | $31.4M |
| 300s | 18.2710 | 18.3293 | $71.1M |

Public 6-month stride=10 screen:

| horizon | previous hybrid score | current candidate score |
|---:|---:|---:|
| 30s | 20.6530 | 35.1926 |
| 120s | 6.9457 | 27.7020 |
| 300s | 7.7372 | 18.6190 |

## Local Checks

```bash
python -m unittest discover -s tests -v
python -m py_compile src/task2_solution.py src/task2_evaluate.py
```

## Server Sync

From Windows PowerShell:

```powershell
.\scripts\sync_task2_to_server.ps1
```

The sync script copies only code/notebook/reports/tests to `/root/CMF/Task_2`; it does not copy datasets, PDFs, docx files or generated outputs.
