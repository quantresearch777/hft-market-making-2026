from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from task3_common import (
        BYBIT_DELAY_US,
        HORIZONS,
        SYMBOLS,
        DataPaths,
        add_markout_arrays,
        date_to_us,
        iter_dates,
        load_bbo,
        load_liq,
        load_trades,
        parse_date,
        summarize_daily,
    )
    from task3_research import score_flags_day
    from task3_solution import classify_trades_after_large_liquidations
except ModuleNotFoundError:
    from .task3_common import (
        BYBIT_DELAY_US,
        HORIZONS,
        SYMBOLS,
        DataPaths,
        add_markout_arrays,
        date_to_us,
        iter_dates,
        load_bbo,
        load_liq,
        load_trades,
        parse_date,
        summarize_daily,
    )
    from .task3_research import score_flags_day
    from .task3_solution import classify_trades_after_large_liquidations


def load_task2_predict(task2_src: Path):
    sys.path.insert(0, str(task2_src))
    from task2_solution import predict as task2_predict

    return task2_predict


def run(
    data_root: Path,
    task2_src: Path,
    output_dir: Path,
    start: str,
    end: str,
    threshold: float,
    window_seconds: int,
    symbols: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    paths = DataPaths.from_root(data_root)
    task2_predict = load_task2_predict(task2_src)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    max_horizon_us = max(HORIZONS) * 1_000_000
    lookback_us = window_seconds * 1_000_000

    for current in iter_dates(parse_date(start), parse_date(end)):
        date_str = current.isoformat()
        start_us = date_to_us(current)
        end_us = date_to_us(current + timedelta(days=1))
        for symbol in symbols:
            print(f"[hybrid] {date_str} {symbol}", flush=True)
            trades = load_trades(paths, symbol, start_us, end_us)
            if trades.is_empty():
                continue
            bbo = load_bbo(paths, symbol, start_us - max_horizon_us - 1_000_000, end_us + max_horizon_us + 1_000_000)
            liq_binance = load_liq(paths.liq_binance(symbol), start_us - lookback_us, end_us)
            liq_bybit = load_liq(paths.liq_bybit(symbol), start_us - lookback_us - BYBIT_DELAY_US, end_us)
            weight, pnl_by_horizon, _, _ = add_markout_arrays(trades, bbo)

            task2_flags = task2_predict(trades, bbo, liq_binance, liq_bybit)
            liq_flags = classify_trades_after_large_liquidations(
                trades,
                liq_binance,
                liq_bybit,
                threshold=threshold,
                window_seconds=window_seconds,
                match_mode="taker_opposite_liquidation",
            ).astype(bool)

            hybrid_flags = {}
            liq_only_30 = {}
            for horizon in HORIZONS:
                base = np.asarray(task2_flags[horizon]).astype(bool)
                if horizon == 30:
                    hybrid_flags[horizon] = np.maximum(base, liq_flags).astype(np.int8)
                    liq_only_30[horizon] = liq_flags.astype(np.int8)
                else:
                    hybrid_flags[horizon] = base.astype(np.int8)
                    liq_only_30[horizon] = np.zeros(len(trades), dtype=np.int8)

            rows.extend(score_flags_day("task2_final", date_str, symbol, weight, pnl_by_horizon, task2_flags))
            rows.extend(score_flags_day("task3_horizon_specific", date_str, symbol, weight, pnl_by_horizon, liq_only_30))
            rows.extend(score_flags_day("task2_plus_task3_30s", date_str, symbol, weight, pnl_by_horizon, hybrid_flags))

    daily = pd.DataFrame(rows)
    summary = summarize_daily(rows, split_by_date=True)
    daily.to_csv(output_dir / "task3_hybrid_daily_metrics.csv", index=False)
    summary.to_csv(output_dir / "task3_hybrid_summary_by_split.csv", index=False)
    return daily, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--task2-src", required=True)
    parser.add_argument("--output-dir", default="reports/hybrid")
    parser.add_argument("--start", default="2025-12-01")
    parser.add_argument("--end", default="2026-03-01")
    parser.add_argument("--threshold", type=float, default=196_940.36)
    parser.add_argument("--window-seconds", type=int, default=30)
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS), choices=list(SYMBOLS))
    args = parser.parse_args()
    run(
        data_root=Path(args.data_root).expanduser().resolve(),
        task2_src=Path(args.task2_src).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        start=args.start,
        end=args.end,
        threshold=args.threshold,
        window_seconds=args.window_seconds,
        symbols=tuple(args.symbols),
    )


if __name__ == "__main__":
    main()
