from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

try:
    from task2_evaluate import (
        DataPaths,
        HORIZONS,
        MAX_NOTIONAL_WEIGHT,
        SYMBOLS,
        TRAIN_START,
        VALIDATION_END,
        VALIDATION_START,
        add_markout_arrays,
        collect_streaming,
        date_to_us,
        iter_dates,
        load_bbo,
        load_liq,
        load_trades,
        parse_date,
        safe_divide,
        scan_time,
        side_sign,
    )
    from task2_solution import BYBIT_DELAY_US, _rolling_sum, _signed_liquidations
except ModuleNotFoundError:
    from .task2_evaluate import (
        DataPaths,
        HORIZONS,
        MAX_NOTIONAL_WEIGHT,
        SYMBOLS,
        TRAIN_START,
        VALIDATION_END,
        VALIDATION_START,
        add_markout_arrays,
        collect_streaming,
        date_to_us,
        iter_dates,
        load_bbo,
        load_liq,
        load_trades,
        parse_date,
        safe_divide,
        scan_time,
        side_sign,
    )
    from .task2_solution import BYBIT_DELAY_US, _rolling_sum, _signed_liquidations


LIQ_WINDOWS_US = (100_000, 250_000, 500_000, 1_000_000, 2_000_000, 5_000_000)
TRADE_WINDOWS_US = (250_000, 500_000, 1_000_000, 2_000_000, 5_000_000)
RETURN_WINDOWS_US = (1_000_000, 5_000_000, 30_000_000)
BYBIT_DELAYS_US = (0, 100_000, 200_000, 500_000, 1_000_000)

LIQ_THRESHOLDS = (
    -20_000_000.0,
    -10_000_000.0,
    -5_000_000.0,
    -2_000_000.0,
    -1_000_000.0,
    -500_000.0,
    -200_000.0,
    -100_000.0,
    -50_000.0,
    0.0,
    50_000.0,
    100_000.0,
    200_000.0,
    500_000.0,
    1_000_000.0,
    2_000_000.0,
    5_000_000.0,
    10_000_000.0,
    20_000_000.0,
)
FLOW_THRESHOLDS = (
    -250_000_000.0,
    -100_000_000.0,
    -50_000_000.0,
    -20_000_000.0,
    -10_000_000.0,
    -5_000_000.0,
    -2_000_000.0,
    -1_000_000.0,
    -500_000.0,
    0.0,
    500_000.0,
    1_000_000.0,
    2_000_000.0,
    5_000_000.0,
    10_000_000.0,
    20_000_000.0,
    50_000_000.0,
    100_000_000.0,
    250_000_000.0,
)
IMBALANCE_THRESHOLDS = (-1.0, -0.75, -0.5, -0.25, -0.1, 0.0, 0.1, 0.25, 0.5, 0.75, 1.0)
SPREAD_SCORE_THRESHOLDS = (-100.0, -50.0, -20.0, -10.0, -5.0, -2.0, -1.0, -0.5, -0.1, 0.0)
RETURN_THRESHOLDS = (-200.0, -100.0, -50.0, -20.0, -10.0, -5.0, -2.0, -1.0, 0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0)
NOTIONAL_SCORE_THRESHOLDS = (-100_000.0, -50_000.0, -20_000.0, -10_000.0, -5_000.0, -2_000.0, -1_000.0, -500.0, -100.0, 0.0)
KEEP_FRACTIONS = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.50)


@dataclass(frozen=True)
class Candidate:
    name: str
    family: str
    kind: str
    window_us: int = 0
    delay_us: int = BYBIT_DELAY_US
    direction: float = 1.0


def split_name(day: date) -> str:
    parsed = pd.Timestamp(day)
    if TRAIN_START <= parsed < VALIDATION_START:
        return "train"
    if VALIDATION_START <= parsed < VALIDATION_END:
        return "validation"
    return "public_extra"


def fmt_ms(value_us: int) -> str:
    if value_us % 1_000_000 == 0:
        return f"{value_us // 1_000_000}s"
    return f"{value_us // 1_000}ms"


