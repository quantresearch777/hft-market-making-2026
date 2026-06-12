from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "src"))

from task3_common import summarize_daily  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-glob", required=True, help="Glob for chunk daily metrics CSV files.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--prefix", default="task3_combined")
    args = parser.parse_args()

    files = sorted(Path().glob(args.input_glob))
    if not files:
        raise FileNotFoundError(f"No files matched {args.input_glob}")

    daily = pd.concat([pd.read_csv(path) for path in files], ignore_index=True)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    daily.to_csv(output_dir / f"{args.prefix}_daily_metrics.csv", index=False)
    summarize_daily(daily.to_dict("records"), split_by_date=True).to_csv(output_dir / f"{args.prefix}_summary_by_split.csv", index=False)
    summarize_daily(daily.to_dict("records"), split_by_date=False).to_csv(output_dir / f"{args.prefix}_summary_overall.csv", index=False)
    print(f"Combined {len(files)} files into {output_dir}")


if __name__ == "__main__":
    main()
