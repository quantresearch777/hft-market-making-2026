# HFT School Task 1: Full Dataset Exploration

This folder contains my Task 1 notebook for the main education course.

## Main Notebook

```text
notebooks/task_1_full_dataset_eda_0520_executed.ipynb
```

The notebook is executed and contains code plus results. It explores:

- dataset shapes and coverage;
- event distributions over time;
- prices, sizes, notionals, spreads, and outliers;
- BTC vs ETH and Binance vs Bybit differences;
- trade, BBO, and liquidation relationships on the same timeline;
- timestamp and side conventions;
- unusual findings and caveats.

## Polars Pipeline

The heavy full-dataset EDA was done with Polars in:

```text
src/task1_full_eda.py
```

The notebook reads compact CSV outputs from:

```text
outputs_full_eda_0520/tables/
```

and uses figures from:

```text
outputs_full_eda_0520/figures/
```

Raw parquet datasets and large archives are intentionally not committed.

## Identification

GitHub username: `quantresearch777`