def make_candidates(preset: str) -> list[Candidate]:
    candidates: list[Candidate] = []

    if preset in {"baseline", "selected"}:
        candidates.append(Candidate("liq_total_w1s_d200ms", "liq", "liq_total", 1_000_000, 200_000))
        candidates.append(Candidate("liq_total_w500ms_d200ms", "liq", "liq_total", 500_000, 200_000))
        candidates.append(Candidate("liq_total_w2s_d200ms", "liq", "liq_total", 2_000_000, 200_000))
        candidates.append(Candidate("liq_binance_w1s", "liq", "liq_binance", 1_000_000, 0))
        candidates.append(Candidate("liq_bybit_w1s_d200ms", "liq", "liq_bybit", 1_000_000, 200_000))
    else:
        for window_us in LIQ_WINDOWS_US:
            candidates.append(Candidate(f"liq_binance_w{fmt_ms(window_us)}", "liq", "liq_binance", window_us, 0))
            for delay_us in BYBIT_DELAYS_US:
                delay = fmt_ms(delay_us)
                window = fmt_ms(window_us)
                candidates.append(Candidate(f"liq_bybit_w{window}_d{delay}", "liq", "liq_bybit", window_us, delay_us))
                candidates.append(Candidate(f"liq_total_w{window}_d{delay}", "liq", "liq_total", window_us, delay_us))

    if preset != "baseline":
        for window_us in TRADE_WINDOWS_US:
            window = fmt_ms(window_us)
            candidates.append(Candidate(f"trade_flow_w{window}", "flow", "trade_flow", window_us))
            candidates.append(Candidate(f"neg_trade_flow_w{window}", "flow", "trade_flow", window_us, direction=-1.0))

        for window_us in RETURN_WINDOWS_US:
            window = fmt_ms(window_us)
            candidates.append(Candidate(f"return_w{window}", "return", "return", window_us))
            candidates.append(Candidate(f"neg_return_w{window}", "return", "return", window_us, direction=-1.0))

        candidates.extend(
            [
                Candidate("book_imbalance", "imbalance", "book_imbalance"),
                Candidate("neg_book_imbalance", "imbalance", "book_imbalance", direction=-1.0),
                Candidate("low_spread_bps", "spread", "spread", direction=-1.0),
                Candidate("small_notional", "notional", "notional", direction=-1.0),
                Candidate("large_notional", "notional", "notional"),
            ]
        )

    return candidates


def filter_candidates(candidates: list[Candidate], filters: tuple[str, ...]) -> list[Candidate]:
    if not filters:
        return candidates
    lowered = tuple(item.lower() for item in filters)
    return [candidate for candidate in candidates if any(item in candidate.name.lower() for item in lowered)]


def thresholds_for(candidate: Candidate) -> tuple[float, ...]:
    if candidate.family == "liq":
        return LIQ_THRESHOLDS
    if candidate.family == "flow":
        return FLOW_THRESHOLDS
    if candidate.family == "imbalance":
        return IMBALANCE_THRESHOLDS
    if candidate.family == "spread":
        return SPREAD_SCORE_THRESHOLDS
    if candidate.family == "return":
        return RETURN_THRESHOLDS
    if candidate.family == "notional":
        return NOTIONAL_SCORE_THRESHOLDS
    raise ValueError(f"Unsupported candidate family: {candidate.family}")


def load_liq_with_lookback(path: Path, start_us: int, end_us: int, lookback_us: int) -> pl.DataFrame:
    return collect_streaming(
        scan_time(path, start_us - lookback_us, end_us)
        .select(["timestamp", "ticker", "side", "price", "amount"])
        .sort("timestamp")
    )


def stride_trades(trades: pl.DataFrame, stride: int) -> pl.DataFrame:
    if stride <= 1 or trades.is_empty():
        return trades
    return trades.with_row_index("__row").filter((pl.col("__row") % stride) == 0).drop("__row")


