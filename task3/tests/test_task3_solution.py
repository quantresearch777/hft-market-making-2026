from __future__ import annotations

import unittest

import pandas as pd

from src.task3_solution import BYBIT_DELAY_US, classify_trades_after_large_liquidations, predict


class LargeLiquidationFilterTest(unittest.TestCase):
    def test_filters_same_direction_within_window(self) -> None:
        trades = pd.DataFrame(
            {
                "timestamp": [1_000_000, 2_000_000, 5_000_000],
                "side": ["buy", "sell", "buy"],
                "price": [100.0, 100.0, 100.0],
                "amount": [1.0, 1.0, 1.0],
            }
        )
        liq = pd.DataFrame(
            {
                "timestamp": [900_000],
                "side": ["buy"],
                "price": [100.0],
                "amount": [20.0],
            }
        )
        empty = liq.iloc[:0].copy()
        flags = classify_trades_after_large_liquidations(
            trades,
            liq,
            empty,
            threshold=1_000.0,
            window_seconds=2,
            match_mode="taker_same_liquidation",
        )
        self.assertEqual(flags.tolist(), [1, 0, 0])

    def test_filters_opposite_taker_side_for_maker_direction(self) -> None:
        trades = pd.DataFrame(
            {
                "timestamp": [1_000_000, 2_000_000],
                "side": ["buy", "sell"],
                "price": [100.0, 100.0],
                "amount": [1.0, 1.0],
            }
        )
        liq = pd.DataFrame({"timestamp": [900_000], "side": ["buy"], "price": [100.0], "amount": [20.0]})
        empty = liq.iloc[:0].copy()
        flags = classify_trades_after_large_liquidations(
            trades,
            liq,
            empty,
            threshold=1_000.0,
            window_seconds=2,
            match_mode="taker_opposite_liquidation",
        )
        self.assertEqual(flags.tolist(), [0, 1])

    def test_window_is_inclusive(self) -> None:
        trades = pd.DataFrame({"timestamp": [3_000_000], "side": ["sell"], "price": [100.0], "amount": [1.0]})
        liq = pd.DataFrame({"timestamp": [1_000_000], "side": ["sell"], "price": [100.0], "amount": [20.0]})
        empty = liq.iloc[:0].copy()
        flags = classify_trades_after_large_liquidations(
            trades,
            liq,
            empty,
            threshold=1_000.0,
            window_seconds=2,
            match_mode="taker_same_liquidation",
        )
        self.assertEqual(flags.tolist(), [1])

    def test_applies_bybit_delay(self) -> None:
        trades = pd.DataFrame(
            {
                "timestamp": [1_100_000, 1_250_000],
                "side": ["buy", "buy"],
                "price": [100.0, 100.0],
                "amount": [1.0, 1.0],
            }
        )
        empty = pd.DataFrame({"timestamp": [], "side": [], "price": [], "amount": []})
        bybit = pd.DataFrame({"timestamp": [1_000_000], "side": ["buy"], "price": [100.0], "amount": [20.0]})
        flags = classify_trades_after_large_liquidations(
            trades,
            empty,
            bybit,
            threshold=1_000.0,
            window_seconds=1,
            match_mode="taker_same_liquidation",
        )
        self.assertEqual(flags.tolist(), [0, 1])
        self.assertEqual(BYBIT_DELAY_US, 200_000)

    def test_predict_returns_all_horizons(self) -> None:
        trades = pd.DataFrame({"timestamp": [1], "side": ["buy"], "price": [100.0], "amount": [1.0]})
        empty = pd.DataFrame({"timestamp": [], "side": [], "price": [], "amount": []})
        out = predict(trades, empty, empty, empty)
        self.assertEqual(set(out), {30, 120, 300})
        self.assertTrue(all(len(flags) == 1 for flags in out.values()))

    def test_predict_can_be_horizon_specific(self) -> None:
        trades = pd.DataFrame(
            {
                "timestamp": [50_000_000],
                "side": ["sell"],
                "price": [100.0],
                "amount": [1.0],
            }
        )
        liq = pd.DataFrame({"timestamp": [1_000_000], "side": ["buy"], "price": [100.0], "amount": [2_000.0]})
        empty = liq.iloc[:0].copy()
        out = predict(trades, empty, liq, empty)
        self.assertEqual(out[30].tolist(), [1])
        self.assertEqual(out[120].tolist(), [0])
        self.assertEqual(out[300].tolist(), [0])


if __name__ == "__main__":
    unittest.main()
