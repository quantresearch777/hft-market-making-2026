import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cmf_hft_backtester.order_book import OrderBook
from cmf_hft_backtester.orders import OrderManager
from cmf_hft_backtester.portfolio import Portfolio
from cmf_hft_backtester.strategies import (
    AvellanedaStoikovEWMAVolatilityStrategy,
    AvellanedaStoikovMicropriceStrategy,
    AvellanedaStoikovOBIHybridStrategy,
    AvellanedaStoikovStrategy,
)


class TestStrategies(unittest.TestCase):
    def test_positive_inventory_lowers_reservation_quote(self):
        book = OrderBook.from_levels(bids=[(99.0, 10.0)], asks=[(101.0, 10.0)])
        cfg = {"gamma": 0.1, "k": 1000.0, "tau_seconds": 10.0, "min_half_spread_ticks": 1}
        market = {"tick_size": 0.01}
        risk = {"order_qty": 1.0, "max_inventory": 100.0}

        p_flat = Portfolio(position=0.0)
        p_long = Portfolio(position=10.0)
        strat_flat = AvellanedaStoikovStrategy(cfg, market, risk)
        strat_long = AvellanedaStoikovStrategy(cfg, market, risk)
        q_flat = strat_flat.on_quote(1, book, p_flat, OrderManager())
        q_long = strat_long.on_quote(1, book, p_long, OrderManager())
        self.assertLessEqual(q_long.bid, q_flat.bid)
        self.assertLessEqual(q_long.ask, q_flat.ask)

    def test_microprice_changes_fair_value_direction(self):
        book = OrderBook.from_levels(bids=[(99.0, 100.0)], asks=[(101.0, 10.0)])
        strat = AvellanedaStoikovMicropriceStrategy(
            {"gamma": 0.1, "k": 1000.0, "tau_seconds": 10.0, "max_alpha_ticks": 200},
            {"tick_size": 0.01},
            {"order_qty": 1.0, "max_inventory": 100.0},
        )
        self.assertGreater(strat._fair_price(book), book.mid_price())

    def test_as_obi_hybrid_moves_fair_price_toward_heavier_bid_side(self):
        book = OrderBook.from_levels(bids=[(99.0, 100.0)], asks=[(101.0, 10.0)])
        strat = AvellanedaStoikovOBIHybridStrategy(
            {"alpha_ticks": 10.0, "levels": 1, "max_alpha_ticks": 20.0},
            {"tick_size": 0.01},
            {"order_qty": 1.0, "max_inventory": 100.0},
        )
        self.assertGreater(strat._fair_price(book), book.mid_price())

    def test_ewma_vol_quotes_are_passive(self):
        book = OrderBook.from_levels(bids=[(99.0, 10.0)], asks=[(101.0, 10.0)])
        strat = AvellanedaStoikovEWMAVolatilityStrategy(
            {"gamma": 0.1, "k": 1000.0, "tau_seconds": 10.0, "min_half_spread_ticks": 1},
            {"tick_size": 0.01},
            {"order_qty": 1.0, "max_inventory": 100.0},
        )
        quote = strat.on_quote(1, book, Portfolio(), OrderManager())
        self.assertLessEqual(quote.bid, book.best_bid())
        self.assertGreaterEqual(quote.ask, book.best_ask())


if __name__ == "__main__":
    unittest.main()
