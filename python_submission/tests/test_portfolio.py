import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cmf_hft_backtester.orders import Fill, Side
from cmf_hft_backtester.portfolio import Portfolio


class TestPortfolio(unittest.TestCase):
    def test_buy_and_sell_update_cash_inventory_turnover(self):
        p = Portfolio(maker_fee_bps=0.0)
        p.on_fill(Fill(order_id=1, ts_ns=1, side=Side.BUY, price=100.0, qty=2.0))
        self.assertEqual(p.cash, -200.0)
        self.assertEqual(p.position, 2.0)
        p.on_fill(Fill(order_id=2, ts_ns=2, side=Side.SELL, price=101.0, qty=1.0))
        self.assertEqual(p.cash, -99.0)
        self.assertEqual(p.position, 1.0)
        self.assertEqual(p.turnover, 301.0)
        self.assertEqual(p.equity(100.0), 1.0)


if __name__ == "__main__":
    unittest.main()

