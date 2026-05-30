from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

try:
    from task2_evaluate import (
        DataPaths,
        HORIZONS,
        SYMBOLS,
        VALIDATION_END,
        VALIDATION_START,
        add_markout_arrays,
        collect_streaming,
        date_to_us,
        iter_dates,
        load_bbo,
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
        SYMBOLS,
        VALIDATION_END,
        VALIDATION_START,
        add_markout_arrays,
        collect_streaming,
        date_to_us,
        iter_dates,
        load_bbo,
        load_trades,
        parse_date,
        safe_divide,
        scan_time,
        side_sign,
    )
    from .task2_solution import BYBIT_DELAY_US, _rolling_sum, _signed_liquidations


TURNOVER_CONSTRAINT_PER_DAY = 500_000.0
MAX_LOOKBACK_US = 30_000_000


def split_name(day: date) -> str:
    parsed = pd.Timestamp(day)
    if parsed < VALIDATION_START:
        return "train"
    if parsed < VALIDATION_END:
        return "validation"
    return "public_extra"


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


def mid_return_bps(trade_ts: np.ndarray, bbo: pl.DataFrame, window_us: int) -> np.ndarray:
    bbo_ts = bbo["timestamp"].to_numpy()
    mid = bbo["mid"].to_numpy().astype(np.float64, copy=False)
    current_idx = np.searchsorted(bbo_ts, trade_ts, side="right") - 1
    past_idx = np.searchsorted(bbo_ts, trade_ts - window_us, side="right") - 1
    out = np.full(len(trade_ts), np.nan, dtype=np.float64)
    ok = (current_idx >= 0) & (past_idx >= 0)
    positions = np.flatnonzero(ok)
    current_mid = mid[current_idx[ok]]
    past_mid = mid[past_idx[ok]]
    finite = np.isfinite(current_mid) & np.isfinite(past_mid) & (past_mid > 0)
    out[positions[finite]] = (current_mid[finite] - past_mid[finite]) / past_mid[finite] * 10_000.0
    return out


def rolling_sum_prior(event_ts: np.ndarray, values: np.ndarray, query_ts: np.ndarray, window_us: int) -> np.ndarray:
    if len(event_ts) == 0:
        return np.zeros(len(query_ts), dtype=np.float64)
    cumulative = np.concatenate([[0.0], np.cumsum(values, dtype=np.float64)])
    right = np.searchsorted(event_ts, query_ts, side="left")
    left = np.searchsorted(event_ts, query_ts - window_us, side="right")
    return cumulative[right] - cumulative[left]


