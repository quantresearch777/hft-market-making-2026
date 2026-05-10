#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cmf_hft_backtester.eda import run_eda


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/MD")
    parser.add_argument("--lob-sample-rows", type=int, default=200_000)
    parser.add_argument("--trade-sample-rows", type=int, default=1_000_000)
    parser.add_argument("--output-dir", default="outputs/eda")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    run_eda(data_dir, output_dir, args.lob_sample_rows, args.trade_sample_rows)
    print(f"Wrote EDA report to {output_dir / 'EDA_REPORT.md'}")


if __name__ == "__main__":
    main()
