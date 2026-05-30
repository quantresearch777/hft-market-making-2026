from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from sklearn.ensemble import HistGradientBoostingRegressor

try:
    from task2_evaluate import (
        DataPaths,
        HORIZONS,
        SYMBOLS,
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


FEATURE_NAMES = [
    "side_aware_return_1s",
    "side_aware_return_5s",
    "side_aware_return_30s",
    "side_aware_liq_total_1s",
    "side_aware_liq_total_2s",
    "side_aware_bybit_liq_5s",
    "side_aware_neg_trade_flow_1s",
    "side_aware_neg_trade_flow_5s",
    "side_aware_book_imbalance",
    "spread_bps",
    "log_notional",
    "is_btc",
]
KEEP_FRACTIONS = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20)
MAX_LOOKBACK_US = 30_000_000
TURNOVER_CONSTRAINT_PER_DAY = 500_000.0


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


def split_name(day: date) -> str:
    return "train" if pd.Timestamp(day) < VALIDATION_START else "validation"


def mid_return_bps(trade_ts: np.ndarray, trade_sign: np.ndarray, bbo: pl.DataFrame, window_us: int) -> np.ndarray:
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
    out[positions[finite]] = trade_sign[positions[finite]] * (
        (current_mid[finite] - past_mid[finite]) / past_mid[finite] * 10_000.0
    )
    return out


def rolling_sum_prior(event_ts: np.ndarray, values: np.ndarray, query_ts: np.ndarray, window_us: int) -> np.ndarray:
    if len(event_ts) == 0:
        return np.zeros(len(query_ts), dtype=np.float64)
    cumulative = np.concatenate([[0.0], np.cumsum(values, dtype=np.float64)])
    right = np.searchsorted(event_ts, query_ts, side="left")
    left = np.searchsorted(event_ts, query_ts - window_us, side="right")
    return cumulative[right] - cumulative[left]


