from __future__ import annotations

from typing import Any

import numpy as np


BYBIT_DELAY_US = 200_000
WINDOW_US = 1_000_000
THRESHOLD = 100_000.0
LONG_WINDOW_US = 2_000_000
LONG_THRESHOLD = 2_000_000.0
RETURN_WINDOW_US = 5_000_000
RETURN_THRESHOLD_BPS = 50.0
ETH_RETURN_THRESHOLD_BPS = 100.0
RETURN_GUARD_THRESHOLD_BPS = 20.0
HORIZONS = (30, 120, 300)


def _column(frame: Any, name: str) -> np.ndarray:
    col = frame[name]
    if hasattr(col, "to_numpy"):
        return col.to_numpy()
    if hasattr(col, "to_pandas"):
        return col.to_pandas().to_numpy()
    return np.asarray(col)


def _side_sign(side: np.ndarray) -> np.ndarray:
    side_str = np.asarray(side).astype(str)
    return np.where(np.char.lower(side_str) == "buy", 1.0, -1.0)


def _signed_liquidations(liq: Any, delay_us: int = 0) -> tuple[np.ndarray, np.ndarray]:
    if len(liq) == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)

    timestamp = _column(liq, "timestamp").astype(np.int64, copy=False) + delay_us
    sign = _side_sign(_column(liq, "side"))
    price = _column(liq, "price").astype(np.float64, copy=False)
    amount = _column(liq, "amount").astype(np.float64, copy=False)
    signed_notional = sign * price * amount

    finite = np.isfinite(signed_notional)
    timestamp = timestamp[finite]
    signed_notional = signed_notional[finite]

    order = np.argsort(timestamp, kind="mergesort")
    return timestamp[order], signed_notional[order]


def _rolling_sum(event_ts: np.ndarray, values: np.ndarray, query_ts: np.ndarray, window_us: int) -> np.ndarray:
    if len(event_ts) == 0:
        return np.zeros(len(query_ts), dtype=np.float64)

    cumulative = np.concatenate([[0.0], np.cumsum(values, dtype=np.float64)])
    right = np.searchsorted(event_ts, query_ts, side="right")
    left = np.searchsorted(event_ts, query_ts - window_us, side="right")
    return cumulative[right] - cumulative[left]


def _has_columns(frame: Any, names: tuple[str, ...]) -> bool:
    return all(name in frame for name in names)


def _bbo_mid_arrays(bbo: Any) -> tuple[np.ndarray, np.ndarray]:
    timestamp = _column(bbo, "timestamp").astype(np.int64, copy=False)
    if "mid" in bbo:
        mid = _column(bbo, "mid").astype(np.float64, copy=False)
    else:
        bid = _column(bbo, "bid_price").astype(np.float64, copy=False)
        ask = _column(bbo, "ask_price").astype(np.float64, copy=False)
        mid = (bid + ask) / 2.0

    finite = np.isfinite(mid)
    timestamp = timestamp[finite]
    mid = mid[finite]
    order = np.argsort(timestamp, kind="mergesort")
    return timestamp[order], mid[order]


def _side_aware_return_bps(trades: Any, bbo: Any, window_us: int) -> np.ndarray:
    trade_ts = _column(trades, "timestamp").astype(np.int64, copy=False)
    trade_sign = _side_sign(_column(trades, "side"))
    bbo_ts, mid = _bbo_mid_arrays(bbo)
    if len(bbo_ts) == 0:
        return np.full(len(trade_ts), np.nan, dtype=np.float64)

    current_idx = np.searchsorted(bbo_ts, trade_ts, side="right") - 1
    past_idx = np.searchsorted(bbo_ts, trade_ts - window_us, side="right") - 1
    out = np.full(len(trade_ts), np.nan, dtype=np.float64)
    ok = (current_idx >= 0) & (past_idx >= 0)
    positions = np.flatnonzero(ok)
    current_mid = mid[current_idx[ok]]
    past_mid = mid[past_idx[ok]]
    valid = np.isfinite(current_mid) & np.isfinite(past_mid) & (past_mid > 0)
    out[positions[valid]] = trade_sign[positions[valid]] * (
        (current_mid[valid] - past_mid[valid]) / past_mid[valid] * 10_000.0
    )
    return out


def _symbol_return_thresholds(trades: Any) -> np.ndarray:
    threshold = np.full(len(_column(trades, "timestamp")), RETURN_THRESHOLD_BPS, dtype=np.float64)
    if "ticker" not in trades:
        return threshold

    ticker = np.char.lower(_column(trades, "ticker").astype(str))
    is_eth = np.char.find(ticker, "eth") >= 0
    threshold[is_eth] = ETH_RETURN_THRESHOLD_BPS
    return threshold


