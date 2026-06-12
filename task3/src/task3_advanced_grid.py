from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

try:
    from task3_common import (
        BYBIT_DELAY_US,
        HORIZONS,
        SYMBOLS,
        DataPaths,
        add_markout_arrays,
        collect_streaming,
        date_to_us,
        iter_dates,
        load_bbo,
        load_liq,
        load_trades,
        parse_date,
        summarize_daily,
    )
    from task3_research import score_flags_day
except ImportError:
    from .task3_common import (
        BYBIT_DELAY_US,
        HORIZONS,
        SYMBOLS,
        DataPaths,
        add_markout_arrays,
        collect_streaming,
        date_to_us,
        iter_dates,
        load_bbo,
        load_liq,
        load_trades,
        parse_date,
        summarize_daily,
    )
    from .task3_research import score_flags_day


def _side_sign(side: np.ndarray) -> np.ndarray:
    return np.where(np.char.lower(np.asarray(side).astype(str)) == "buy", 1, -1).astype(np.int8)


def compute_thresholds(paths: DataPaths, start: str, end: str, quantiles: list[float]) -> pd.DataFrame:
    start_us = date_to_us(parse_date(start))
    end_us = date_to_us(parse_date(end))
    rows = []
    for source in ("both", "binance", "bybit"):
        frames = []
        for symbol in SYMBOLS:
            if source in ("both", "binance"):
                frames.append(
                    (
                        paths.liq_binance(symbol),
                        f"binance:{symbol}",
                    )
                )
            if source in ("both", "bybit"):
                frames.append(
                    (
                        paths.liq_bybit(symbol),
                        f"bybit:{symbol}",
                    )
                )
        scans = [
            (
                pd.Series(
                    collect_streaming(
                        pl.scan_parquet(path)
                        .filter((pl.col("timestamp") >= start_us) & (pl.col("timestamp") < end_us))
                        .select((pl.col("price") * pl.col("amount")).alias("notional"))
                    )["notional"].to_numpy()
                )
            )
            for path, _ in frames
        ]
        values = pd.concat(scans, ignore_index=True).to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        for q in quantiles:
            rows.append({"source": source, "q": q, "threshold": float(np.quantile(values, q))})
    return pd.DataFrame(rows)


def event_arrays(liq_binance, liq_bybit, threshold: float, source: str) -> tuple[np.ndarray, np.ndarray]:
    chunks = []
    if source in ("both", "binance") and not liq_binance.is_empty():
        ts = liq_binance["timestamp"].to_numpy().astype(np.int64, copy=False)
        sign = _side_sign(liq_binance["side"].to_numpy())
        notional = liq_binance["price"].to_numpy().astype(float) * liq_binance["amount"].to_numpy().astype(float)
        keep = np.isfinite(notional) & (notional >= threshold)
        chunks.append((ts[keep], sign[keep]))
    if source in ("both", "bybit") and not liq_bybit.is_empty():
        ts = liq_bybit["timestamp"].to_numpy().astype(np.int64, copy=False) + BYBIT_DELAY_US
        sign = _side_sign(liq_bybit["side"].to_numpy())
        notional = liq_bybit["price"].to_numpy().astype(float) * liq_bybit["amount"].to_numpy().astype(float)
        keep = np.isfinite(notional) & (notional >= threshold)
        chunks.append((ts[keep], sign[keep]))
    if not chunks:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int8)
    ts = np.concatenate([chunk[0] for chunk in chunks])
    sign = np.concatenate([chunk[1] for chunk in chunks])
    order = np.argsort(ts, kind="mergesort")
    return ts[order], sign[order]


def maker_age_us(trade_ts: np.ndarray, trade_sign: np.ndarray, event_ts: np.ndarray, event_sign: np.ndarray) -> np.ndarray:
    age = np.full(len(trade_ts), np.iinfo(np.int64).max, dtype=np.int64)
    for liq_sign in (-1, 1):
        ts = event_ts[event_sign == liq_sign]
        if len(ts) == 0:
            continue
        target = trade_sign == -liq_sign
        idx = np.searchsorted(ts, trade_ts[target], side="right") - 1
        ok = idx >= 0
        positions = np.flatnonzero(target)
        age[positions[ok]] = trade_ts[positions[ok]] - ts[idx[ok]]
    return age