def bbo_features(trade_ts: np.ndarray, trade_sign: np.ndarray, bbo: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    bbo_ts = bbo["timestamp"].to_numpy()
    bid = bbo["bid_price"].to_numpy().astype(np.float64, copy=False)
    ask = bbo["ask_price"].to_numpy().astype(np.float64, copy=False)
    bid_size = bbo["bid_amount"].to_numpy().astype(np.float64, copy=False)
    ask_size = bbo["ask_amount"].to_numpy().astype(np.float64, copy=False)
    idx = np.searchsorted(bbo_ts, trade_ts, side="right") - 1
    spread = np.full(len(trade_ts), np.nan, dtype=np.float64)
    imbalance = np.full(len(trade_ts), np.nan, dtype=np.float64)
    ok = idx >= 0
    positions = np.flatnonzero(ok)
    selected = idx[ok]
    mid = (bid[selected] + ask[selected]) / 2.0
    denom = bid_size[selected] + ask_size[selected]
    spread[positions] = np.divide(ask[selected] - bid[selected], mid, out=np.full_like(mid, np.nan), where=mid > 0) * 10_000.0
    raw_imbalance = np.divide(bid_size[selected] - ask_size[selected], denom, out=np.full_like(denom, np.nan), where=denom > 0)
    imbalance[positions] = trade_sign[positions] * raw_imbalance
    return spread, imbalance


def build_features(
    symbol: str,
    trades: pl.DataFrame,
    bbo: pl.DataFrame,
    liq_binance: pl.DataFrame,
    liq_bybit: pl.DataFrame,
) -> tuple[np.ndarray, np.ndarray, dict[int, np.ndarray]]:
    trade_ts = trades["timestamp"].to_numpy().astype(np.int64, copy=False)
    trade_sign = side_sign(trades["side"].to_numpy())
    price = trades["price"].to_numpy().astype(np.float64, copy=False)
    amount = trades["amount"].to_numpy().astype(np.float64, copy=False)
    notional = price * amount

    binance_ts, binance_signed = _signed_liquidations(liq_binance, delay_us=0)
    bybit_ts, bybit_signed = _signed_liquidations(liq_bybit, delay_us=BYBIT_DELAY_US)
    liq_total_1s = trade_sign * (
        _rolling_sum(binance_ts, binance_signed, trade_ts, 1_000_000)
        + _rolling_sum(bybit_ts, bybit_signed, trade_ts, 1_000_000)
    )
    liq_total_2s = trade_sign * (
        _rolling_sum(binance_ts, binance_signed, trade_ts, 2_000_000)
        + _rolling_sum(bybit_ts, bybit_signed, trade_ts, 2_000_000)
    )
    bybit_liq_5s = trade_sign * _rolling_sum(bybit_ts, bybit_signed, trade_ts, 5_000_000)

    signed_trade_notional = trade_sign * notional
    neg_flow_1s = -trade_sign * rolling_sum_prior(trade_ts, signed_trade_notional, trade_ts, 1_000_000)
    neg_flow_5s = -trade_sign * rolling_sum_prior(trade_ts, signed_trade_notional, trade_ts, 5_000_000)
    spread, imbalance = bbo_features(trade_ts, trade_sign, bbo)

    x = np.column_stack(
        [
            mid_return_bps(trade_ts, trade_sign, bbo, 1_000_000),
            mid_return_bps(trade_ts, trade_sign, bbo, 5_000_000),
            mid_return_bps(trade_ts, trade_sign, bbo, 30_000_000),
            liq_total_1s,
            liq_total_2s,
            bybit_liq_5s,
            neg_flow_1s,
            neg_flow_5s,
            imbalance,
            spread,
            np.log1p(np.maximum(notional, 0.0)),
            np.full(len(trades), 1.0 if symbol == "btcusdt" else 0.0, dtype=np.float64),
        ]
    ).astype(np.float32, copy=False)

    weight, pnl_by_horizon, _ = add_markout_arrays(trades, bbo)
    return x, weight.astype(np.float32, copy=False), pnl_by_horizon


def append_split_data(container: dict, split: str, x: np.ndarray, weight: np.ndarray, pnl_by_horizon: dict[int, np.ndarray]) -> None:
    valid_base = np.isfinite(weight) & (weight > 0)
    for horizon, pnl in pnl_by_horizon.items():
        valid = valid_base & np.isfinite(pnl)
        if not np.any(valid):
            continue
        bucket = container.setdefault((split, horizon), {"x": [], "w": [], "y": []})
        bucket["x"].append(x[valid])
        bucket["w"].append(weight[valid])
        bucket["y"].append(pnl[valid].astype(np.float32, copy=False))


def concat_bucket(container: dict, split: str, horizon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    bucket = container[(split, horizon)]
    return np.vstack(bucket["x"]), np.concatenate(bucket["w"]), np.concatenate(bucket["y"])


def weighted_mean(values: np.ndarray, weight: np.ndarray, mask: np.ndarray) -> float:
    valid = mask & np.isfinite(values) & np.isfinite(weight) & (weight > 0)
    if not np.any(valid):
        return float("nan")
    w = weight[valid]
    return float(np.sum(w * values[valid]) / np.sum(w))


def evaluate_predictions(
    y: np.ndarray,
    weight: np.ndarray,
    pred: np.ndarray,
    days: int,
    split: str,
    horizon: int,
    model_name: str,
) -> list[dict]:
    rows = []
    valid = np.isfinite(y) & np.isfinite(weight) & (weight > 0) & np.isfinite(pred)
    if not np.any(valid):
        return rows
    yv = y[valid]
    wv = weight[valid]
    pv = pred[valid]
    pnl_all = weighted_mean(yv, wv, np.ones(len(yv), dtype=bool))

    order = np.argsort(pv, kind="mergesort")
    for keep_fraction in KEEP_FRACTIONS:
        keep_count = max(1, int(np.ceil(len(order) * keep_fraction)))
        keep_idx = order[-keep_count:]
        kept = np.zeros(len(order), dtype=bool)
        kept[keep_idx] = True
        pnl_kept = weighted_mean(yv, wv, kept)
        pnl_filtered = weighted_mean(yv, wv, ~kept)
        kept_turnover = float(np.sum(wv[kept]))
        rows.append(
            {
                "model": model_name,
                "split": split,
                "horizon_s": horizon,
                "keep_fraction": keep_fraction,
                "days": days,
                "pnl_all": pnl_all,
                "pnl_kept": pnl_kept,
                "pnl_filtered": pnl_filtered,
                "score": pnl_kept - pnl_all,
                "kept_turnover_per_day": kept_turnover / days,
                "constraint_ok": kept_turnover / days >= TURNOVER_CONSTRAINT_PER_DAY,
                "kept_rows": int(np.sum(kept)),
                "filtered_rows": int(np.sum(~kept)),
            }
        )
    return rows


def run(
    data_root: Path,
    output_dir: Path,
    start: str,
    end: str,
    symbols: tuple[str, ...],
    trade_stride: int,
    sample_every: int,
) -> None:
    paths = DataPaths.from_root(data_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    start_date = parse_date(start)
    end_date = parse_date(end)
    data: dict = {}
    split_days = {"train": set(), "validation": set()}

    for day_index, current in enumerate(iter_dates(start_date, end_date)):
        if sample_every > 1 and day_index % sample_every != 0:
            continue
        date_str = current.isoformat()
        split = split_name(current)
        split_days[split].add(date_str)
        start_us = date_to_us(current)
        end_us = date_to_us(current + timedelta(days=1))
        for symbol in symbols:
            print(f"[ml-research] build {date_str} {symbol}", flush=True)
            trades = stride_trades(load_trades(paths, symbol, start_us, end_us), trade_stride)
            if trades.is_empty():
                continue
            bbo = load_bbo(paths, symbol, start_us - MAX_LOOKBACK_US, end_us + max(HORIZONS) * 1_000_000 + 1_000_000)
            liq_binance = load_liq_with_lookback(paths.liq_binance(symbol), start_us, end_us, MAX_LOOKBACK_US)
            liq_bybit = load_liq_with_lookback(paths.liq_bybit(symbol), start_us, end_us, MAX_LOOKBACK_US)
            x, weight, pnl_by_horizon = build_features(symbol, trades, bbo, liq_binance, liq_bybit)
            append_split_data(data, split, x, weight, pnl_by_horizon)

    rows = []
    importances = []
    for horizon in HORIZONS:
        print(f"[ml-research] train horizon {horizon}", flush=True)
        x_train, w_train, y_train = concat_bucket(data, "train", horizon)
        x_val, w_val, y_val = concat_bucket(data, "validation", horizon)
        target = np.clip(y_train, -100.0, 100.0)
        model = HistGradientBoostingRegressor(
            max_iter=120,
            learning_rate=0.05,
            max_leaf_nodes=31,
            l2_regularization=1.0,
            random_state=42 + horizon,
        )
        model.fit(x_train, target, sample_weight=np.minimum(w_train, 100_000.0))
        train_pred = model.predict(x_train)
        val_pred = model.predict(x_val)
        rows.extend(evaluate_predictions(y_train, w_train, train_pred, len(split_days["train"]), "train", horizon, "hgb_regressor"))
        rows.extend(evaluate_predictions(y_val, w_val, val_pred, len(split_days["validation"]), "validation", horizon, "hgb_regressor"))

        # Permutation-style feature importance on validation, small and deterministic.
        base_corr = pd.Series(val_pred).corr(pd.Series(y_val), method="spearman")
        rng = np.random.default_rng(10_000 + horizon)
        sample_n = min(len(x_val), 100_000)
        sample_idx = rng.choice(len(x_val), size=sample_n, replace=False)
        x_sample = x_val[sample_idx].copy()
        y_sample = y_val[sample_idx]
        base_pred = model.predict(x_sample)
        base_sample_corr = pd.Series(base_pred).corr(pd.Series(y_sample), method="spearman")
        for col, name in enumerate(FEATURE_NAMES):
            shuffled = x_sample.copy()
            rng.shuffle(shuffled[:, col])
            shuffled_pred = model.predict(shuffled)
            shuffled_corr = pd.Series(shuffled_pred).corr(pd.Series(y_sample), method="spearman")
            importances.append(
                {
                    "horizon_s": horizon,
                    "feature": name,
                    "validation_spearman": base_corr,
                    "sample_spearman": base_sample_corr,
                    "importance_drop": base_sample_corr - shuffled_corr,
                }
            )

    summary = pd.DataFrame(rows)
    summary.to_csv(output_dir / "ml_summary.csv", index=False)
    pd.DataFrame(importances).sort_values(["horizon_s", "importance_drop"], ascending=[True, False]).to_csv(
        output_dir / "ml_feature_importance.csv", index=False
    )
    (output_dir / "ml_config.json").write_text(
        json.dumps(
            {
                "data_root": str(paths.data),
                "start": start,
                "end": end,
                "symbols": symbols,
                "trade_stride": trade_stride,
                "sample_every": sample_every,
                "features": FEATURE_NAMES,
                "split_days": {k: len(v) for k, v in split_days.items()},
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    best = summary[summary["constraint_ok"]].sort_values(["split", "horizon_s", "score"], ascending=[True, True, False])
    print(best.groupby(["split", "horizon_s"]).head(5).to_string(index=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-dir", default="outputs_ml_research")
    parser.add_argument("--start", default="2025-12-01")
    parser.add_argument("--end", default="2026-03-01")
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS), choices=list(SYMBOLS))
    parser.add_argument("--trade-stride", type=int, default=2000)
    parser.add_argument("--sample-every", type=int, default=1)
    args = parser.parse_args()

    run(
        data_root=Path(args.data_root).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        start=args.start,
        end=args.end,
        symbols=tuple(args.symbols),
        trade_stride=max(1, args.trade_stride),
        sample_every=max(1, args.sample_every),
    )


if __name__ == "__main__":
    main()