def classify_trades(
    trades: Any,
    bbo: Any,
    liq_binance: Any,
    liq_bybit: Any,
    threshold: float = THRESHOLD,
) -> np.ndarray:
    """Return 0 for kept trades and 1 for filtered trades.

    Rule:
    - liquidation side is treated as directional pressure;
    - Bybit liquidations are delayed by 200 ms before use;
    - pressure is summed over the previous 1 second;
    - pressure is multiplied by the Binance trade side, where taker buy means
      maker sell and taker sell means maker buy;
    - trades are kept only when side-aware pressure is above the threshold.

    This is intentionally a simple baseline, not an overfit ML model.
    """
    del bbo

    trade_ts = _column(trades, "timestamp").astype(np.int64, copy=False)
    trade_sign = _side_sign(_column(trades, "side"))

    binance_ts, binance_signed = _signed_liquidations(liq_binance, delay_us=0)
    bybit_ts, bybit_signed = _signed_liquidations(liq_bybit, delay_us=BYBIT_DELAY_US)

    signed_pressure = _rolling_sum(binance_ts, binance_signed, trade_ts, WINDOW_US)
    signed_pressure += _rolling_sum(bybit_ts, bybit_signed, trade_ts, WINDOW_US)
    side_aware_pressure = trade_sign * signed_pressure

    return (side_aware_pressure <= threshold).astype(np.int8)


def classify_trades_liq2(
    trades: Any,
    bbo: Any,
    liq_binance: Any,
    liq_bybit: Any,
    threshold: float = LONG_THRESHOLD,
) -> np.ndarray:
    """More selective long-horizon liquidation-pressure filter.

    This uses the same side-aware pressure idea as the baseline, but with a
    2-second window and a higher threshold. It was selected for the 120s/300s
    horizons after the public-regime research pass.
    """
    del bbo

    trade_ts = _column(trades, "timestamp").astype(np.int64, copy=False)
    trade_sign = _side_sign(_column(trades, "side"))

    binance_ts, binance_signed = _signed_liquidations(liq_binance, delay_us=0)
    bybit_ts, bybit_signed = _signed_liquidations(liq_bybit, delay_us=BYBIT_DELAY_US)

    signed_pressure = _rolling_sum(binance_ts, binance_signed, trade_ts, LONG_WINDOW_US)
    signed_pressure += _rolling_sum(bybit_ts, bybit_signed, trade_ts, LONG_WINDOW_US)
    side_aware_pressure = trade_sign * signed_pressure

    return (side_aware_pressure <= threshold).astype(np.int8)


def classify_trades_return_reversal(
    trades: Any,
    bbo: Any,
    liq_binance: Any,
    liq_bybit: Any,
    threshold_bps: float = RETURN_THRESHOLD_BPS,
) -> np.ndarray:
    """Return 0 for kept trades and 1 for filtered trades.

    The rule keeps trades only after a large side-aware move over the previous
    five seconds. It is a short-term reversal filter:

    - taker buy / maker sell is kept after a strong upward move;
    - taker sell / maker buy is kept after a strong downward move.

    If BBO history is not available, fall back to the liquidation baseline.
    """
    if not _has_columns(trades, ("timestamp", "side")):
        raise KeyError("trades must contain timestamp and side")
    if not _has_columns(bbo, ("timestamp",)) or (not _has_columns(bbo, ("mid",)) and not _has_columns(bbo, ("bid_price", "ask_price"))):
        return classify_trades(trades, bbo, liq_binance, liq_bybit)

    side_aware_return = _side_aware_return_bps(trades, bbo, RETURN_WINDOW_US)
    return (side_aware_return <= threshold_bps).astype(np.int8)


def classify_trades_liq2_and_return_guard(
    trades: Any,
    bbo: Any,
    liq_binance: Any,
    liq_bybit: Any,
) -> np.ndarray:
    """120s quality filter: keep only when liq2 and 5s return agree."""
    liq_flags = classify_trades_liq2(trades, bbo, liq_binance, liq_bybit)
    if not _has_columns(bbo, ("timestamp",)) or (not _has_columns(bbo, ("mid",)) and not _has_columns(bbo, ("bid_price", "ask_price"))):
        return liq_flags

    return_guard_flags = classify_trades_return_reversal(
        trades,
        bbo,
        liq_binance,
        liq_bybit,
        threshold_bps=RETURN_GUARD_THRESHOLD_BPS,
    )
    return np.maximum(liq_flags, return_guard_flags).astype(np.int8)


def predict(trades: Any, bbo: Any, liq_binance: Any, liq_bybit: Any) -> dict[int, np.ndarray]:
    """Submission entry point expected by the task statement."""
    return_flags = classify_trades_return_reversal(
        trades,
        bbo,
        liq_binance,
        liq_bybit,
        threshold_bps=_symbol_return_thresholds(trades),
    )
    liq_flags = classify_trades_liq2(trades, bbo, liq_binance, liq_bybit)
    liq_return_guard_flags = classify_trades_liq2_and_return_guard(trades, bbo, liq_binance, liq_bybit)
    return {
        30: return_flags.copy(),
        120: liq_return_guard_flags.copy(),
        300: liq_flags.copy(),
    }
