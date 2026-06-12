from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import polars as pl

try:
    from task3_solution import BYBIT_DELAY_US, HORIZONS, LARGE_LIQ_THRESHOLD, REACTION_WINDOW_SECONDS, predict
except ModuleNotFoundError:
    from .task3_solution import BYBIT_DELAY_US, HORIZONS, LARGE_LIQ_THRESHOLD, REACTION_WINDOW_SECONDS, predict


MAX_NOTIONAL_WEIGHT = 100_000.0
MAKER_REBATE_BPS = 0.5
TURNOVER_CONSTRAINT_PER_DAY = 500_000.0
SYMBOLS = ("btcusdt", "ethusdt")
TRAIN_START = pd.Timestamp("2025-12-01")
VALIDATION_START = pd.Timestamp("2026-02-01")
VALIDATION_END = pd.Timestamp("2026-03-01")


def collect_streaming(lf: pl.LazyFrame) -> pl.DataFrame:
    try:
        return lf.collect(engine="streaming")
    except TypeError:
        return lf.collect(streaming=True)


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_to_us(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp() * 1_000_000)


def iter_dates(start: date, end: date):
    cur = start
    while cur < end:
        yield cur
        cur += timedelta(days=1)


@dataclass(frozen=True)
class DataPaths:
    data: Path

    @classmethod
    def from_root(cls, root: Path) -> "DataPaths":
        candidates = [
            root,
            root / "data",
            root / "liquidation_task" / "data",
            root / "liquidation_task" / "liquidation_task" / "data",
            root / "liquidation_task_0520" / "data",
            root / "liquidation_task_0520" / "liquidation_task" / "data",
            root / "liquidation_task_0520_unpacked" / "data",
            root / "liquidation_task_0520_unpacked" / "liquidation_task" / "data",
        ]
        data = next((p for p in candidates if (p / "binance_trades").exists()), None)
        if data is None:
            raise FileNotFoundError(f"Cannot find liquidation task data under {root}")
        return cls(data=data)

    def trades(self, symbol: str) -> Path:
        return self.data / "binance_trades" / f"perp_{symbol}.parquet"

    def bbo(self, symbol: str) -> Path:
        return self.data / "binance_booktickers" / f"perp_{symbol}.parquet"

    def liq_binance(self, symbol: str) -> Path:
        return self.data / "binance_liquidations" / f"perp_{symbol}.parquet"

    def liq_bybit(self, symbol: str) -> Path:
        return self.data / "bybit_liquidations" / f"{symbol}.parquet"


def scan_time(path: Path, start_us: int, end_us: int) -> pl.LazyFrame:
    return pl.scan_parquet(path).filter((pl.col("timestamp") >= start_us) & (pl.col("timestamp") < end_us))


def load_trades(paths: DataPaths, symbol: str, start_us: int, end_us: int) -> pl.DataFrame:
    return collect_streaming(
        scan_time(paths.trades(symbol), start_us, end_us)
        .select(["timestamp", "ticker", "side", "price", "amount"])
        .sort("timestamp")
    )


def load_bbo(paths: DataPaths, symbol: str, start_us: int, end_us: int) -> pl.DataFrame:
    return collect_streaming(
        scan_time(paths.bbo(symbol), start_us, end_us)
        .select(["timestamp", "bid_price", "bid_amount", "ask_price", "ask_amount"])
        .with_columns(((pl.col("bid_price") + pl.col("ask_price")) / 2.0).alias("mid"))
        .sort("timestamp")
    )


def load_liq(path: Path, start_us: int, end_us: int) -> pl.DataFrame:
    return collect_streaming(
        scan_time(path, start_us, end_us)
        .select(["timestamp", "ticker", "side", "price", "amount"])
        .sort("timestamp")
    )


def side_sign(side: np.ndarray) -> np.ndarray:
    return np.where(np.char.lower(np.asarray(side).astype(str)) == "buy", 1.0, -1.0)


