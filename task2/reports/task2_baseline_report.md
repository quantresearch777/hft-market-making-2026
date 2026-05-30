# Task 2 Baseline Report

## Goal

Build a simple trade filter for Binance trades using liquidation data, then report:

- Score
- PnL_all
- PnL_kept
- PnL_filtered
- kept turnover per day

The turnover constraint is:

```text
KeptTurnoverPerDay >= 500,000 USD/day
```

## Selected Rule

The selected baseline is:

```text
pressure_i = s_i * (signed_binance_liq_1s + signed_bybit_liq_1s_shifted_200ms)
keep_i = pressure_i > 100,000
filter_i = pressure_i <= 100,000
```

Where:

- `s_i = +1` for taker buy / maker sell;
- `s_i = -1` for taker sell / maker buy;
- Bybit liquidation timestamps are shifted by `+200 ms`;
- signed liquidation notional is positive for `buy` liquidation orders and negative for `sell` liquidation orders.

## Intuition

The rule keeps trades when recent liquidation pressure is favorable for the maker side. It is side-aware, cross-exchange aware and respects the Bybit delay convention from the task statement.

## Server Run Summary

Official train/validation run:

```text
server path: /root/CMF/Task_2/outputs_official
local copy:  D:\Python\CMF\HFT_School\Task_2\outputs_official
data root:   /root/CMF/Task_1/liquidation_task_0520_unpacked/liquidation_task/data
period:      2025-12-01 -> 2026-02-28
```

Output files:

- `task2_daily_metrics.csv`
- `task2_summary_by_split.csv`
- `task2_summary_overall.csv`
- `run_config.json`
- `run.log`

## Official Train / Validation Metrics

The rule was selected from train data and checked on validation data. Metrics below are from the server-side evaluator in `src/task2_evaluate.py`.

| split | horizon_s | days | pnl_all | pnl_kept | pnl_filtered | score | kept_turnover_per_day | constraint_ok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 30 | 62 | -0.0696 | 4.4881 | -0.1446 | 4.5577 | $356,854,430 | yes |
| train | 120 | 62 | 0.0552 | 11.8026 | -0.1379 | 11.7474 | $356,854,430 | yes |
| train | 300 | 62 | 0.1066 | 12.4704 | -0.0967 | 12.3638 | $356,854,430 | yes |
| validation | 30 | 28 | -0.0464 | 6.9806 | -0.1384 | 7.0270 | $351,079,241 | yes |
| validation | 120 | 28 | -0.0326 | 11.5232 | -0.1839 | 11.5558 | $351,079,241 | yes |
| validation | 300 | 28 | 0.0245 | 12.6077 | -0.1402 | 12.5831 | $351,079,241 | yes |

## Overall Official Metrics

| horizon_s | days | pnl_all | pnl_kept | pnl_filtered | score | kept_turnover_per_day | constraint_ok |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | 90 | -0.0613 | 5.2548 | -0.1424 | 5.3162 | $355,057,704 | yes |
| 120 | 90 | 0.0238 | 11.7166 | -0.1544 | 11.6928 | $355,057,704 | yes |
| 300 | 90 | 0.0773 | 12.5126 | -0.1123 | 12.4354 | $355,057,704 | yes |

The turnover constraint is comfortably satisfied.

## Follow-up Hybrid Upgrade

After a second research pass, the implementation was upgraded to a horizon-specific hybrid:

- 30s uses a side-aware 5-second return reversal filter.
- 120s and 300s keep the original liquidation-pressure baseline.

Official exact hybrid result:

| horizon_s | days | pnl_all | pnl_kept | pnl_filtered | score | kept_turnover_per_day | constraint_ok |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | 90 | -0.0613 | 29.6755 | -0.1157 | 29.7368 | $43,178,154 | yes |
| 120 | 90 | 0.0238 | 11.7166 | -0.1544 | 11.6928 | $355,057,704 | yes |
| 300 | 90 | 0.0773 | 12.5126 | -0.1123 | 12.4354 | $355,057,704 | yes |

See `reports/task2_research_followup.md` for the grid search and exact validation notes.

## Full Public 6-Month Metrics

Full public run:

```text
server path: /root/CMF/Task_2/outputs_public_6m
local copy:  D:\Python\CMF\HFT_School\Task_2\outputs_public_6m
period:      2025-11-01 -> 2026-04-28
days:        179
```

By split:

| split | horizon_s | days | pnl_all | pnl_kept | pnl_filtered | score | kept_turnover_per_day | constraint_ok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 30 | 62 | -0.0696 | 4.4881 | -0.1446 | 4.5577 | $356,854,430 | yes |
| train | 120 | 62 | 0.0552 | 11.8026 | -0.1379 | 11.7474 | $356,854,430 | yes |
| train | 300 | 62 | 0.1066 | 12.4704 | -0.0967 | 12.3638 | $356,854,430 | yes |
| validation | 30 | 28 | -0.0464 | 6.9806 | -0.1384 | 7.0270 | $351,079,241 | yes |
| validation | 120 | 28 | -0.0326 | 11.5232 | -0.1839 | 11.5558 | $351,079,241 | yes |
| validation | 300 | 28 | 0.0245 | 12.6077 | -0.1402 | 12.5831 | $351,079,241 | yes |
| public_extra | 30 | 89 | -0.0951 | 1.7161 | -0.1172 | 1.8112 | $284,232,097 | yes |
| public_extra | 120 | 89 | -0.0550 | 1.3659 | -0.0724 | 1.4209 | $284,232,097 | yes |
| public_extra | 300 | 89 | -0.0075 | 2.3359 | -0.0361 | 2.3434 | $284,232,097 | yes |

Overall:

| horizon_s | days | pnl_all | pnl_kept | pnl_filtered | score | kept_turnover_per_day | constraint_ok |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | 179 | -0.0781 | 3.6912 | -0.1299 | 3.7693 | $319,842,738 | yes |
| 120 | 179 | -0.0153 | 7.1432 | -0.1136 | 7.1584 | $319,842,738 | yes |
| 300 | 179 | 0.0352 | 8.0161 | -0.0744 | 7.9808 | $319,842,738 | yes |

## Robustness Caveat

The 6-month aggregate is positive across all horizons, and train/validation are very strong. The extra months are positive in aggregate, but March-April alone is weaker for 120s and 300s. This suggests regime dependence and motivates a next-stage improvement with horizon-specific thresholds, additional BBO/trade-flow features, or a simple ML ranker.

After the hybrid upgrade, the 6-month 30s aggregate improved from `3.7693` to `20.0623`, but March-April remains weaker for the 30s return-reversal rule. The current best next step is a regime switch rather than a blind ML replacement.

## Reproducibility

Run on the server with the existing Task 1 dataset path:

```bash
python src/task2_evaluate.py \
  --data-root /path/to/existing/Task_1 \
  --output-dir outputs \
  --start 2025-11-01 \
  --end 2026-04-29
```

This writes:

- `outputs/task2_daily_metrics.csv`
- `outputs/task2_summary_by_split.csv` with `train`, `validation`, and `public_extra`
- `outputs/task2_summary_overall.csv`
- `outputs/run_config.json`
