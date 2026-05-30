import unittest

import numpy as np

from src.task2_solution import (
    BYBIT_DELAY_US,
    HORIZONS,
    classify_trades,
    classify_trades_liq2,
    classify_trades_liq2_and_return_guard,
    classify_trades_return_reversal,
    predict,
)


def frame(**columns):
    return {name: np.asarray(values) for name, values in columns.items()}


class Task2SolutionTest(unittest.TestCase):
    def test_binance_liquidation_pressure_is_side_aware(self):
        trades = frame(
            timestamp=[1_000_000, 1_000_000],
            side=["buy", "sell"],
            price=[100.0, 100.0],
            amount=[1.0, 1.0],
        )
        liq_binance = frame(
            timestamp=[500_000],
            side=["buy"],
            price=[100.0],
            amount=[2_000.0],
        )
        liq_bybit = frame(timestamp=[], side=[], price=[], amount=[])

        flags = classify_trades(trades, {}, liq_binance, liq_bybit)

        np.testing.assert_array_equal(flags, np.array([0, 1], dtype=np.int8))

    def test_bybit_liquidations_are_delayed(self):
        trades = frame(
            timestamp=[1_000_000, 1_200_000],
            side=["buy", "buy"],
            price=[100.0, 100.0],
            amount=[1.0, 1.0],
        )
        liq_binance = frame(timestamp=[], side=[], price=[], amount=[])
        liq_bybit = frame(
            timestamp=[1_000_000 - BYBIT_DELAY_US],
            side=["buy"],
            price=[100.0],
            amount=[2_000.0],
        )

        flags = classify_trades(trades, {}, liq_binance, liq_bybit)

        np.testing.assert_array_equal(flags, np.array([0, 0], dtype=np.int8))

    def test_bybit_event_is_not_available_before_delay(self):
        trades = frame(
            timestamp=[1_000_000],
            side=["buy"],
            price=[100.0],
            amount=[1.0],
        )
        liq_binance = frame(timestamp=[], side=[], price=[], amount=[])
        liq_bybit = frame(
            timestamp=[900_000],
            side=["buy"],
            price=[100.0],
            amount=[2_000.0],
        )

        flags = classify_trades(trades, {}, liq_binance, liq_bybit)

        np.testing.assert_array_equal(flags, np.array([1], dtype=np.int8))

    def test_predict_returns_all_horizons_with_trade_length(self):
        trades = frame(
            timestamp=[1_000_000, 2_000_000, 3_000_000],
            side=["buy", "sell", "buy"],
            price=[100.0, 100.0, 100.0],
            amount=[1.0, 1.0, 1.0],
        )
        empty_liq = frame(timestamp=[], side=[], price=[], amount=[])

        output = predict(trades, {}, empty_liq, empty_liq)

        self.assertEqual(set(output), set(HORIZONS))
        for flags in output.values():
            self.assertEqual(len(flags), 3)
            self.assertTrue(np.isin(flags, [0, 1]).all())

    def test_return_reversal_keeps_side_aware_large_move(self):
        trades = frame(
            timestamp=[6_000_000, 6_000_000],
            side=["buy", "sell"],
            price=[110.0, 110.0],
            amount=[1.0, 1.0],
        )
        bbo = frame(
            timestamp=[1_000_000, 6_000_000],
            bid_price=[99.0, 109.0],
            ask_price=[101.0, 111.0],
        )
        empty_liq = frame(timestamp=[], side=[], price=[], amount=[])

        flags = classify_trades_return_reversal(trades, bbo, empty_liq, empty_liq, threshold_bps=50.0)

        np.testing.assert_array_equal(flags, np.array([0, 1], dtype=np.int8))

    def test_predict_uses_stricter_eth_return_threshold(self):
        trades = frame(
            timestamp=[6_000_000, 6_000_000],
            ticker=["btcusdt", "ethusdt"],
            side=["buy", "buy"],
            price=[100.6, 100.6],
            amount=[1.0, 1.0],
        )
        bbo = frame(
            timestamp=[1_000_000, 6_000_000],
            bid_price=[99.0, 100.5],
            ask_price=[101.0, 100.7],
        )
        empty_liq = frame(timestamp=[], side=[], price=[], amount=[])

        output = predict(trades, bbo, empty_liq, empty_liq)

        np.testing.assert_array_equal(output[30], np.array([0, 1], dtype=np.int8))

    def test_liq2_requires_higher_two_second_pressure(self):
        trades = frame(
            timestamp=[2_000_000, 2_000_000],
            side=["buy", "sell"],
            price=[100.0, 100.0],
            amount=[1.0, 1.0],
        )
        liq_binance = frame(
            timestamp=[500_000],
            side=["buy"],
            price=[100.0],
            amount=[21_000.0],
        )
        liq_bybit = frame(timestamp=[], side=[], price=[], amount=[])

        flags = classify_trades_liq2(trades, {}, liq_binance, liq_bybit)

        np.testing.assert_array_equal(flags, np.array([0, 1], dtype=np.int8))

    def test_120s_guard_requires_liq2_and_return_signal(self):
        trades = frame(
            timestamp=[6_000_000, 8_000_000],
            side=["buy", "buy"],
            price=[101.0, 100.1],
            amount=[1.0, 1.0],
        )
        bbo = frame(
            timestamp=[1_000_000, 3_000_000, 6_000_000, 8_000_000],
            bid_price=[99.0, 99.0, 100.9, 100.0],
            ask_price=[101.0, 101.0, 101.1, 100.2],
        )
        liq_binance = frame(
            timestamp=[5_500_000, 7_000_000],
            side=["buy", "buy"],
            price=[100.0, 100.0],
            amount=[21_000.0, 21_000.0],
        )
        liq_bybit = frame(timestamp=[], side=[], price=[], amount=[])

        liq_flags = classify_trades_liq2(trades, bbo, liq_binance, liq_bybit)
        guard_flags = classify_trades_liq2_and_return_guard(trades, bbo, liq_binance, liq_bybit)

        np.testing.assert_array_equal(liq_flags, np.array([0, 0], dtype=np.int8))
        np.testing.assert_array_equal(guard_flags, np.array([0, 1], dtype=np.int8))


if __name__ == "__main__":
    unittest.main()