def build_rule_flags(
    trades: pl.DataFrame,
    bbo: pl.DataFrame,
    liq_binance: pl.DataFrame,
    liq_bybit: pl.DataFrame,
    rule_set: str,
) -> dict[str, dict[int, np.ndarray]]:
    trade_ts = trades["timestamp"].to_numpy().astype(np.int64, copy=False)
    trade_sign = side_sign(trades["side"].to_numpy())

    raw_rules: dict[str, np.ndarray] = {}

    if rule_set in {"all", "core", "liq", "combo"}:
        binance_ts, binance_signed = _signed_liquidations(liq_binance, delay_us=0)
        bybit_ts_d0, bybit_signed_d0 = _signed_liquidations(liq_bybit, delay_us=0)
        bybit_ts_d200, bybit_signed_d200 = _signed_liquidations(liq_bybit, delay_us=BYBIT_DELAY_US)

        binance_1s = _rolling_sum(binance_ts, binance_signed, trade_ts, 1_000_000)
        binance_2s = _rolling_sum(binance_ts, binance_signed, trade_ts, 2_000_000)
        bybit_1s_d200 = _rolling_sum(bybit_ts_d200, bybit_signed_d200, trade_ts, 1_000_000)
        bybit_2s_d0 = _rolling_sum(bybit_ts_d0, bybit_signed_d0, trade_ts, 2_000_000)
        bybit_2s_d200 = _rolling_sum(bybit_ts_d200, bybit_signed_d200, trade_ts, 2_000_000)
        bybit_5s_d0 = _rolling_sum(bybit_ts_d0, bybit_signed_d0, trade_ts, 5_000_000)
        bybit_5s_d200 = _rolling_sum(bybit_ts_d200, bybit_signed_d200, trade_ts, 5_000_000)

        liq1_total_d200 = trade_sign * (binance_1s + bybit_1s_d200)
        liq2_total_d0 = trade_sign * (binance_2s + bybit_2s_d0)
        liq2_total_d200 = trade_sign * (binance_2s + bybit_2s_d200)
        bybit5_d0 = trade_sign * bybit_5s_d0
        bybit5_d200 = trade_sign * bybit_5s_d200

        raw_rules.update(
            {
                "baseline_liq1s_d200_gt_100k": liq1_total_d200 > 100_000.0,
                "liq2s_d0_gt_2m": liq2_total_d0 > 2_000_000.0,
                "liq2s_d200_gt_1m": liq2_total_d200 > 1_000_000.0,
                "liq2s_d200_gt_2m": liq2_total_d200 > 2_000_000.0,
                "bybit5s_d0_gt_2m": bybit5_d0 > 2_000_000.0,
                "bybit5s_d200_gt_2m": bybit5_d200 > 2_000_000.0,
            }
        )

    if rule_set in {"all", "core", "return", "combo"}:
        ret1 = trade_sign * mid_return_bps(trade_ts, bbo, 1_000_000)
        ret5 = trade_sign * mid_return_bps(trade_ts, bbo, 5_000_000)
        ret30 = trade_sign * mid_return_bps(trade_ts, bbo, 30_000_000)
        raw_rules.update(
            {
                "return1s_gt_20": ret1 > 20.0,
                "return5s_gt_20": ret5 > 20.0,
                "return5s_gt_50": ret5 > 50.0,
                "return5s_gt_100": ret5 > 100.0,
                "return30s_gt_50": ret30 > 50.0,
                "neg_return30s_gt_50": (-ret30) > 50.0,
            }
        )

    if rule_set in {"all", "flow"}:
        price = trades["price"].to_numpy().astype(np.float64, copy=False)
        amount = trades["amount"].to_numpy().astype(np.float64, copy=False)
        signed_notional = trade_sign * price * amount
        flow1 = trade_sign * rolling_sum_prior(trade_ts, signed_notional, trade_ts, 1_000_000)
        flow2 = trade_sign * rolling_sum_prior(trade_ts, signed_notional, trade_ts, 2_000_000)
        flow5 = trade_sign * rolling_sum_prior(trade_ts, signed_notional, trade_ts, 5_000_000)
        raw_rules.update(
            {
                "neg_trade_flow1s_gt_500k": (-flow1) > 500_000.0,
                "neg_trade_flow2s_gt_500k": (-flow2) > 500_000.0,
                "neg_trade_flow5s_gt_500k": (-flow5) > 500_000.0,
                "neg_trade_flow5s_gt_1m": (-flow5) > 1_000_000.0,
                "trade_flow250ms_gt_500k": (
                    trade_sign * rolling_sum_prior(trade_ts, signed_notional, trade_ts, 250_000)
                )
                > 500_000.0,
            }
        )

    if rule_set in {"all", "core", "combo"}:
        if "baseline_liq1s_d200_gt_100k" in raw_rules and "return5s_gt_50" in raw_rules:
            raw_rules["baseline_or_return5s_gt_50"] = raw_rules["baseline_liq1s_d200_gt_100k"] | raw_rules["return5s_gt_50"]
            raw_rules["baseline_and_return5s_gt_20"] = raw_rules["baseline_liq1s_d200_gt_100k"] & raw_rules["return5s_gt_20"]
        if "liq2s_d200_gt_2m" in raw_rules and "return5s_gt_50" in raw_rules:
            raw_rules["liq2s_or_return5s_gt_50"] = raw_rules["liq2s_d200_gt_2m"] | raw_rules["return5s_gt_50"]
            raw_rules["liq2s_and_return5s_gt_20"] = raw_rules["liq2s_d200_gt_2m"] & raw_rules["return5s_gt_20"]
        if "bybit5s_d200_gt_2m" in raw_rules and "return5s_gt_50" in raw_rules:
            raw_rules["bybit5s_or_return5s_gt_50"] = raw_rules["bybit5s_d200_gt_2m"] | raw_rules["return5s_gt_50"]

    rules = {name: {horizon: (~keep).astype(np.int8) for horizon in HORIZONS} for name, keep in raw_rules.items()}
    if rule_set in {"all", "core", "combo"} and "return5s_gt_50" in raw_rules and "liq2s_d200_gt_2m" in raw_rules:
        rules["horizon_specific_return_liq"] = {
            30: (~raw_rules["return5s_gt_50"]).astype(np.int8),
            120: (~raw_rules["return5s_gt_50"]).astype(np.int8),
            300: (~raw_rules["liq2s_d200_gt_2m"]).astype(np.int8),
        }
    if rule_set in {"all", "core", "combo"} and "return5s_gt_50" in raw_rules and "bybit5s_d200_gt_2m" in raw_rules:
        rules["horizon_specific_bybit_return"] = {
            30: (~raw_rules["return5s_gt_50"]).astype(np.int8),
            120: (~raw_rules["bybit5s_d200_gt_2m"]).astype(np.int8),
            300: (~raw_rules["liq2s_d200_gt_2m"]).astype(np.int8),
        }
    return rules


