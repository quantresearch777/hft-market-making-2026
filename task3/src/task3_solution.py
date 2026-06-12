from __future__ import annotations

from typing import Any

import numpy as np


BYBIT_DELAY_US = 200_000
HORIZONS = (30, 120, 300)

# Selected after validating both taker-side and maker-side interpretations of
# "trade direction" against q90/q95/q99 liquidation-notional thresholds.
SHORT_LIQ_THRESHOLD = 196_940.36
SHORT_REACTION_WINDOW_SECONDS = 60
LONG_LIQ_THRESHOLD = 38_929.53
LONG_REACTION_WINDOW_SECONDS = 30
LARGE_LIQ_THRESHOLD = LONG_LIQ_THRESHOLD
REACTION_WINDOW_SECONDS = LONG_REACTION_WINDOW_SECONDS
MATCH_MODE = "taker_opposite_liquidation"


def _column(frame: Any, name: str) -> np.ndarray:
    col = frame[name]
    if hasattr(col, "to_numpy"):
        return col.to_numpy()
    if hasattr(col, "to_pandas"):
        return col.to_pandas().to_numpy()
    return np.asarray(col)


def _side_sign(side: np.ndarray) -> np.ndarray:
    side_str = np.asarray(side).astype(str)
    return np.where(np.char.lower(side_str) == "buy", 1, -1).astype(np.int8)


def _large_liquidation_events(
    liq: Any,
    threshold: float,
    delay_us: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    if len(liq) == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int8)

    timestamp = _column(liq, "timestamp").astype(np.int64, copy=False) + delay_us
    sign = _side_sign(_column(liq, "side"))
    price = _column(liq, "price").astype(np.float64, copy=False)
    amount = _column(liq, "amount").astype(np.float64, copy=False)
    notional = price * amount

    keep = np.isfinite(notional) & (notional >= threshold)
    timestamp = timestamp[keep]
    sign = sign[keep]

    order = np.argsort(timestamp, kind="mergesort")
    return timestamp[order], sign[order]


def _last_event_within_window(
    event_ts: np.ndarray,
    query_ts: np.ndarray,
    window_us: int,
) -> np.ndarray:
    if len(event_ts) == 0:
        return np.zeros(len(query_ts), dtype=bool)

    idx = np.searchsorted(event_ts, query_ts, side="right") - 1
    ok = idx >= 0
    out = np.zeros(len(query_ts), dtype=bool)
    positions = np.flatnonzero(ok)
    out[positions] = query_ts[positions] - event_ts[idx[ok]] <= window_us
    return out


def classify_trades_after_large_liquidations(
    trades: Any,
    liq_binance: Any,
    liq_bybit: Any,
    threshold: float = LARGE_LIQ_THRESHOLD,
    window_seconds: int = REACTION_WINDOW_SECONDS,
    match_mode: str = MATCH_MODE,
) -> np.ndarray:
    """Return 1 for trades filtered after large liquidations.

    `trades.side` is the taker side, while markout is measured for a passive
    maker fill. Therefore two interpretations are useful:

    - `taker_same_liquidation`: taker trade side equals liquidation side.
    - `taker_opposite_liquidation`: maker fill side equals liquidation side.
    """
    if len(trades) == 0:
        return np.empty(0, dtype=np.int8)
    if match_mode not in {"taker_same_liquidation", "taker_opposite_liquidation"}:
        raise ValueError(f"Unsupported match_mode: {match_mode}")

    trade_ts = _column(trades, "timestamp").astype(np.int64, copy=False)
    trade_sign = _side_sign(_column(trades, "side"))
    window_us = int(window_seconds * 1_000_000)

    binance_ts, binance_sign = _large_liquidation_events(liq_binance, threshold=threshold, delay_us=0)
    bybit_ts, bybit_sign = _large_liquidation_events(liq_bybit, threshold=threshold, delay_us=BYBIT_DELAY_US)

    flags = np.zeros(len(trades), dtype=bool)
    for sign in (-1, 1):
        event_ts = np.concatenate([binance_ts[binance_sign == sign], bybit_ts[bybit_sign == sign]])
        if len(event_ts) == 0:
            continue
        event_ts.sort(kind="mergesort")
        target_sign = sign if match_mode == "taker_same_liquidation" else -sign
        target_trades = trade_sign == target_sign
        flags[target_trades] = _last_event_within_window(event_ts, trade_ts[target_trades], window_us)

    return flags.astype(np.int8)


def predict(trades: Any, bbo: Any, liq_binance: Any, liq_bybit: Any) -> dict[int, np.ndarray]:
    """Submission entry point.

    The final rule is horizon-specific:
    - 30s uses a stricter q99 / 60s reaction filter;
    - 120s and 300s use the more robust q95 / 30s reaction filter.
    """
    del bbo
    short_flags = classify_trades_after_large_liquidations(
        trades,
        liq_binance,
        liq_bybit,
        threshold=SHORT_LIQ_THRESHOLD,
        window_seconds=SHORT_REACTION_WINDOW_SECONDS,
    )
    long_flags = classify_trades_after_large_liquidations(
        trades,
        liq_binance,
        liq_bybit,
        threshold=LONG_LIQ_THRESHOLD,
        window_seconds=LONG_REACTION_WINDOW_SECONDS,
    )
    return {30: short_flags, 120: long_flags.copy(), 300: long_flags.copy()}
