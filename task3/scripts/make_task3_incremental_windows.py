from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _weighted_summary(group: pd.DataFrame) -> pd.Series:
    all_turnover = group["all_clipped_turnover"].sum()
    kept_turnover = group["kept_clipped_turnover"].sum()
    filtered_turnover = group["filtered_clipped_turnover"].sum()
    pnl_all = group["all_weighted_pnl_sum"].sum() / all_turnover
    pnl_kept = group["kept_weighted_pnl_sum"].sum() / kept_turnover
    pnl_filtered = group["filtered_weighted_pnl_sum"].sum() / filtered_turnover if filtered_turnover > 0 else float("nan")
    return pd.Series(
        {
            "days": group["date"].nunique(),
            "all_clipped_turnover": all_turnover,
            "kept_clipped_turnover": kept_turnover,
            "filtered_clipped_turnover": filtered_turnover,
            "pnl_all": pnl_all,
            "pnl_kept": pnl_kept,
            "pnl_filtered": pnl_filtered,
            "score": pnl_kept - pnl_all,
            "kept_turnover_per_day": kept_turnover / group["date"].nunique(),
            "positive_symbol_day_rate": float((group["score"] > 0).mean()),
        }
    )


def run(table_dir: Path, output_dir: Path) -> None:
    daily = pd.read_csv(table_dir / "task3_full_grid_daily_metrics.csv")
    daily["split"] = pd.to_datetime(daily["date"]).map(
        lambda d: "train" if d < pd.Timestamp("2026-02-01") else "validation"
    )
    daily["all_weighted_pnl_sum"] = daily["pnl_all"] * daily["all_clipped_turnover"]
    daily["kept_weighted_pnl_sum"] = daily["pnl_kept"].fillna(0.0) * daily["kept_clipped_turnover"]
    daily["filtered_weighted_pnl_sum"] = daily["pnl_filtered"].fillna(0.0) * daily["filtered_clipped_turnover"]

    pairs = [
        ("task3_maker_q90_win30", "task3_maker_q90_win60", "synthetic_maker_q90_30s_60s"),
        ("task3_maker_q95_win30", "task3_maker_q95_win60", "synthetic_maker_q95_30s_60s"),
        ("task3_maker_q99_win30", "task3_maker_q99_win60", "synthetic_maker_q99_30s_60s"),
    ]

    rows = []
    key_cols = ["date", "symbol", "horizon_s"]
    no_filter = daily[daily["strategy"] == "no_filter"].set_index(key_cols)
    for early_name, wide_name, out_name in pairs:
        early = daily[daily["strategy"] == early_name].set_index(key_cols)
        wide = daily[daily["strategy"] == wide_name].set_index(key_cols)
        common = no_filter.index.intersection(early.index).intersection(wide.index)
        all_part = no_filter.loc[common]
        early_part = early.loc[common]
        wide_part = wide.loc[common]

        band_filtered_turnover = wide_part["filtered_clipped_turnover"] - early_part["filtered_clipped_turnover"]
        band_filtered_sum = wide_part["filtered_weighted_pnl_sum"] - early_part["filtered_weighted_pnl_sum"]
        all_sum = all_part["all_weighted_pnl_sum"]
        all_turnover = all_part["all_clipped_turnover"]
        kept_turnover = all_turnover - band_filtered_turnover
        kept_sum = all_sum - band_filtered_sum

        out = pd.DataFrame(index=common)
        out["strategy"] = out_name
        out["pnl_all"] = all_sum / all_turnover
        out["pnl_kept"] = kept_sum / kept_turnover
        out["pnl_filtered"] = band_filtered_sum / band_filtered_turnover.where(band_filtered_turnover != 0)
        out["score"] = out["pnl_kept"] - out["pnl_all"]
        out["all_clipped_turnover"] = all_turnover
        out["kept_clipped_turnover"] = kept_turnover
        out["filtered_clipped_turnover"] = band_filtered_turnover
        out["kept_trade_count"] = wide_part["kept_trade_count"]
        out["filtered_trade_count"] = wide_part["filtered_trade_count"] - early_part["filtered_trade_count"]
        out = out.reset_index()
        rows.append(out)

    synthetic_daily = pd.concat(rows, ignore_index=True)
    synthetic_daily["split"] = pd.to_datetime(synthetic_daily["date"]).map(
        lambda d: "train" if d < pd.Timestamp("2026-02-01") else "validation"
    )
    synthetic_daily["all_weighted_pnl_sum"] = synthetic_daily["pnl_all"] * synthetic_daily["all_clipped_turnover"]
    synthetic_daily["kept_weighted_pnl_sum"] = synthetic_daily["pnl_kept"].fillna(0.0) * synthetic_daily["kept_clipped_turnover"]
    synthetic_daily["filtered_weighted_pnl_sum"] = synthetic_daily["pnl_filtered"].fillna(0.0) * synthetic_daily["filtered_clipped_turnover"]

    summary = (
        synthetic_daily.groupby(["strategy", "split", "horizon_s"], as_index=False)
        .apply(_weighted_summary, include_groups=False)
        .reset_index(drop=True)
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    synthetic_daily.to_csv(output_dir / "task3_incremental_window_daily_metrics.csv", index=False)
    summary.to_csv(output_dir / "task3_incremental_window_summary_by_split.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-dir", default="reports/tables")
    parser.add_argument("--output-dir", default="reports/experiments/exp05_incremental_windows")
    args = parser.parse_args()
    run(Path(args.table_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()