def weighted_mean(values: np.ndarray, weight: np.ndarray, mask: np.ndarray) -> float:
    valid = mask & np.isfinite(values) & np.isfinite(weight) & (weight > 0)
    if not np.any(valid):
        return float("nan")
    w = weight[valid]
    return float(np.sum(w * values[valid]) / np.sum(w))


def score_rules(
    date_str: str,
    split: str,
    symbol: str,
    trades: pl.DataFrame,
    bbo: pl.DataFrame,
    liq_binance: pl.DataFrame,
    liq_bybit: pl.DataFrame,
    rule_set: str,
) -> list[dict]:
    if trades.is_empty() or bbo.is_empty():
        return []

    weight, pnl_by_horizon, _ = add_markout_arrays(trades, bbo)
    flags_by_rule = build_rule_flags(trades, bbo, liq_binance, liq_bybit, rule_set)
    rows = []

    for rule_name, flags_by_horizon in flags_by_rule.items():
        for horizon, flags in flags_by_horizon.items():
            flags_bool = np.asarray(flags).astype(bool)
            pnl = pnl_by_horizon[horizon]
            valid = np.isfinite(pnl) & np.isfinite(weight) & (weight > 0)
            kept = valid & ~flags_bool
            filtered = valid & flags_bool
            rows.append(
                {
                    "date": date_str,
                    "split": split,
                    "symbol": symbol,
                    "rule": rule_name,
                    "horizon_s": horizon,
                    "pnl_all": weighted_mean(pnl, weight, valid),
                    "pnl_kept": weighted_mean(pnl, weight, kept),
                    "pnl_filtered": weighted_mean(pnl, weight, filtered),
                    "all_clipped_turnover": float(np.sum(weight[valid])),
                    "kept_clipped_turnover": float(np.sum(weight[kept])),
                    "filtered_clipped_turnover": float(np.sum(weight[filtered])),
                    "kept_trade_count": int(np.sum(kept)),
                    "filtered_trade_count": int(np.sum(filtered)),
                }
            )
    return rows


