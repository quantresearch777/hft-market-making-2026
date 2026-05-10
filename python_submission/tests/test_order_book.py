import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cmf_hft_backtester.order_book import OrderBook


class TestOrderBook(unittest.TestCase):
    def test_top_of_book_metrics(self):
        book = OrderBook.from_levels(
            bids=[(99.0, 10.0), (98.0, 5.0)],
            asks=[(101.0, 30.0), (102.0, 5.0)],
        )
        self.assertEqual(book.best_bid(), 99.0)
        self.assertEqual(book.best_ask(), 101.0)
        self.assertEqual(book.mid_price(), 100.0)
        self.assertEqual(book.spread(), 2.0)
        self.assertAlmostEqual(book.microprice(), (101.0 * 10.0 + 99.0 * 30.0) / 40.0)
        self.assertAlmostEqual(book.imbalance(), (10.0 - 30.0) / 40.0)


if __name__ == "__main__":
    unittest.main()

