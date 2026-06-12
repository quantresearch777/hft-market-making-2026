from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

try:
    import matplotlib.pyplot as plt
except ModuleNotFoundError:  # pragma: no cover
    plt = None

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
        weighted_mean,
    )
    from task3_solution import classify_trades_after_large_liquidations
except ModuleNotFoundError:
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
        weighted_mean,
    )
    from .task3_solution import classify_trades_after_large_liquidations


TRAIN_START = "2025-12-01"
VALIDATION_END = "2026-03-01"
MAX_REACTION_SECONDS = 300


def _liq_scan_with_notional(path: Path, start_us: int, end_us: int, delay_us: int = 0) -> pl.LazyFrame:
    return (
        pl.scan_parquet(path)
        .filter((pl.col("timestamp") >= start_us) & (pl.col("timestamp") < end_us))
        .select(
            [
                (pl.col("timestamp") + delay_us).alias("timestamp"),
                pl.col("ticker"),
                pl.col("side"),
                pl.col("price"),
                pl.col("amount"),
                (pl.col("price") * pl.col("amount")).alias("notional"),
            ]
        )
    )


def compute_liq_thresholds(paths: DataPaths, start: str, end: str, output_dir: Path) -> pd.DataFrame:
    start_us = date_to_us(parse_date(start))
    end_us = date_to_us(parse_date(end))
    frames: list[pl.LazyFrame] = []
    for symbol in SYMBOLS:
        frames.append(_liq_scan_with_notional(paths.liq_binance(symbol), start_us, end_us).with_columns(pl.lit(symbol).alias("symbol"), pl.lit("binance").alias("exchange")))
        frames.append(_liq_scan_with_notional(paths.liq_bybit(symbol), start_us, end_us, BYBIT_DELAY_US).with_columns(pl.lit(symbol).alias("symbol"), pl.lit("bybit").alias("exchange")))

    all_liq = pl.concat(frames)
    global_q = collect_streaming(
        all_liq.select(
            [
                pl.len().alias("event_count"),
                pl.col("notional").quantile(0.90).alias("q90"),
                pl.col("notional").quantile(0.95).alias("q95"),
                pl.col("notional").quantile(0.99).alias("q99"),
                pl.col("notional").max().alias("max_notional"),
            ]
        )
    ).with_columns(pl.lit("all").alias("symbol"), pl.lit("all").alias("exchange"))

    by_symbol_exchange = collect_streaming(
        all_liq.group_by(["symbol", "exchange"])
        .agg(
            [
                pl.len().alias("event_count"),
                pl.col("notional").quantile(0.90).alias("q90"),
                pl.col("notional").quantile(0.95).alias("q95"),
                pl.col("notional").quantile(0.99).alias("q99"),
                pl.col("notional").max().alias("max_notional"),
            ]
        )
        .sort(["symbol", "exchange"])
    )

    out = pl.concat([global_q.select(by_symbol_exchange.columns), by_symbol_exchange]).to_pandas()
    output_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_dir / "task3_liq_thresholds.csv", index=False)
    return out


def threshold_values(thresholds: pd.DataFrame) -> list[tuple[str, float]]:
    global_row = thresholds[(thresholds["symbol"] == "all") & (thresholds["exchange"] == "all")].iloc[0]
    candidates = [
        ("q90", float(global_row["q90"])),
        ("q95", float(global_row["q95"])),
        ("q99", float(global_row["q99"])),
    ]
    return [(label, round(value, 2)) for label, value in candidates if np.isfinite(value)]