def add_markout_arrays(trades: pl.DataFrame, bbo: pl.DataFrame) -> tuple[np.ndarray, dict[int, np.ndarray], np.ndarray, np.ndarray]:
    trade_ts = trades["timestamp"].to_numpy()
    price = trades["price"].to_numpy().astype(np.float64, copy=False)
    amount = trades["amount"].to_numpy().astype(np.float64, copy=False)
    sign = side_sign(trades["side"].to_numpy())
    weight = np.minimum(price * amount, MAX_NOTIONAL_WEIGHT)

    bbo_ts = bbo["timestamp"].to_numpy()
    mid = bbo["mid"].to_numpy().astype(np.float64, copy=False)
    max_bbo_ts = int(bbo_ts[-1]) if len(bbo_ts) else -1

    pnl_by_horizon: dict[int, np.ndarray] = {}
    for horizon in HORIZONS:
        target_ts = trade_ts + horizon * 1_000_000
        idx = np.searchsorted(bbo_ts, target_ts, side="right") - 1
        future_mid = np.full(len(trades), np.nan, dtype=np.float64)
        ok = (idx >= 0) & (target_ts <= max_bbo_ts)
        future_mid[ok] = mid[idx[ok]]
        pnl_by_horizon[horizon] = -sign * ((future_mid - price) / price * 10_000.0) + MAKER_REBATE_BPS

    return weight, pnl_by_horizon, trade_ts, sign


def weighted_mean(values: np.ndarray, weight: np.ndarray, mask: np.ndarray) -> float:
    valid = mask & np.isfinite(values) & np.isfinite(weight) & (weight > 0)
    if not np.any(valid):
        return float("nan")
    w = weight[valid]
    return float(np.sum(w * values[valid]) / np.sum(w))


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.div(denominator.where(denominator != 0))


PredictFn = Callable[[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame], dict[int, np.ndarray]]


def score_one_day(
    date_str: str,
    symbol: str,
    trades: pl.DataFrame,
    bbo: pl.DataFrame,
    liq_binance: pl.DataFrame,
    liq_bybit: pl.DataFrame,
    predict_fn: PredictFn = predict,
    strategy_name: str = "task3_large_liq",
) -> list[dict]:
    if trades.is_empty() or bbo.is_empty():
        return []

    weight, pnl_by_horizon, _, _ = add_markout_arrays(trades, bbo)
    flags_by_horizon = predict_fn(trades, bbo, liq_binance, liq_bybit)

    rows = []
    for horizon, flags in flags_by_horizon.items():
        flags = np.asarray(flags).astype(bool)
        if len(flags) != len(trades):
            raise ValueError(f"predict returned {len(flags)} flags for {len(trades)} trades at horizon {horizon}")
        if horizon not in pnl_by_horizon:
            raise ValueError(f"predict returned unsupported horizon {horizon}; expected one of {tuple(pnl_by_horizon)}")

        pnl = pnl_by_horizon[horizon]
        valid = np.isfinite(pnl) & np.isfinite(weight) & (weight > 0)
        kept = valid & ~flags
        filtered = valid & flags

        pnl_all = weighted_mean(pnl, weight, valid)
        pnl_kept = weighted_mean(pnl, weight, kept)
        pnl_filtered = weighted_mean(pnl, weight, filtered)
        kept_turnover = float(np.sum(weight[kept]))
        all_turnover = float(np.sum(weight[valid]))

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
                "all_clipped_turnover": all_turnover,
                "kept_clipped_turnover": kept_turnover,
                "filtered_clipped_turnover": float(np.sum(weight[filtered])),
                "kept_trade_count": int(np.sum(kept)),
                "filtered_trade_count": int(np.sum(filtered)),
            }
        )
    return rows


def assign_split(dates: pd.Series) -> np.ndarray:
    parsed = pd.to_datetime(dates)
    return np.select(
        [
            (parsed >= TRAIN_START) & (parsed < VALIDATION_START),
            (parsed >= VALIDATION_START) & (parsed < VALIDATION_END),
        ],
        ["train", "validation"],
        default="public_extra",
    )


