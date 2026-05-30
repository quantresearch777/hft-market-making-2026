from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


TURNOVER_CONSTRAINT_PER_DAY = 500_000.0
TRAIN_START = pd.Timestamp("2025-12-01")
VALIDATION_START = pd.Timestamp("2026-02-01")
VALIDATION_END = pd.Timestamp("2026-03-01")


def assign_split(dates: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(dates)
    split = pd.Series("public_extra", index=dates.index)
    split[(parsed >= TRAIN_START) & (parsed < VALIDATION_START)] = "train"
    split[(parsed >= VALIDATION_START) & (parsed < VALIDATION_END)] = "validation"
    return split


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.div(denominator.where(denominator != 0))


def summarize(daily: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    df = daily.copy()
    df["all_weighted_pnl_sum"] = df["pnl_all"] * df["all_clipped_turnover"]
    df["kept_weighted_pnl_sum"] = df["pnl_kept"].fillna(0.0) * df["kept_clipped_turnover"]
    df["filtered_weighted_pnl_sum"] = df["pnl_filtered"].fillna(0.0) * df["filtered_clipped_turnover"]
    out = (
        df.groupby(group_cols, as_index=False)
        .agg(
            days=("date", "nunique"),
            all_clipped_turnover=("all_clipped_turnover", "sum"),
            kept_clipped_turnover=("kept_clipped_turnover", "sum"),
            filtered_clipped_turnover=("filtered_clipped_turnover", "sum"),
            all_weighted_pnl_sum=("all_weighted_pnl_sum", "sum"),
            kept_weighted_pnl_sum=("kept_weighted_pnl_sum", "sum"),
            filtered_weighted_pnl_sum=("filtered_weighted_pnl_sum", "sum"),
            kept_trade_count=("kept_trade_count", "sum"),
            filtered_trade_count=("filtered_trade_count", "sum"),
        )
    )
    out["pnl_all"] = safe_divide(out["all_weighted_pnl_sum"], out["all_clipped_turnover"])
    out["pnl_kept"] = safe_divide(out["kept_weighted_pnl_sum"], out["kept_clipped_turnover"])
    out["pnl_filtered"] = safe_divide(out["filtered_weighted_pnl_sum"], out["filtered_clipped_turnover"])
    out["score"] = out["pnl_kept"] - out["pnl_all"]
    out["kept_turnover_per_day"] = out["kept_clipped_turnover"] / out["days"]
    out["constraint_ok"] = out["kept_turnover_per_day"] >= TURNOVER_CONSTRAINT_PER_DAY
    return out[
        [
            *group_cols,
            "days",
            "pnl_all",
            "pnl_kept",
            "pnl_filtered",
            "score",
            "kept_turnover_per_day",
            "constraint_ok",
            "kept_trade_count",
            "filtered_trade_count",
            "all_clipped_turnover",
            "kept_clipped_turnover",
            "filtered_clipped_turnover",
        ]
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    for item in args.inputs:
        path = Path(item)
        daily_path = path / "task2_daily_metrics.csv" if path.is_dir() else path
        frames.append(pd.read_csv(daily_path))

    daily = pd.concat(frames, ignore_index=True)
    daily = daily.drop_duplicates(["date", "symbol", "horizon_s"]).sort_values(["date", "symbol", "horizon_s"])
    daily["split"] = assign_split(daily["date"])
    daily.to_csv(output_dir / "task2_daily_metrics.csv", index=False)

    by_split = summarize(daily, ["split", "horizon_s"])
    order = {"train": 0, "validation": 1, "public_extra": 2}
    by_split = by_split.assign(_split_order=by_split["split"].map(order)).sort_values(["_split_order", "horizon_s"]).drop(columns="_split_order")
    by_split.to_csv(output_dir / "task2_summary_by_split.csv", index=False)

    overall = summarize(daily, ["horizon_s"]).sort_values("horizon_s")
    overall.to_csv(output_dir / "task2_summary_overall.csv", index=False)

    (output_dir / "run_config.json").write_text(
        json.dumps(
            {
                "inputs": args.inputs,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "rows": int(len(daily)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("Summary by split")
    print(by_split.to_string(index=False))
    print("\nOverall summary")
    print(overall.to_string(index=False))


if __name__ == "__main__":
    main()

