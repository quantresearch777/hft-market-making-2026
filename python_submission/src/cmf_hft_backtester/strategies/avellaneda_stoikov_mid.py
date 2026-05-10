from __future__ import annotations

import math

from ..order_book import OrderBook
from ..orders import OrderManager
from ..portfolio import Portfolio
from ..rounding import clamp
from .base import BaseStrategy, Quote


class AvellanedaStoikovStrategy(BaseStrategy):
    name = "avellaneda_stoikov_mid"

    def on_quote(self, ts_ns: int, book: OrderBook, portfolio: Portfolio, orders: OrderManager) -> Quote:
        mid = book.mid_price()
        self.state.update_mid(mid)
        fair = self._fair_price(book)
        if fair is None:
            return Quote(None, None)

        gamma = max(1e-12, float(self.config.get("gamma", 0.05)))
        k = max(1e-12, float(self.config.get("k", 200_000.0)))
        tau = max(0.0, float(self.config.get("tau_seconds", 60.0)))
        min_half_spread_ticks = float(self.config.get("min_half_spread_ticks", 1))
        max_half_spread_ticks = float(self.config.get("max_half_spread_ticks", 30))
        sigma = self.state.sigma(fallback=self.tick_size)

        reservation = fair - portfolio.position * gamma * sigma * sigma * tau
        optimal_spread = gamma * sigma * sigma * tau + (2.0 / gamma) * math.log(1.0 + gamma / k)
        half_spread = optimal_spread / 2.0
        half_spread = clamp(
            half_spread,
            min_half_spread_ticks * self.tick_size,
            max_half_spread_ticks * self.tick_size,
        )
        bid = reservation - half_spread
        ask = reservation + half_spread
        quote = self._bound_passive_quote(bid, ask, book)
        return self._replace_quotes(ts_ns, quote, book, portfolio, orders)

    def _fair_price(self, book: OrderBook) -> float | None:
        return book.mid_price()
