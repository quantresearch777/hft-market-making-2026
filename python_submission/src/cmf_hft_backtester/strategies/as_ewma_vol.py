from __future__ import annotations

import math

from ..order_book import OrderBook
from ..orders import OrderManager
from ..portfolio import Portfolio
from ..rounding import clamp
from .avellaneda_stoikov_mid import AvellanedaStoikovStrategy
from .base import Quote


class AvellanedaStoikovEWMAVolatilityStrategy(AvellanedaStoikovStrategy):
    name = "as_ewma_vol"

    def on_quote(self, ts_ns: int, book: OrderBook, portfolio: Portfolio, orders: OrderManager) -> Quote:
        mid = book.mid_price()
        self.state.update_mid(mid)
        fair = self._fair_price(book)
        if fair is None:
            return Quote(None, None)

        base_gamma = max(1e-12, float(self.config.get("gamma", 0.05)))
        k = max(1e-12, float(self.config.get("k", 200_000.0)))
        tau = max(0.0, float(self.config.get("tau_seconds", 60.0)))
        reference_sigma_ticks = max(1e-12, float(self.config.get("reference_sigma_ticks", 1.0)))
        gamma_vol_multiplier = max(0.0, float(self.config.get("gamma_vol_multiplier", 0.75)))
        spread_vol_multiplier = max(0.0, float(self.config.get("spread_vol_multiplier", 0.5)))
        min_half_spread_ticks = float(self.config.get("min_half_spread_ticks", 1))
        max_half_spread_ticks = float(self.config.get("max_half_spread_ticks", 35))

        sigma = self.state.sigma(fallback=self.tick_size)
        sigma_ticks = sigma / self.tick_size
        vol_ratio = clamp(sigma_ticks / reference_sigma_ticks, 0.5, 8.0)
        gamma = base_gamma * (1.0 + gamma_vol_multiplier * max(0.0, vol_ratio - 1.0))

        reservation = fair - portfolio.position * gamma * sigma * sigma * tau
        optimal_spread = gamma * sigma * sigma * tau + (2.0 / gamma) * math.log(1.0 + gamma / k)
        half_spread = optimal_spread / 2.0
        half_spread *= 1.0 + spread_vol_multiplier * max(0.0, vol_ratio - 1.0)
        half_spread = clamp(
            half_spread,
            min_half_spread_ticks * self.tick_size,
            max_half_spread_ticks * self.tick_size,
        )
        quote = self._bound_passive_quote(reservation - half_spread, reservation + half_spread, book)
        return self._replace_quotes(ts_ns, quote, book, portfolio, orders)
