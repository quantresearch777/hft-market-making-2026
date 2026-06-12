from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-glob", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    files = sorted(Path().glob(args.input_glob))
    if not files:
        raise FileNotFoundError(f"No files matched {args.input_glob}")

    raw = pd.concat([pd.read_csv(path) for path in files], ignore_index=True)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw.to_csv(output_dir / "task3_event_study_raw.csv", index=False)

    grouped = (
        raw.groupby(["threshold_label", "threshold", "relation", "bin_start_s", "bin_end_s"], as_index=False)
        .agg(
            large_liq_count=("large_liq_count", "sum"),
            trade_count=("trade_count", "sum"),
            weight_sum=("weight_sum", "sum"),
            weighted_pnl_sum=("weighted_pnl_sum", "sum"),
        )
    )
    grouped["avg_markout_bps"] = grouped["weighted_pnl_sum"] / grouped["weight_sum"].where(grouped["weight_sum"] != 0)
    grouped.to_csv(output_dir / "task3_event_study.csv", index=False)
    print(f"Combined {len(files)} event-study files into {output_dir}")


if __name__ == "__main__":
    main()
