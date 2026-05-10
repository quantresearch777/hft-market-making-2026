from __future__ import annotations

from ..order_book import OrderBook
from ..rounding import clamp
from .avellaneda_stoikov_mid import AvellanedaStoikovStrategy


class AvellanedaStoikovMicropriceStrategy(AvellanedaStoikovStrategy):
    name = "avellaneda_stoikov_microprice"

    def _fair_price(self, book: OrderBook) -> float | None:
        mid = book.mid_price()
        micro = book.microprice()
        if mid is None:
            return None
        if micro is None:
            return mid
        max_alpha_ticks = float(self.config.get("max_alpha_ticks", 5))
        alpha = clamp(micro - mid, -max_alpha_ticks * self.tick_size, max_alpha_ticks * self.tick_size)
        return mid + alpha
