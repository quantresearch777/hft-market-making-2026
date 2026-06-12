from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


FINAL_MAP = {
    30: "task3_maker_q99_win60",
    120: "task3_maker_q95_win30",
    300: "task3_maker_q95_win30",
}


def _weighted_summary(group: pd.DataFrame) -> pd.Series:
    all_turnover = group["all_clipped_turnover"].sum()
    kept_turnover = group["kept_clipped_turnover"].sum()
    filtered_turnover = group["filtered_clipped_turnover"].sum()
    pnl_all = (group["pnl_all"] * group["all_clipped_turnover"]).sum() / all_turnover
    pnl_kept = (group["pnl_kept"] * group["kept_clipped_turnover"]).sum() / kept_turnover
    pnl_filtered = (
        (group["pnl_filtered"].fillna(0.0) * group["filtered_clipped_turnover"]).sum() / filtered_turnover
        if filtered_turnover > 0
        else float("nan")
    )
    return pd.Series(
        {
            "days": group["date"].nunique(),
            "pnl_all": pnl_all,
            "pnl_kept": pnl_kept,
            "pnl_filtered": pnl_filtered,
            "score": pnl_kept - pnl_all,
            "kept_turnover_per_day": kept_turnover / group["date"].nunique(),
            "positive_symbol_days": int((group["score"] > 0).sum()),
            "symbol_days": int(len(group)),
            "positive_symbol_day_rate": float((group["score"] > 0).mean()),
            "daily_score_mean": group["score"].mean(),
            "daily_score_median": group["score"].median(),
            "daily_score_p10": group["score"].quantile(0.10),
            "daily_score_p90": group["score"].quantile(0.90),
        }
    )


def run(table_dir: Path) -> None:
    daily = pd.read_csv(table_dir / "task3_full_grid_daily_metrics.csv")
    selected = []
    for horizon, strategy in FINAL_MAP.items():
        part = daily[(daily["horizon_s"] == horizon) & (daily["strategy"] == strategy)].copy()
        part["strategy"] = "task3_final_horizon_specific"
        selected.append(part)
    final_daily = pd.concat(selected, ignore_index=True)
    final_daily.to_csv(table_dir / "task3_final_daily_metrics.csv", index=False)

    final_daily["split"] = pd.to_datetime(final_daily["date"]).map(
        lambda d: "train" if d < pd.Timestamp("2026-02-01") else "validation"
    )
    by_symbol = (
        final_daily.groupby(["split", "symbol", "horizon_s"], as_index=False)
        .apply(_weighted_summary, include_groups=False)
        .reset_index(drop=True)
    )
    by_symbol.to_csv(table_dir / "task3_final_symbol_summary.csv", index=False)

    robustness = (
        final_daily.groupby(["split", "horizon_s"], as_index=False)
        .apply(_weighted_summary, include_groups=False)
        .reset_index(drop=True)
    )
    robustness.to_csv(table_dir / "task3_final_robustness.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-dir", default="reports/tables")
    args = parser.parse_args()
    run(Path(args.table_dir))


if __name__ == "__main__":
    main()