def run(
    data_root: Path,
    output_dir: Path,
    start: str,
    end: str,
    quantiles: list[float],
    windows: list[int],
    sources: list[str],
    symbols: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    paths = DataPaths.from_root(data_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    thresholds = compute_thresholds(paths, "2025-12-01", "2026-02-01", quantiles)
    thresholds.to_csv(output_dir / "task3_advanced_thresholds.csv", index=False)

    max_horizon_us = max(HORIZONS) * 1_000_000
    max_window_us = max(windows) * 1_000_000
    rows = []
    for current in iter_dates(parse_date(start), parse_date(end)):
        date_str = current.isoformat()
        start_us = date_to_us(current)
        end_us = date_to_us(current + timedelta(days=1))
        for symbol in symbols:
            print(f"[advanced] {date_str} {symbol}", flush=True)
            trades = load_trades(paths, symbol, start_us, end_us)
            if trades.is_empty():
                continue
            bbo = load_bbo(paths, symbol, start_us - max_horizon_us - 1_000_000, end_us + max_horizon_us + 1_000_000)
            liq_binance = load_liq(paths.liq_binance(symbol), start_us - max_window_us, end_us)
            liq_bybit = load_liq(paths.liq_bybit(symbol), start_us - max_window_us - BYBIT_DELAY_US, end_us)
            weight, pnl_by_horizon, trade_ts, trade_sign_float = add_markout_arrays(trades, bbo)
            trade_sign = trade_sign_float.astype(np.int8)
            zero = np.zeros(len(trades), dtype=np.int8)
            rows.extend(score_flags_day("no_filter", date_str, symbol, weight, pnl_by_horizon, {h: zero for h in HORIZONS}))

            for source in sources:
                src_thresholds = thresholds[thresholds["source"] == source]
                for _, threshold_row in src_thresholds.iterrows():
                    q_label = f"q{int(round(float(threshold_row['q']) * 100))}"
                    threshold = float(threshold_row["threshold"])
                    ev_ts, ev_sign = event_arrays(liq_binance, liq_bybit, threshold, source)
                    age = maker_age_us(trade_ts, trade_sign, ev_ts, ev_sign)
                    for window in windows:
                        flags = (age <= window * 1_000_000).astype(np.int8)
                        name = f"adv_{source}_{q_label}_win{window}"
                        rows.extend(score_flags_day(name, date_str, symbol, weight, pnl_by_horizon, {h: flags for h in HORIZONS}))

    daily = pd.DataFrame(rows)
    summary = summarize_daily(rows, split_by_date=True)
    daily.to_csv(output_dir / "task3_advanced_daily_metrics.csv", index=False)
    summary.to_csv(output_dir / "task3_advanced_summary_by_split.csv", index=False)
    return daily, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-dir", default="reports/advanced")
    parser.add_argument("--start", default="2025-12-01")
    parser.add_argument("--end", default="2026-03-01")
    parser.add_argument("--quantiles", nargs="+", type=float, default=[0.85, 0.90, 0.95, 0.97, 0.99])
    parser.add_argument("--windows", nargs="+", type=int, default=[10, 20, 30, 45, 60, 90, 120])
    parser.add_argument("--sources", nargs="+", default=["both", "binance", "bybit"], choices=["both", "binance", "bybit"])
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS), choices=list(SYMBOLS))
    args = parser.parse_args()
    run(
        data_root=Path(args.data_root).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        start=args.start,
        end=args.end,
        quantiles=args.quantiles,
        windows=args.windows,
        sources=args.sources,
        symbols=tuple(args.symbols),
    )


if __name__ == "__main__":
    main()
