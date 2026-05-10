import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cmf_hft_backtester.events import MarketEvent
from cmf_hft_backtester.execution import ExecutionModel
from cmf_hft_backtester.order_book import OrderBook
from cmf_hft_backtester.orders import OrderManager, OrderStatus, Side


class TestExecution(unittest.TestCase):
    def test_buy_limit_fills_on_aggressive_sell_cross(self):
        orders = OrderManager()
        orders.submit_limit_order(Side.BUY, 99.0, 5.0, 10, "test")
        event = MarketEvent(ts_ns=20, event_type="trade", side="sell", price=99.0, qty=2.0)
        fills = ExecutionModel(partial_fills=True).match(event, OrderBook(), orders)
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].qty, 2.0)
        self.assertEqual(orders.orders[1].status, OrderStatus.PARTIALLY_FILLED)

    def test_sell_limit_fills_on_aggressive_buy_cross(self):
        orders = OrderManager()
        orders.submit_limit_order(Side.SELL, 101.0, 5.0, 10, "test")
        event = MarketEvent(ts_ns=20, event_type="trade", side="buy", price=101.0, qty=10.0)
        fills = ExecutionModel(partial_fills=True).match(event, OrderBook(), orders)
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].qty, 5.0)
        self.assertEqual(orders.orders[1].status, OrderStatus.FILLED)

    def test_pending_order_waits_for_latency(self):
        orders = OrderManager()
        orders.submit_limit_order(Side.BUY, 99.0, 5.0, 10, "test", order_latency_ns=100)
        event = MarketEvent(ts_ns=20, event_type="trade", side="sell", price=99.0, qty=5.0)
        fills = ExecutionModel().match(event, OrderBook(), orders)
        self.assertEqual(fills, [])


if __name__ == "__main__":
    unittest.main()