def summarize_daily(rows: list[dict], split_by_date: bool = True) -> pd.DataFrame:
    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily

    if split_by_date:
        daily["split"] = assign_split(daily["date"])
        group_cols = ["strategy", "split", "horizon_s"]
    else:
        group_cols = ["strategy", "horizon_s"]

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

    result = out[
        [
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
    ].sort_values(group_cols)

    if split_by_date:
        order = {"train": 0, "validation": 1, "public_extra": 2}
        result = result.assign(_split_order=result["split"].map(order)).sort_values(["strategy", "_split_order", "horizon_s"]).drop(columns="_split_order")

    return result


def make_param_predict_fn(
    threshold: float,
    window_seconds: int,
    match_mode: str = "taker_same_liquidation",
) -> PredictFn:
    try:
        from task3_solution import classify_trades_after_large_liquidations
    except ModuleNotFoundError:
        from .task3_solution import classify_trades_after_large_liquidations

    def _predict(trades: pl.DataFrame, bbo: pl.DataFrame, liq_binance: pl.DataFrame, liq_bybit: pl.DataFrame) -> dict[int, np.ndarray]:
        del bbo
        flags = classify_trades_after_large_liquidations(
            trades,
            liq_binance,
            liq_bybit,
            threshold=threshold,
            window_seconds=window_seconds,
            match_mode=match_mode,
        )
        return {horizon: flags.copy() for horizon in HORIZONS}

    return _predict


def run_evaluation(
    data_root: Path,
    output_dir: Path,
    start: str,
    end: str,
    symbols: tuple[str, ...] = SYMBOLS,
    predict_fn: PredictFn = predict,
    strategy_name: str = "task3_large_liq",
    liq_lookback_us: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    paths = DataPaths.from_root(data_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    start_date = parse_date(start)
    end_date = parse_date(end)
    max_horizon_us = max(HORIZONS) * 1_000_000
    if liq_lookback_us is None:
        liq_lookback_us = max(REACTION_WINDOW_SECONDS * 1_000_000, 300 * 1_000_000)
    rows: list[dict] = []

    for current in iter_dates(start_date, end_date):
        date_str = current.isoformat()
        start_us = date_to_us(current)
        end_us = date_to_us(current + timedelta(days=1))
        for symbol in symbols:
            print(f"[evaluate] {date_str} {symbol} {strategy_name}", flush=True)
            trades = load_trades(paths, symbol, start_us, end_us)
            if trades.is_empty():
                continue
            bbo = load_bbo(paths, symbol, start_us - max_horizon_us - 1_000_000, end_us + max_horizon_us + 1_000_000)
            liq_binance = load_liq(paths.liq_binance(symbol), start_us - liq_lookback_us, end_us)
            liq_bybit = load_liq(paths.liq_bybit(symbol), start_us - liq_lookback_us - BYBIT_DELAY_US, end_us)
            rows.extend(score_one_day(date_str, symbol, trades, bbo, liq_binance, liq_bybit, predict_fn=predict_fn, strategy_name=strategy_name))

    daily = pd.DataFrame(rows)
    summary_by_split = summarize_daily(rows, split_by_date=True)
    summary_overall = summarize_daily(rows, split_by_date=False)
    daily.to_csv(output_dir / f"{strategy_name}_daily_metrics.csv", index=False)
    summary_by_split.to_csv(output_dir / f"{strategy_name}_summary_by_split.csv", index=False)
    summary_overall.to_csv(output_dir / f"{strategy_name}_summary_overall.csv", index=False)
    (output_dir / f"{strategy_name}_run_config.json").write_text(
        json.dumps(
            {
                "data_root": str(paths.data),
                "start": start,
                "end": end,
                "symbols": symbols,
                "large_liq_threshold": LARGE_LIQ_THRESHOLD,
                "reaction_window_seconds": REACTION_WINDOW_SECONDS,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return daily, summary_by_split, summary_overall


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--start", default="2025-12-01")
    parser.add_argument("--end", default="2026-03-01")
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS), choices=list(SYMBOLS))
    parser.add_argument("--threshold", type=float, default=LARGE_LIQ_THRESHOLD)
    parser.add_argument("--window-seconds", type=int, default=REACTION_WINDOW_SECONDS)
    parser.add_argument(
        "--match-mode",
        default="taker_opposite_liquidation",
        choices=["taker_same_liquidation", "taker_opposite_liquidation"],
    )
    args = parser.parse_args()

    mode_label = "maker" if args.match_mode == "taker_opposite_liquidation" else "same"
    strategy_name = f"task3_{mode_label}_thr{int(args.threshold)}_win{args.window_seconds}"
    run_evaluation(
        data_root=Path(args.data_root).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        start=args.start,
        end=args.end,
        symbols=tuple(args.symbols),
        predict_fn=make_param_predict_fn(args.threshold, args.window_seconds, args.match_mode),
        strategy_name=strategy_name,
        liq_lookback_us=args.window_seconds * 1_000_000,
    )


if __name__ == "__main__":
    main()
