from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def aggregate_by_symbol(daily: pd.DataFrame) -> pd.DataFrame:
    df = daily.copy()
    df["kept_weighted_pnl_sum"] = df["pnl_kept"].fillna(0.0) * df["kept_clipped_turnover"]
    df["all_weighted_pnl_sum"] = df["pnl_all"] * df["all_clipped_turnover"]
    out = (
        df.groupby(["horizon_s", "symbol"], as_index=False)
        .agg(
            days=("date", "nunique"),
            all_clipped_turnover=("all_clipped_turnover", "sum"),
            kept_clipped_turnover=("kept_clipped_turnover", "sum"),
            kept_weighted_pnl_sum=("kept_weighted_pnl_sum", "sum"),
            all_weighted_pnl_sum=("all_weighted_pnl_sum", "sum"),
            kept_trade_count=("kept_trade_count", "sum"),
            filtered_trade_count=("filtered_trade_count", "sum"),
        )
    )
    out["pnl_all"] = out["all_weighted_pnl_sum"] / out["all_clipped_turnover"]
    out["pnl_kept"] = out["kept_weighted_pnl_sum"] / out["kept_clipped_turnover"]
    out["score"] = out["pnl_kept"] - out["pnl_all"]
    out["kept_turnover_per_day"] = out["kept_clipped_turnover"] / out["days"]
    return out[
        [
            "horizon_s",
            "symbol",
            "days",
            "pnl_all",
            "pnl_kept",
            "score",
            "kept_turnover_per_day",
            "kept_trade_count",
            "filtered_trade_count",
        ]
    ].sort_values(["horizon_s", "symbol"])


def markdown_table(df: pd.DataFrame, float_cols: tuple[str, ...]) -> str:
    data = df.copy()
    for col in float_cols:
        if col in data:
            data[col] = data[col].map(lambda value: f"{value:,.4f}")
    data = data.astype(str)
    headers = list(data.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in data.iterrows():
        lines.append("| " + " | ".join(row[col] for col in headers) + " |")
    return "\n".join(lines)


def run(hybrid_dir: Path, baseline_dir: Path, output: Path) -> None:
    hybrid = pd.read_csv(hybrid_dir / "task2_daily_metrics.csv")
    baseline = pd.read_csv(baseline_dir / "task2_daily_metrics.csv")

    by_symbol = aggregate_by_symbol(hybrid)
    h30 = hybrid[hybrid["horizon_s"] == 30][
        ["date", "symbol", "score", "pnl_kept", "kept_clipped_turnover", "kept_trade_count"]
    ].merge(
        baseline[baseline["horizon_s"] == 30][
            ["date", "symbol", "score", "pnl_kept", "kept_clipped_turnover", "kept_trade_count"]
        ],
        on=["date", "symbol"],
        suffixes=("_hybrid", "_baseline"),
    )
    h30["score_diff"] = h30["score_hybrid"] - h30["score_baseline"]
    best_diff = h30.sort_values("score_diff", ascending=False).head(10)
    worst_diff = h30.sort_values("score_diff").head(10)
    negative = h30[h30["score_hybrid"] < 0].sort_values("score_hybrid").head(10)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(
            [
                "# Task 2 Diagnostics",
                "",
                "## Hybrid Metrics by Symbol",
                "",
                markdown_table(by_symbol, ("pnl_all", "pnl_kept", "score", "kept_turnover_per_day")),
                "",
                "## Best 30s Hybrid Improvements vs Baseline",
                "",
                markdown_table(
                    best_diff,
                    (
                        "score_hybrid",
                        "pnl_kept_hybrid",
                        "kept_clipped_turnover_hybrid",
                        "score_baseline",
                        "pnl_kept_baseline",
                        "kept_clipped_turnover_baseline",
                        "score_diff",
                    ),
                ),
                "",
                "## Worst 30s Hybrid Differences vs Baseline",
                "",
                markdown_table(
                    worst_diff,
                    (
                        "score_hybrid",
                        "pnl_kept_hybrid",
                        "kept_clipped_turnover_hybrid",
                        "score_baseline",
                        "pnl_kept_baseline",
                        "kept_clipped_turnover_baseline",
                        "score_diff",
                    ),
                ),
                "",
                f"Hybrid 30s negative day-symbol rows: {int((h30['score_hybrid'] < 0).sum())} / {len(h30)}",
                "",
                "## Worst Negative 30s Hybrid Day-Symbol Rows",
                "",
                markdown_table(
                    negative,
                    (
                        "score_hybrid",
                        "pnl_kept_hybrid",
                        "kept_clipped_turnover_hybrid",
                        "score_baseline",
                        "pnl_kept_baseline",
                        "kept_clipped_turnover_baseline",
                        "score_diff",
                    ),
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hybrid-dir", required=True)
    parser.add_argument("--baseline-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(Path(args.hybrid_dir), Path(args.baseline_dir), Path(args.output))


if __name__ == "__main__":
    main()