def _concat_large_liqs(
    liq_binance: pl.DataFrame,
    liq_bybit: pl.DataFrame,
    threshold: float,
) -> tuple[np.ndarray, np.ndarray]:
    rows = []
    for frame, delay_us in ((liq_binance, 0), (liq_bybit, BYBIT_DELAY_US)):
        if frame.is_empty():
            continue
        ts = frame["timestamp"].to_numpy().astype(np.int64, copy=False) + delay_us
        side = np.where(np.char.lower(frame["side"].to_numpy().astype(str)) == "buy", 1, -1).astype(np.int8)
        notional = frame["price"].to_numpy().astype(np.float64, copy=False) * frame["amount"].to_numpy().astype(np.float64, copy=False)
        keep = np.isfinite(notional) & (notional >= threshold)
        rows.append((ts[keep], side[keep]))
    if not rows:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int8)
    ts = np.concatenate([item[0] for item in rows])
    side = np.concatenate([item[1] for item in rows])
    order = np.argsort(ts, kind="mergesort")
    return ts[order], side[order]


def _cum_arrays(ts: np.ndarray, values: np.ndarray, weights: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    selected_ts = ts[mask]
    selected_values = values[mask]
    selected_weights = weights[mask]
    order = np.argsort(selected_ts, kind="mergesort")
    selected_ts = selected_ts[order]
    selected_values = selected_values[order]
    selected_weights = selected_weights[order]
    finite = np.isfinite(selected_values) & np.isfinite(selected_weights) & (selected_weights > 0)
    selected_ts = selected_ts[finite]
    selected_values = selected_values[finite]
    selected_weights = selected_weights[finite]
    cum_w = np.concatenate([[0.0], np.cumsum(selected_weights)])
    cum_wpnl = np.concatenate([[0.0], np.cumsum(selected_weights * selected_values)])
    cum_count = np.arange(len(selected_ts) + 1, dtype=np.int64)
    return selected_ts, cum_w, cum_wpnl, cum_count


def _sum_between(
    trade_ts: np.ndarray,
    cum_w: np.ndarray,
    cum_wpnl: np.ndarray,
    cum_count: np.ndarray,
    event_ts: np.ndarray,
    left_us: int,
    right_us: int,
) -> tuple[float, float, int]:
    if len(trade_ts) == 0 or len(event_ts) == 0:
        return 0.0, 0.0, 0
    left = np.searchsorted(trade_ts, event_ts + left_us, side="left")
    right = np.searchsorted(trade_ts, event_ts + right_us, side="left")
    sum_w = float(np.sum(cum_w[right] - cum_w[left]))
    sum_wpnl = float(np.sum(cum_wpnl[right] - cum_wpnl[left]))
    count = int(np.sum(cum_count[right] - cum_count[left]))
    return sum_w, sum_wpnl, count


def event_study_day(
    date_str: str,
    symbol: str,
    trades: pl.DataFrame,
    bbo: pl.DataFrame,
    liq_binance: pl.DataFrame,
    liq_bybit: pl.DataFrame,
    thresholds: list[tuple[str, float]],
    bin_seconds: int,
) -> list[dict]:
    if trades.is_empty() or bbo.is_empty():
        return []
    weight, pnl_by_horizon, trade_ts, trade_sign = add_markout_arrays(trades, bbo)
    pnl30 = pnl_by_horizon[30]
    bins = list(range(0, MAX_REACTION_SECONDS, bin_seconds))

    rows: list[dict] = []
    side_arrays = {}
    for side in (-1, 1):
        side_arrays[side] = _cum_arrays(trade_ts, pnl30, weight, trade_sign == side)

    for threshold_label, threshold in thresholds:
        liq_ts, liq_side = _concat_large_liqs(liq_binance, liq_bybit, threshold)
        if len(liq_ts) == 0:
            continue
        for liq_sign in (-1, 1):
            events = liq_ts[liq_side == liq_sign]
            if len(events) == 0:
                continue
            for left_s in bins:
                right_s = left_s + bin_seconds
                for relation, trade_side in (("same_direction", liq_sign), ("opposite_direction", -liq_sign)):
                    arr_ts, cum_w, cum_wpnl, cum_count = side_arrays[trade_side]
                    sum_w, sum_wpnl, count = _sum_between(
                        arr_ts,
                        cum_w,
                        cum_wpnl,
                        cum_count,
                        events,
                        left_s * 1_000_000,
                        right_s * 1_000_000,
                    )
                    rows.append(
                        {
                            "date": date_str,
                            "symbol": symbol,
                            "threshold_label": threshold_label,
                            "threshold": threshold,
                            "liq_side": "buy" if liq_sign == 1 else "sell",
                            "relation": relation,
                            "bin_start_s": left_s,
                            "bin_end_s": right_s,
                            "large_liq_count": int(len(events)),
                            "trade_count": count,
                            "weight_sum": sum_w,
                            "weighted_pnl_sum": sum_wpnl,
                        }
                    )
    return rows


def event_study_worker(args: tuple[str, str, str, list[tuple[str, float]], int]) -> list[dict]:
    data_root, date_str, symbol, thresholds, bin_seconds = args
    paths = DataPaths.from_root(Path(data_root))
    current = parse_date(date_str)
    start_us = date_to_us(current)
    end_us = date_to_us(current + timedelta(days=1))
    max_horizon_us = max(HORIZONS) * 1_000_000
    max_event_us = MAX_REACTION_SECONDS * 1_000_000
    trades = load_trades(paths, symbol, start_us, end_us + max_event_us)
    if trades.is_empty():
        return []
    bbo = load_bbo(paths, symbol, start_us - 1_000_000, end_us + max_event_us + max_horizon_us + 1_000_000)
    liq_binance = load_liq(paths.liq_binance(symbol), start_us, end_us)
    liq_bybit = load_liq(paths.liq_bybit(symbol), start_us - BYBIT_DELAY_US, end_us)
    return event_study_day(date_str, symbol, trades, bbo, liq_binance, liq_bybit, thresholds, bin_seconds)


def aggregate_event_study(rows: list[dict], output_dir: Path) -> pd.DataFrame:
    raw = pd.DataFrame(rows)
    if raw.empty:
        return raw
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
    return grouped


def plot_event_study(event_study: pd.DataFrame, figure_dir: Path) -> None:
    if plt is None or event_study.empty:
        return
    figure_dir.mkdir(parents=True, exist_ok=True)
    for threshold_label, chunk in event_study.groupby("threshold_label"):
        fig, ax = plt.subplots(figsize=(10, 5))
        for relation, rel_chunk in chunk.groupby("relation"):
            rel_chunk = rel_chunk.sort_values("bin_start_s")
            label = "same direction" if relation == "same_direction" else "opposite direction"
            ax.plot(rel_chunk["bin_start_s"], rel_chunk["avg_markout_bps"], marker="o", linewidth=1.5, label=label)
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set_title(f"Average 30s maker markout after large liquidations ({threshold_label})")
        ax.set_xlabel("seconds after liquidation")
        ax.set_ylabel("average 30s markout, bps")
        ax.grid(True, alpha=0.25)
        ax.legend()
        fig.tight_layout()
        fig.savefig(figure_dir / f"task3_event_study_{threshold_label}.png", dpi=160)
        plt.close(fig)


def score_flags_day(
    strategy_name: str,
    date_str: str,
    symbol: str,
    weight: np.ndarray,
    pnl_by_horizon: dict[int, np.ndarray],
    flags_by_horizon: dict[int, np.ndarray],
) -> list[dict]:
    rows: list[dict] = []
    for horizon in HORIZONS:
        flags = np.asarray(flags_by_horizon[horizon]).astype(bool)
        pnl = pnl_by_horizon[horizon]
        valid = np.isfinite(pnl) & np.isfinite(weight) & (weight > 0)
        kept = valid & ~flags
        filtered = valid & flags
        pnl_all = weighted_mean(pnl, weight, valid)
        pnl_kept = weighted_mean(pnl, weight, kept)
        pnl_filtered = weighted_mean(pnl, weight, filtered)
        rows.append(
            {
                "strategy": strategy_name,
                "date": date_str,
                "symbol": symbol,
                "horizon_s": horizon,
                "pnl_all": pnl_all,
                "pnl_kept": pnl_kept,
                "pnl_filtered": pnl_filtered,
                "score": pnl_kept - pnl_all,
                "all_clipped_turnover": float(np.sum(weight[valid])),
                "kept_clipped_turnover": float(np.sum(weight[kept])),
                "filtered_clipped_turnover": float(np.sum(weight[filtered])),
                "kept_trade_count": int(np.sum(kept)),
                "filtered_trade_count": int(np.sum(filtered)),
            }
        )
    return rows


def _zero_flags(n: int) -> dict[int, np.ndarray]:
    flags = np.zeros(n, dtype=np.int8)
    return {horizon: flags for horizon in HORIZONS}


def _task2_predict(task2_src: Path | None):
    if task2_src is None:
        return None
    if not task2_src.exists():
        return None
    sys.path.insert(0, str(task2_src))
    try:
        from task2_solution import predict as task2_predict
    except ModuleNotFoundError:
        return None
    return task2_predict


def evaluate_grid(
    paths: DataPaths,
    output_dir: Path,
    start: str,
    end: str,
    thresholds: list[tuple[str, float]],
    windows: list[int],
    symbols: tuple[str, ...],
    task2_src: Path | None,
    match_modes: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    start_date = parse_date(start)
    end_date = parse_date(end)
    max_horizon_us = max(HORIZONS) * 1_000_000
    max_window_us = max(windows) * 1_000_000 if windows else 0
    task2_predict = _task2_predict(task2_src)
    rows: list[dict] = []

    for current in iter_dates(start_date, end_date):
        date_str = current.isoformat()
        start_us = date_to_us(current)
        end_us = date_to_us(current + timedelta(days=1))
        for symbol in symbols:
            print(f"[grid] {date_str} {symbol}", flush=True)
            trades = load_trades(paths, symbol, start_us, end_us)
            if trades.is_empty():
                continue
            bbo = load_bbo(paths, symbol, start_us - max_horizon_us - 1_000_000, end_us + max_horizon_us + 1_000_000)
            liq_binance = load_liq(paths.liq_binance(symbol), start_us - max_window_us, end_us)
            liq_bybit = load_liq(paths.liq_bybit(symbol), start_us - max_window_us - BYBIT_DELAY_US, end_us)
            weight, pnl_by_horizon, _, _ = add_markout_arrays(trades, bbo)

            rows.extend(score_flags_day("no_filter", date_str, symbol, weight, pnl_by_horizon, _zero_flags(len(trades))))
            if task2_predict is not None:
                rows.extend(score_flags_day("task2_final", date_str, symbol, weight, pnl_by_horizon, task2_predict(trades, bbo, liq_binance, liq_bybit)))

            for threshold_label, threshold in thresholds:
                for window_seconds in windows:
                    for match_mode in match_modes:
                        flags = classify_trades_after_large_liquidations(
                            trades,
                            liq_binance,
                            liq_bybit,
                            threshold=threshold,
                            window_seconds=window_seconds,
                            match_mode=match_mode,
                        )
                        flags_by_horizon = {horizon: flags for horizon in HORIZONS}
                        mode_label = "same" if match_mode == "taker_same_liquidation" else "maker"
                        name = f"task3_{mode_label}_{threshold_label}_win{window_seconds}"
                        rows.extend(score_flags_day(name, date_str, symbol, weight, pnl_by_horizon, flags_by_horizon))

    daily = pd.DataFrame(rows)
    daily.to_csv(output_dir / "task3_grid_daily_metrics.csv", index=False)
    summary = summarize_daily(rows, split_by_date=True)
    summary.to_csv(output_dir / "task3_grid_summary_by_split.csv", index=False)
    return daily, summary


def grid_worker(args: tuple[str, str, str, list[tuple[str, float]], list[int], str | None, list[str]]) -> list[dict]:
    data_root, date_str, symbol, thresholds, windows, task2_src_str, match_modes = args
    paths = DataPaths.from_root(Path(data_root))
    task2_predict = _task2_predict(Path(task2_src_str) if task2_src_str else None)
    current = parse_date(date_str)
    start_us = date_to_us(current)
    end_us = date_to_us(current + timedelta(days=1))
    max_horizon_us = max(HORIZONS) * 1_000_000
    max_window_us = max(windows) * 1_000_000 if windows else 0

    trades = load_trades(paths, symbol, start_us, end_us)
    if trades.is_empty():
        return []
    bbo = load_bbo(paths, symbol, start_us - max_horizon_us - 1_000_000, end_us + max_horizon_us + 1_000_000)
    liq_binance = load_liq(paths.liq_binance(symbol), start_us - max_window_us, end_us)
    liq_bybit = load_liq(paths.liq_bybit(symbol), start_us - max_window_us - BYBIT_DELAY_US, end_us)
    weight, pnl_by_horizon, _, _ = add_markout_arrays(trades, bbo)

    rows: list[dict] = []
    rows.extend(score_flags_day("no_filter", date_str, symbol, weight, pnl_by_horizon, _zero_flags(len(trades))))
    if task2_predict is not None:
        rows.extend(score_flags_day("task2_final", date_str, symbol, weight, pnl_by_horizon, task2_predict(trades, bbo, liq_binance, liq_bybit)))

    for threshold_label, threshold in thresholds:
        for window_seconds in windows:
            for match_mode in match_modes:
                flags = classify_trades_after_large_liquidations(
                    trades,
                    liq_binance,
                    liq_bybit,
                    threshold=threshold,
                    window_seconds=window_seconds,
                    match_mode=match_mode,
                )
                flags_by_horizon = {horizon: flags for horizon in HORIZONS}
                mode_label = "same" if match_mode == "taker_same_liquidation" else "maker"
                name = f"task3_{mode_label}_{threshold_label}_win{window_seconds}"
                rows.extend(score_flags_day(name, date_str, symbol, weight, pnl_by_horizon, flags_by_horizon))
    return rows


def evaluate_grid_parallel(
    paths: DataPaths,
    output_dir: Path,
    start: str,
    end: str,
    thresholds: list[tuple[str, float]],
    windows: list[int],
    symbols: tuple[str, ...],
    task2_src: Path | None,
    workers: int,
    match_modes: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if workers <= 1:
        return evaluate_grid(paths, output_dir, start, end, thresholds, windows, symbols, task2_src, match_modes)

    tasks = [
        (str(paths.data), current.isoformat(), symbol, thresholds, windows, str(task2_src) if task2_src else None, match_modes)
        for current in iter_dates(parse_date(start), parse_date(end))
        for symbol in symbols
    ]
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(grid_worker, task): task for task in tasks}
        for future in as_completed(futures):
            _, date_str, symbol, _, _, _, _ = futures[future]
            print(f"[grid-parallel] done {date_str} {symbol}", flush=True)
            rows.extend(future.result())

    daily = pd.DataFrame(rows)
    daily.to_csv(output_dir / "task3_grid_daily_metrics.csv", index=False)
    summary = summarize_daily(rows, split_by_date=True)
    summary.to_csv(output_dir / "task3_grid_summary_by_split.csv", index=False)
    return daily, summary


def build_decision_table(summary: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    if summary.empty:
        return summary
    filtered = summary[summary["strategy"].str.startswith("task3_")].copy()
    pivot = filtered.pivot_table(index=["strategy", "split"], columns="horizon_s", values="score", aggfunc="first").reset_index()
    pivot.columns = [str(col) if isinstance(col, int) else col for col in pivot.columns]
    validation = filtered[filtered["split"] == "validation"].copy()
    validation["rank_score"] = validation["score"].where(validation["constraint_ok"], -1e9)
    by_strategy = (
        validation.groupby("strategy", as_index=False)
        .agg(
            min_validation_score=("rank_score", "min"),
            mean_validation_score=("rank_score", "mean"),
            min_kept_turnover_per_day=("kept_turnover_per_day", "min"),
            all_constraints_ok=("constraint_ok", "all"),
        )
        .sort_values(["all_constraints_ok", "min_validation_score", "mean_validation_score"], ascending=[False, False, False])
    )
    by_strategy.to_csv(output_dir / "task3_candidate_ranking.csv", index=False)

    comparison = summary[summary["strategy"].isin(["no_filter", "task2_final"]) | summary["strategy"].isin(by_strategy.head(5)["strategy"])].copy()
    comparison.to_csv(output_dir / "task3_baseline_comparison_by_split.csv", index=False)
    pivot.to_csv(output_dir / "task3_score_pivot.csv", index=False)
    return by_strategy


def run(
    data_root: Path,
    output_dir: Path,
    start: str,
    end: str,
    event_start: str,
    event_end: str,
    symbols: tuple[str, ...],
    windows: list[int],
    bin_seconds: int,
    task2_src: Path | None,
    smoke: bool,
    workers: int,
    match_modes: list[str],
) -> None:
    paths = DataPaths.from_root(data_root)
    table_dir = output_dir / "tables"
    figure_dir = output_dir / "figures"
    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    thresholds = compute_liq_thresholds(paths, start=TRAIN_START, end="2026-02-01", output_dir=table_dir)
    candidates = threshold_values(thresholds)
    if smoke:
        candidates = candidates[:2]
        windows = windows[:2]

    event_start_date = parse_date(event_start)
    event_end_date = parse_date(event_end)
    event_tasks = [
        (str(paths.data), current.isoformat(), symbol, candidates, bin_seconds)
        for current in iter_dates(event_start_date, event_end_date)
        for symbol in symbols
    ]
    event_rows: list[dict] = []
    if workers <= 1:
        for task in event_tasks:
            _, date_str, symbol, _, _ = task
            print(f"[event-study] {date_str} {symbol}", flush=True)
            event_rows.extend(event_study_worker(task))
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(event_study_worker, task): task for task in event_tasks}
            for future in as_completed(futures):
                _, date_str, symbol, _, _ = futures[future]
                print(f"[event-study-parallel] done {date_str} {symbol}", flush=True)
                event_rows.extend(future.result())

    event_study = aggregate_event_study(event_rows, table_dir)
    plot_event_study(event_study, figure_dir)

    _, summary = evaluate_grid_parallel(paths, table_dir, start, end, candidates, windows, symbols, task2_src, workers, match_modes)
    ranking = build_decision_table(summary, table_dir)

    (output_dir / "task3_run_config.json").write_text(
        json.dumps(
            {
                "data_root": str(paths.data),
                "metric_start": start,
                "metric_end": end,
                "event_start": event_start,
                "event_end": event_end,
                "symbols": symbols,
                "threshold_candidates": candidates,
                "windows": windows,
                "match_modes": match_modes,
                "bin_seconds": bin_seconds,
                "workers": workers,
                "top_strategy": None if ranking.empty else ranking.iloc[0].to_dict(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--start", default=TRAIN_START)
    parser.add_argument("--end", default=VALIDATION_END)
    parser.add_argument("--event-start", default=TRAIN_START)
    parser.add_argument("--event-end", default="2026-02-01")
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS), choices=list(SYMBOLS))
    parser.add_argument("--windows", nargs="+", type=int, default=[5, 10, 20, 30, 60, 120, 180, 300])
    parser.add_argument("--bin-seconds", type=int, default=10)
    parser.add_argument("--task2-src", default=None)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--match-modes",
        nargs="+",
        default=["taker_same_liquidation"],
        choices=["taker_same_liquidation", "taker_opposite_liquidation"],
    )
    args = parser.parse_args()

    run(
        data_root=Path(args.data_root).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        start=args.start,
        end=args.end,
        event_start=args.event_start,
        event_end=args.event_end,
        symbols=tuple(args.symbols),
        windows=args.windows,
        bin_seconds=args.bin_seconds,
        task2_src=Path(args.task2_src).expanduser().resolve() if args.task2_src else None,
        smoke=args.smoke,
        workers=args.workers,
        match_modes=args.match_modes,
    )


if __name__ == "__main__":
    main()
