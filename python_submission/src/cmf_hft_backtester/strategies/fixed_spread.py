from __future__ import annotations

from ..order_book import OrderBook
from ..orders import OrderManager
from ..portfolio import Portfolio
from .base import BaseStrategy, Quote


class FixedSpreadMarketMaker(BaseStrategy):
    name = "fixed_spread"

    def on_quote(self, ts_ns: int, book: OrderBook, portfolio: Portfolio, orders: OrderManager) -> Quote:
        mid = book.mid_price()
        self.state.update_mid(mid)
        if mid is None:
            return Quote(None, None)
        half_spread_ticks = float(self.config.get("half_spread_ticks", 2))
        skew_ticks_per_unit = float(self.config.get("inventory_skew_ticks_per_unit", 0.0))
        reservation = mid - portfolio.position * skew_ticks_per_unit * self.tick_size
        half_spread = max(self.tick_size, half_spread_ticks * self.tick_size)
        quote = self._bound_passive_quote(reservation - half_spread, reservation + half_spread, book)
        return self._replace_quotes(ts_ns, quote, book, portfolio, orders)
