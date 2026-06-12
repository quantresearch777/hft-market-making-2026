from __future__ import annotations

import argparse
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
    from task3_guard_grid import side_aware_return_bps
    from task3_research import score_flags_day
    from task3_solution import classify_trades_after_large_liquidations
except ImportError:
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
    from .task3_guard_grid import side_aware_return_bps
    from .task3_research import score_flags_day
    from .task3_solution import classify_trades_after_large_liquidations


BASE_CONFIGS = [
    ("q95w30", 38_929.53, 30),
    ("q99w60", 196_940.36, 60),
]
GUARD_CONFIGS = [
    (5, -20.0),
    (5, 0.0),
    (10, -20.0),
    (10, 0.0),
]


def run(data_root: Path, output_dir: Path, start: str, end: str, symbols: tuple[str, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    paths = DataPaths.from_root(data_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    max_horizon_us = max(HORIZONS) * 1_000_000
    max_liq_window_us = max(window for _, _, window in BASE_CONFIGS) * 1_000_000
    max_return_window_us = max(lookback for lookback, _ in GUARD_CONFIGS) * 1_000_000
    rows = []

    for current in iter_dates(parse_date(start), parse_date(end)):
        date_str = current.isoformat()
        start_us = date_to_us(current)
        end_us = date_to_us(current + timedelta(days=1))
        for symbol in symbols:
            print(f"[guard-candidates] {date_str} {symbol}", flush=True)
            trades = load_trades(paths, symbol, start_us, end_us)
            if trades.is_empty():
                continue
            bbo = load_bbo(
                paths,
                symbol,
                start_us - max(max_horizon_us, max_return_window_us) - 1_000_000,
                end_us + max_horizon_us + 1_000_000,
            )
            liq_binance = load_liq(paths.liq_binance(symbol), start_us - max_liq_window_us, end_us)
            liq_bybit = load_liq(paths.liq_bybit(symbol), start_us - max_liq_window_us - BYBIT_DELAY_US, end_us)
            weight, pnl_by_horizon, _, _ = add_markout_arrays(trades, bbo)

            zero = np.zeros(len(trades), dtype=np.int8)
            rows.extend(score_flags_day("no_filter", date_str, symbol, weight, pnl_by_horizon, {h: zero for h in HORIZONS}))

            returns = {lookback: side_aware_return_bps(trades, bbo, lookback) for lookback, _ in GUARD_CONFIGS}
            for base_label, threshold, liq_window in BASE_CONFIGS:
                base_flags = classify_trades_after_large_liquidations(
                    trades,
                    liq_binance,
                    liq_bybit,
                    threshold=threshold,
                    window_seconds=liq_window,
                    match_mode="taker_opposite_liquidation",
                ).astype(bool)
                rows.extend(score_flags_day(f"candidate_base_{base_label}", date_str, symbol, weight, pnl_by_horizon, {h: base_flags for h in HORIZONS}))

                for lookback, level in GUARD_CONFIGS:
                    values = returns[lookback]
                    finite = np.isfinite(values)
                    flags = (base_flags & finite & (values < level)).astype(np.int8)
                    suffix = str(int(level)).replace("-", "m")
                    name = f"candidate_guard_{base_label}_ret{lookback}s_lt{suffix}"
                    rows.extend(score_flags_day(name, date_str, symbol, weight, pnl_by_horizon, {h: flags for h in HORIZONS}))

    daily = pd.DataFrame(rows)
    summary = summarize_daily(rows, split_by_date=True)
    daily.to_csv(output_dir / "task3_guard_candidates_daily_metrics.csv", index=False)
    summary.to_csv(output_dir / "task3_guard_candidates_summary_by_split.csv", index=False)
    return daily, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-dir", default="reports/guard_candidates")
    parser.add_argument("--start", default="2025-12-01")
    parser.add_argument("--end", default="2026-03-01")
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS), choices=list(SYMBOLS))
    args = parser.parse_args()
    run(
        data_root=Path(args.data_root).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        start=args.start,
        end=args.end,
        symbols=tuple(args.symbols),
    )


if __name__ == "__main__":
    main()