def bbo_at_trades(trade_ts: np.ndarray, bbo: pl.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    bbo_ts = bbo["timestamp"].to_numpy()
    bid_price = bbo["bid_price"].to_numpy().astype(np.float64, copy=False)
    ask_price = bbo["ask_price"].to_numpy().astype(np.float64, copy=False)
    bid_amount = bbo["bid_amount"].to_numpy().astype(np.float64, copy=False)
    ask_amount = bbo["ask_amount"].to_numpy().astype(np.float64, copy=False)

    idx = np.searchsorted(bbo_ts, trade_ts, side="right") - 1
    ok = idx >= 0
    bid = np.full(len(trade_ts), np.nan, dtype=np.float64)
    ask = np.full(len(trade_ts), np.nan, dtype=np.float64)
    bid_size = np.full(len(trade_ts), np.nan, dtype=np.float64)
    ask_size = np.full(len(trade_ts), np.nan, dtype=np.float64)
    bid[ok] = bid_price[idx[ok]]
    ask[ok] = ask_price[idx[ok]]
    bid_size[ok] = bid_amount[idx[ok]]
    ask_size[ok] = ask_amount[idx[ok]]
    return bid, ask, bid_size, ask_size


def mid_return_at_trades(trade_ts: np.ndarray, bbo: pl.DataFrame, window_us: int) -> np.ndarray:
    bbo_ts = bbo["timestamp"].to_numpy()
    mid = bbo["mid"].to_numpy().astype(np.float64, copy=False)
    current_idx = np.searchsorted(bbo_ts, trade_ts, side="right") - 1
    past_idx = np.searchsorted(bbo_ts, trade_ts - window_us, side="right") - 1
    out = np.full(len(trade_ts), np.nan, dtype=np.float64)
    ok = (current_idx >= 0) & (past_idx >= 0)
    current_mid = mid[current_idx[ok]]
    past_mid = mid[past_idx[ok]]
    valid = np.isfinite(current_mid) & np.isfinite(past_mid) & (past_mid > 0)
    ok_positions = np.flatnonzero(ok)
    out[ok_positions[valid]] = (current_mid[valid] - past_mid[valid]) / past_mid[valid] * 10_000.0
    return out


def rolling_sum_prior(event_ts: np.ndarray, values: np.ndarray, query_ts: np.ndarray, window_us: int) -> np.ndarray:
    if len(event_ts) == 0:
        return np.zeros(len(query_ts), dtype=np.float64)
    cumulative = np.concatenate([[0.0], np.cumsum(values, dtype=np.float64)])
    right = np.searchsorted(event_ts, query_ts, side="left")
    left = np.searchsorted(event_ts, query_ts - window_us, side="right")
    return cumulative[right] - cumulative[left]


def build_feature(
    candidate: Candidate,
    trades: pl.DataFrame,
    bbo: pl.DataFrame,
    liq_binance: pl.DataFrame,
    liq_bybit: pl.DataFrame,
) -> np.ndarray:
    trade_ts = trades["timestamp"].to_numpy().astype(np.int64, copy=False)
    trade_sign = side_sign(trades["side"].to_numpy())

    if candidate.kind.startswith("liq"):
        binance_ts, binance_signed = _signed_liquidations(liq_binance, delay_us=0)
        bybit_ts, bybit_signed = _signed_liquidations(liq_bybit, delay_us=candidate.delay_us)
        feature = np.zeros(len(trades), dtype=np.float64)
        if candidate.kind in {"liq_binance", "liq_total"}:
            feature += _rolling_sum(binance_ts, binance_signed, trade_ts, candidate.window_us)
        if candidate.kind in {"liq_bybit", "liq_total"}:
            feature += _rolling_sum(bybit_ts, bybit_signed, trade_ts, candidate.window_us)
        return candidate.direction * trade_sign * feature

    if candidate.kind == "trade_flow":
        price = trades["price"].to_numpy().astype(np.float64, copy=False)
        amount = trades["amount"].to_numpy().astype(np.float64, copy=False)
        signed_notional = side_sign(trades["side"].to_numpy()) * price * amount
        feature = rolling_sum_prior(trade_ts, signed_notional, trade_ts, candidate.window_us)
        return candidate.direction * trade_sign * feature

    if candidate.kind == "book_imbalance":
        bid, ask, bid_size, ask_size = bbo_at_trades(trade_ts, bbo)
        del bid, ask
        denom = bid_size + ask_size
        imbalance = np.divide(bid_size - ask_size, denom, out=np.full_like(denom, np.nan), where=denom > 0)
        return candidate.direction * trade_sign * imbalance

    if candidate.kind == "spread":
        bid, ask, _, _ = bbo_at_trades(trade_ts, bbo)
        mid = (bid + ask) / 2.0
        spread_bps = np.divide(ask - bid, mid, out=np.full_like(mid, np.nan), where=mid > 0) * 10_000.0
        return candidate.direction * spread_bps

    if candidate.kind == "return":
        ret_bps = mid_return_at_trades(trade_ts, bbo, candidate.window_us)
        return candidate.direction * trade_sign * ret_bps

    if candidate.kind == "notional":
        price = trades["price"].to_numpy().astype(np.float64, copy=False)
        amount = trades["amount"].to_numpy().astype(np.float64, copy=False)
        notional = np.minimum(price * amount, MAX_NOTIONAL_WEIGHT)
        return candidate.direction * notional

    raise ValueError(f"Unsupported candidate kind: {candidate.kind}")


def empty_accumulator() -> dict[str, float]:
    return {
        "all_clipped_turnover": 0.0,
        "kept_clipped_turnover": 0.0,
        "filtered_clipped_turnover": 0.0,
        "all_weighted_pnl_sum": 0.0,
        "kept_weighted_pnl_sum": 0.0,
        "filtered_weighted_pnl_sum": 0.0,
        "kept_trade_count": 0.0,
        "filtered_trade_count": 0.0,
    }


def update_threshold_accumulators(
    accumulators: dict[tuple, dict[str, float]],
    candidate: Candidate,
    split: str,
    score: np.ndarray,
    weight: np.ndarray,
    pnl_by_horizon: dict[int, np.ndarray],
) -> None:
    thresholds = thresholds_for(candidate)
    base_valid = np.isfinite(score) & np.isfinite(weight) & (weight > 0)
    for horizon, pnl in pnl_by_horizon.items():
        valid = base_valid & np.isfinite(pnl)
        if not np.any(valid):
            continue

        feature = score[valid]
        w = weight[valid]
        wpnl = w * pnl[valid]
        order = np.argsort(feature, kind="mergesort")
        sorted_feature = feature[order]
        sorted_w = w[order]
        sorted_wpnl = wpnl[order]
        cum_w = np.concatenate([[0.0], np.cumsum(sorted_w, dtype=np.float64)])
        cum_wpnl = np.concatenate([[0.0], np.cumsum(sorted_wpnl, dtype=np.float64)])
        total_w = float(cum_w[-1])
        total_wpnl = float(cum_wpnl[-1])
        total_n = len(sorted_feature)

        for threshold in thresholds:
            idx = int(np.searchsorted(sorted_feature, threshold, side="right"))
            filtered_w = float(cum_w[idx])
            filtered_wpnl = float(cum_wpnl[idx])
            kept_w = total_w - filtered_w
            kept_wpnl = total_wpnl - filtered_wpnl
            key = (candidate.name, candidate.family, horizon, split, "threshold", threshold)
            acc = accumulators.setdefault(key, empty_accumulator())
            acc["all_clipped_turnover"] += total_w
            acc["kept_clipped_turnover"] += kept_w
            acc["filtered_clipped_turnover"] += filtered_w
            acc["all_weighted_pnl_sum"] += total_wpnl
            acc["kept_weighted_pnl_sum"] += kept_wpnl
            acc["filtered_weighted_pnl_sum"] += filtered_wpnl
            acc["kept_trade_count"] += total_n - idx
            acc["filtered_trade_count"] += idx


def update_fraction_accumulators_from_sorted(
    accumulators: dict[tuple, dict[str, float]],
    candidate: Candidate,
    split: str,
    horizon: int,
    total_n: int,
    total_w: float,
    total_wpnl: float,
    cum_w: np.ndarray,
    cum_wpnl: np.ndarray,
) -> None:
    for keep_fraction in KEEP_FRACTIONS:
        keep_count = max(1, int(np.ceil(total_n * keep_fraction)))
        idx = max(0, total_n - keep_count)
        filtered_w = float(cum_w[idx])
        filtered_wpnl = float(cum_wpnl[idx])
        kept_w = total_w - filtered_w
        kept_wpnl = total_wpnl - filtered_wpnl
        key = (candidate.name, candidate.family, horizon, split, "keep_fraction", keep_fraction)
        acc = accumulators.setdefault(key, empty_accumulator())
        acc["all_clipped_turnover"] += total_w
        acc["kept_clipped_turnover"] += kept_w
        acc["filtered_clipped_turnover"] += filtered_w
        acc["all_weighted_pnl_sum"] += total_wpnl
        acc["kept_weighted_pnl_sum"] += kept_wpnl
        acc["filtered_weighted_pnl_sum"] += filtered_wpnl
        acc["kept_trade_count"] += keep_count
        acc["filtered_trade_count"] += total_n - keep_count


def update_accumulators(
    threshold_accumulators: dict[tuple, dict[str, float]],
    fraction_accumulators: dict[tuple, dict[str, float]],
    candidate: Candidate,
    split: str,
    score: np.ndarray,
    weight: np.ndarray,
    pnl_by_horizon: dict[int, np.ndarray],
    include_fraction: bool,
) -> None:
    thresholds = thresholds_for(candidate)
    base_valid = np.isfinite(score) & np.isfinite(weight) & (weight > 0)
    for horizon, pnl in pnl_by_horizon.items():
        valid = base_valid & np.isfinite(pnl)
        if not np.any(valid):
            continue

        feature = score[valid]
        w = weight[valid]
        wpnl = w * pnl[valid]
        order = np.argsort(feature, kind="mergesort")
        sorted_feature = feature[order]
        sorted_w = w[order]
        sorted_wpnl = wpnl[order]
        cum_w = np.concatenate([[0.0], np.cumsum(sorted_w, dtype=np.float64)])
        cum_wpnl = np.concatenate([[0.0], np.cumsum(sorted_wpnl, dtype=np.float64)])
        total_w = float(cum_w[-1])
        total_wpnl = float(cum_wpnl[-1])
        total_n = len(sorted_feature)

        for threshold in thresholds:
            idx = int(np.searchsorted(sorted_feature, threshold, side="right"))
            filtered_w = float(cum_w[idx])
            filtered_wpnl = float(cum_wpnl[idx])
            kept_w = total_w - filtered_w
            kept_wpnl = total_wpnl - filtered_wpnl
            key = (candidate.name, candidate.family, horizon, split, "threshold", threshold)
            acc = threshold_accumulators.setdefault(key, empty_accumulator())
            acc["all_clipped_turnover"] += total_w
            acc["kept_clipped_turnover"] += kept_w
            acc["filtered_clipped_turnover"] += filtered_w
            acc["all_weighted_pnl_sum"] += total_wpnl
            acc["kept_weighted_pnl_sum"] += kept_wpnl
            acc["filtered_weighted_pnl_sum"] += filtered_wpnl
            acc["kept_trade_count"] += total_n - idx
            acc["filtered_trade_count"] += idx

        if include_fraction:
            update_fraction_accumulators_from_sorted(
                fraction_accumulators,
                candidate,
                split,
                horizon,
                total_n,
                total_w,
                total_wpnl,
                cum_w,
                cum_wpnl,
            )


def summarize_accumulators(accumulators: dict[tuple, dict[str, float]], day_counts: dict[str, int]) -> pd.DataFrame:
    rows = []
    for (candidate, family, horizon, split, rule_type, value), acc in accumulators.items():
        days = day_counts.get(split, 0)
        all_turnover = acc["all_clipped_turnover"]
        kept_turnover = acc["kept_clipped_turnover"]
        filtered_turnover = acc["filtered_clipped_turnover"]
        pnl_all = acc["all_weighted_pnl_sum"] / all_turnover if all_turnover else np.nan
        pnl_kept = acc["kept_weighted_pnl_sum"] / kept_turnover if kept_turnover else np.nan
        pnl_filtered = acc["filtered_weighted_pnl_sum"] / filtered_turnover if filtered_turnover else np.nan
        kept_turnover_per_day = kept_turnover / days if days else np.nan
        rows.append(
            {
                "candidate": candidate,
                "family": family,
                "horizon_s": horizon,
                "split": split,
                "rule_type": rule_type,
                "rule_value": value,
                "days": days,
                "pnl_all": pnl_all,
                "pnl_kept": pnl_kept,
                "pnl_filtered": pnl_filtered,
                "score": pnl_kept - pnl_all,
                "kept_turnover_per_day": kept_turnover_per_day,
                "constraint_ok": kept_turnover_per_day >= 500_000.0,
                "kept_trade_count": int(acc["kept_trade_count"]),
                "filtered_trade_count": int(acc["filtered_trade_count"]),
                "all_clipped_turnover": all_turnover,
                "kept_clipped_turnover": kept_turnover,
                "filtered_clipped_turnover": filtered_turnover,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["split", "horizon_s", "score"], ascending=[True, True, False])


def summarize_overall(summary: pd.DataFrame, rule_type: str) -> pd.DataFrame:
    if summary.empty:
        return summary
    source = summary[summary["rule_type"] == rule_type].copy()
    group_cols = ["candidate", "family", "horizon_s", "rule_type", "rule_value"]
    source["all_weighted_pnl_sum"] = source["pnl_all"] * source["all_clipped_turnover"]
    source["kept_weighted_pnl_sum"] = source["pnl_kept"].fillna(0.0) * source["kept_clipped_turnover"]
    source["filtered_weighted_pnl_sum"] = source["pnl_filtered"].fillna(0.0) * source["filtered_clipped_turnover"]
    out = (
        source.groupby(group_cols, as_index=False)
        .agg(
            days=("days", "sum"),
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
    out["constraint_ok"] = out["kept_turnover_per_day"] >= 500_000.0
    return out.sort_values(["horizon_s", "score"], ascending=[True, False])


def best_validation(summary: pd.DataFrame, rule_type: str) -> pd.DataFrame:
    if summary.empty:
        return summary
    source = summary[
        (summary["rule_type"] == rule_type)
        & (summary["split"] == "validation")
        & (summary["constraint_ok"])
        & np.isfinite(summary["score"])
    ].copy()
    if source.empty:
        return source
    source = source.sort_values(["horizon_s", "score"], ascending=[True, False])
    return source.groupby("horizon_s", as_index=False).head(25)


def run(
    data_root: Path,
    output_dir: Path,
    start: str,
    end: str,
    symbols: tuple[str, ...],
    preset: str,
    sample_every: int,
    trade_stride: int,
    candidate_filters: tuple[str, ...],
    include_fraction: bool,
) -> None:
    paths = DataPaths.from_root(data_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = filter_candidates(make_candidates(preset), candidate_filters)
    if not candidates:
        raise ValueError("No candidates selected")
    max_window = max([c.window_us + c.delay_us for c in candidates] + [BYBIT_DELAY_US + 1_000_000])
    start_date = parse_date(start)
    end_date = parse_date(end)
    threshold_accumulators: dict[tuple, dict[str, float]] = {}
    fraction_accumulators: dict[tuple, dict[str, float]] = {}
    processed_dates_by_split: dict[str, set[str]] = {"train": set(), "validation": set(), "public_extra": set()}

    for day_index, current in enumerate(iter_dates(start_date, end_date)):
        if sample_every > 1 and day_index % sample_every != 0:
            continue
        date_str = current.isoformat()
        split = split_name(current)
        processed_dates_by_split[split].add(date_str)
        start_us = date_to_us(current)
        end_us = date_to_us(current + timedelta(days=1))
        for symbol in symbols:
            print(f"[research] {date_str} {symbol} preset={preset}", flush=True)
            trades = load_trades(paths, symbol, start_us, end_us)
            if trades.is_empty():
                continue
            trades = stride_trades(trades, trade_stride)
            if trades.is_empty():
                continue
            bbo = load_bbo(paths, symbol, start_us - max_window - max(HORIZONS) * 1_000_000, end_us + max(HORIZONS) * 1_000_000 + 1_000_000)
            if bbo.is_empty():
                continue
            liq_binance = load_liq_with_lookback(paths.liq_binance(symbol), start_us, end_us, max_window)
            liq_bybit = load_liq_with_lookback(paths.liq_bybit(symbol), start_us, end_us, max_window)
            weight, pnl_by_horizon, _ = add_markout_arrays(trades, bbo)

            for candidate in candidates:
                score = build_feature(candidate, trades, bbo, liq_binance, liq_bybit)
                update_accumulators(
                    threshold_accumulators,
                    fraction_accumulators,
                    candidate,
                    split,
                    score,
                    weight,
                    pnl_by_horizon,
                    include_fraction,
                )

    day_counts = {split: len(days) for split, days in processed_dates_by_split.items()}
    threshold_summary = summarize_accumulators(threshold_accumulators, day_counts)
    threshold_overall = summarize_overall(threshold_summary, "threshold")
    threshold_best = best_validation(threshold_summary, "threshold")

    threshold_summary.to_csv(output_dir / "threshold_summary_by_split.csv", index=False)
    threshold_overall.to_csv(output_dir / "threshold_summary_overall.csv", index=False)
    threshold_best.to_csv(output_dir / "threshold_best_validation.csv", index=False)

    if include_fraction:
        fraction_summary = summarize_accumulators(fraction_accumulators, day_counts)
        fraction_overall = summarize_overall(fraction_summary, "keep_fraction")
        fraction_best = best_validation(fraction_summary, "keep_fraction")
        fraction_summary.to_csv(output_dir / "fraction_summary_by_split.csv", index=False)
        fraction_overall.to_csv(output_dir / "fraction_summary_overall.csv", index=False)
        fraction_best.to_csv(output_dir / "fraction_best_validation.csv", index=False)

    config = {
        "data_root": str(paths.data),
        "start": start,
        "end": end,
        "symbols": symbols,
        "preset": preset,
        "sample_every": sample_every,
        "trade_stride": trade_stride,
        "candidate_filters": candidate_filters,
        "include_fraction": include_fraction,
        "candidate_count": len(candidates),
        "day_counts": day_counts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "research_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    print("\nBest deployable threshold candidates on validation", flush=True)
    print(threshold_best.head(30).to_string(index=False), flush=True)
    if include_fraction:
        print("\nBest exploratory top-fraction candidates on validation", flush=True)
        print(fraction_best.head(30).to_string(index=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-dir", default="outputs_research")
    parser.add_argument("--start", default="2025-12-01")
    parser.add_argument("--end", default="2026-03-01")
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS), choices=list(SYMBOLS))
    parser.add_argument("--preset", choices=["baseline", "selected", "broad"], default="selected")
    parser.add_argument("--sample-every", type=int, default=1)
    parser.add_argument("--trade-stride", type=int, default=1)
    parser.add_argument("--candidate-filter", nargs="*", default=[])
    parser.add_argument("--include-fraction", action="store_true")
    args = parser.parse_args()

    run(
        data_root=Path(args.data_root).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        start=args.start,
        end=args.end,
        symbols=tuple(args.symbols),
        preset=args.preset,
        sample_every=max(1, args.sample_every),
        trade_stride=max(1, args.trade_stride),
        candidate_filters=tuple(args.candidate_filter),
        include_fraction=args.include_fraction,
    )


if __name__ == "__main__":
    main()
