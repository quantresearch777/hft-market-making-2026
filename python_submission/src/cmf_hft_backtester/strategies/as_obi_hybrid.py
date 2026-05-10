from __future__ import annotations

from ..order_book import OrderBook
from .avellaneda_stoikov_mid import AvellanedaStoikovStrategy


class AvellanedaStoikovOBIHybridStrategy(AvellanedaStoikovStrategy):
    name = "as_obi_hybrid"

    def _fair_price(self, book: OrderBook) -> float | None:
        levels = int(self.config.get("levels", 3))
        decay = float(self.config.get("level_decay", 0.75))
        alpha_ticks = float(self.config.get("alpha_ticks", 4.0)) * self._weighted_imbalance(book, levels, decay)
        return self._alpha_fair_price(book, alpha_ticks)
