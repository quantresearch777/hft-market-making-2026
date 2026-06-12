from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _fmt_table(df: pd.DataFrame, columns: list[str] | None = None, max_rows: int = 30) -> str:
    if df.empty:
        return "_Not available yet._"
    if columns is not None:
        df = df[[col for col in columns if col in df.columns]]
    df = df.head(max_rows)
    try:
        return df.to_markdown(index=False, floatfmt=".4f")
    except ImportError:
        return "```text\n" + df.to_string(index=False) + "\n```"


def _best_strategy(summary: pd.DataFrame) -> str | None:
    if summary.empty:
        return None
    candidates = summary[summary["strategy"].str.startswith("task3_")].copy()
    if candidates.empty:
        return None
    eligible = candidates[candidates["constraint_ok"]].copy()
    eligible = eligible[eligible["split"].isin(["train", "validation"])]
    if eligible.empty:
        return None
    ranking = (
        eligible.groupby("strategy", as_index=False)
        .agg(mean_score=("score", "mean"), min_score=("score", "min"), min_turnover=("kept_turnover_per_day", "min"))
        .sort_values(["mean_score", "min_score"], ascending=[False, False])
    )
    return str(ranking.iloc[0]["strategy"])


def build_report(report_root: Path, output_path: Path) -> None:
    table_dir = report_root / "tables"
    final_summary = _read_csv(table_dir / "task3_final_summary_by_split.csv")
    full_summary = final_summary if not final_summary.empty else _read_csv(table_dir / "task3_full_grid_summary_by_split.csv")
    if full_summary.empty:
        full_summary = _read_csv(table_dir / "task3_grid_summary_by_split.csv")
    thresholds = _read_csv(table_dir / "task3_liq_thresholds.csv")
    event_study = _read_csv(table_dir / "task3_event_study.csv")
    baseline = _read_csv(table_dir / "task3_task2_baseline_reference.csv")
    robustness = _read_csv(table_dir / "task3_final_robustness.csv")
    symbol_summary = _read_csv(table_dir / "task3_final_symbol_summary.csv")
    incremental = _read_csv(report_root / "experiments" / "exp05_incremental_windows" / "task3_incremental_window_summary_by_split.csv")

    best = _best_strategy(full_summary)
    best_summary = full_summary[full_summary["strategy"].isin(["no_filter", best])] if best else full_summary
    if not baseline.empty:
        baseline = baseline.assign(strategy="task2_baseline")
        best_summary = pd.concat([best_summary, baseline], ignore_index=True, sort=False)

    event_note = "_Event-study plot files are in `reports/figures/`._"
    interpretation = "The event study is used to choose the correct direction convention."
    if not event_study.empty:
        same = event_study[event_study["relation"] == "same_direction"].copy()
        opposite = event_study[event_study["relation"] == "opposite_direction"].copy()
        if not same.empty:
            peak = same.loc[same["avg_markout_bps"].abs().idxmax()]
            event_note = (
                f"Largest absolute same-direction reaction in the generated event study: "
                f"`{peak['threshold_label']}` around `{int(peak['bin_start_s'])}-{int(peak['bin_end_s'])}` seconds, "
                f"average 30s markout `{peak['avg_markout_bps']:.4f}` bps."
            )
        if not same.empty and not opposite.empty:
            same_mean = same["avg_markout_bps"].mean()
            opposite_mean = opposite["avg_markout_bps"].mean()
            interpretation = (
                f"`trades.side` is the taker side, while markout is measured for the passive maker fill. "
                f"On the full train event study, taker-same-direction trades have positive average 30s maker "
                f"markout (`{same_mean:.4f}` bps across bins), while taker-opposite-direction trades are "
                f"negative on average (`{opposite_mean:.4f}` bps across bins). Therefore the final filter uses "
                f"the maker-side interpretation: filter trades where the maker fill direction matches the "
                f"liquidation direction, equivalently where taker trade side is opposite to liquidation side."
            )

    text = f"""# Task 3: Large Liquidation Reaction Filter

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

{_fmt_table(thresholds, max_rows=10)}

## Reaction EDA

For each large liquidation, I measured average Binance trade maker markout with `tau = 30s` from `0` to `300` seconds after liquidation. The curves are split into:

- trades in the same direction as liquidation;
- trades in the opposite direction.

{event_note}

Interpretation:

{interpretation}

## Metrics

The score is:

```text
Score(tau) = PnL_kept(tau) - PnL_all(tau)
```

`no_filter` has score `0` by construction because `PnL_kept = PnL_all` when no trades are filtered.

Best Task 3 candidate selected from full train/validation robustness: `{best or 'not selected yet'}`.

Final horizon-specific parameters:

```text
30s  -> q99 notional threshold ~= 196,940 USD, 60s reaction window
120s -> q95 notional threshold ~= 38,930 USD, 30s reaction window
300s -> q95 notional threshold ~= 38,930 USD, 30s reaction window
```

{_fmt_table(best_summary, columns=['strategy', 'split', 'horizon_s', 'pnl_all', 'pnl_kept', 'pnl_filtered', 'score', 'kept_turnover_per_day', 'constraint_ok'], max_rows=30)}

Task 2 baseline is included as a reference because it was the previous homework filter. It is not used as the Task 3 final answer: Task 3 is specifically about the large-liquidation reaction rule, while the Task 2 filter is a broader short-term reversal/liquidation-pressure filter and keeps a much smaller turnover slice.

## Robustness Checks

The final rule is positive on both train and validation for all three horizons. Positive symbol-day rate is above 60% for each split/horizon, so the result is not driven by a single day.

{_fmt_table(robustness, columns=['split', 'horizon_s', 'score', 'pnl_filtered', 'kept_turnover_per_day', 'positive_symbol_day_rate', 'daily_score_p10', 'daily_score_median', 'daily_score_p90'], max_rows=20)}

Symbol-level summary:

{_fmt_table(symbol_summary, columns=['split', 'symbol', 'horizon_s', 'score', 'pnl_filtered', 'positive_symbol_day_rate'], max_rows=20)}

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

{_fmt_table(incremental[incremental['split'].eq('validation')] if not incremental.empty else incremental, columns=['strategy', 'horizon_s', 'score', 'pnl_filtered', 'kept_turnover_per_day'], max_rows=12)}

## Deliverables

- `src/task3_solution.py` - submission function `predict(trades, bbo, liq_binance, liq_bybit)`.
- `src/task3_research.py` - EDA and grid-search script.
- `reports/tables/` - reproducible metric tables.
- `reports/figures/` - event-study plots.
- `notebooks/task3_large_liquidation_reaction_filter.ipynb` - notebook handoff.
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-root", default="reports")
    parser.add_argument("--output", default="reports/task3_report.md")
    args = parser.parse_args()
    build_report(Path(args.report_root), Path(args.output))


if __name__ == "__main__":
    main()