def summarize(rows: list[dict], by_split: bool) -> pd.DataFrame:
    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily
    group_cols = ["rule", "horizon_s"]
    if by_split:
        group_cols = ["split", *group_cols]
    daily["all_weighted_pnl_sum"] = daily["pnl_all"] * daily["all_clipped_turnover"]
    daily["kept_weighted_pnl_sum"] = daily["pnl_kept"].fillna(0.0) * daily["kept_clipped_turnover"]
    daily["filtered_weighted_pnl_sum"] = daily["pnl_filtered"].fillna(0.0) * daily["filtered_clipped_turnover"]
    out = (
        daily.groupby(group_cols, as_index=False)
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
    cols = [
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
    return out[cols].sort_values([*group_cols[:-1], "horizon_s", "score"], ascending=[*[True] * (len(group_cols) - 1), True, False])


def run(
    data_root: Path,
    output_dir: Path,
    start: str,
    end: str,
    symbols: tuple[str, ...],
    rule_set: str,
    trade_stride: int,
) -> None:
    paths = DataPaths.from_root(data_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    start_date = parse_date(start)
    end_date = parse_date(end)
    rows: list[dict] = []

    for current in iter_dates(start_date, end_date):
        date_str = current.isoformat()
        split = split_name(current)
        start_us = date_to_us(current)
        end_us = date_to_us(current + timedelta(days=1))
        for symbol in symbols:
            print(f"[compare-rules] {date_str} {symbol}", flush=True)
            trades = load_trades(paths, symbol, start_us, end_us)
            if trades.is_empty():
                continue
            trades = stride_trades(trades, trade_stride)
            if trades.is_empty():
                continue
            bbo = load_bbo(paths, symbol, start_us - MAX_LOOKBACK_US, end_us + max(HORIZONS) * 1_000_000 + 1_000_000)
            liq_binance = load_liq_with_lookback(paths.liq_binance(symbol), start_us, end_us, MAX_LOOKBACK_US)
            liq_bybit = load_liq_with_lookback(paths.liq_bybit(symbol), start_us, end_us, MAX_LOOKBACK_US)
            rows.extend(score_rules(date_str, split, symbol, trades, bbo, liq_binance, liq_bybit, rule_set))

    daily = pd.DataFrame(rows)
    by_split = summarize(rows, by_split=True)
    overall = summarize(rows, by_split=False)
    daily.to_csv(output_dir / "rule_daily_metrics.csv", index=False)
    by_split.to_csv(output_dir / "rule_summary_by_split.csv", index=False)
    overall.to_csv(output_dir / "rule_summary_overall.csv", index=False)
    (output_dir / "rule_compare_config.json").write_text(
        json.dumps(
            {
                "data_root": str(paths.data),
                "start": start,
                "end": end,
                "symbols": symbols,
                "rule_set": rule_set,
                "trade_stride": trade_stride,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\nTop validation rules", flush=True)
    if not by_split.empty:
        validation = by_split[(by_split["split"] == "validation") & (by_split["constraint_ok"])]
        print(validation.sort_values(["horizon_s", "score"], ascending=[True, False]).groupby("horizon_s").head(10).to_string(index=False), flush=True)
    print("\nTop overall rules", flush=True)
    if not overall.empty:
        print(overall[overall["constraint_ok"]].sort_values(["horizon_s", "score"], ascending=[True, False]).groupby("horizon_s").head(10).to_string(index=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-dir", default="outputs_rule_compare")
    parser.add_argument("--start", default="2025-12-01")
    parser.add_argument("--end", default="2026-03-01")
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS), choices=list(SYMBOLS))
    parser.add_argument("--rule-set", choices=["all", "core", "liq", "return", "flow", "combo"], default="core")
    parser.add_argument("--trade-stride", type=int, default=1)
    args = parser.parse_args()

    run(
        data_root=Path(args.data_root).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        start=args.start,
        end=args.end,
        symbols=tuple(args.symbols),
        rule_set=args.rule_set,
        trade_stride=max(1, args.trade_stride),
    )


if __name__ == "__main__":
    main()
