from __future__ import annotations

from dataclasses import dataclass, field

from .events import BookLevel, BookSnapshot, MarketEvent


@dataclass
class OrderBook:
    bids: list[BookLevel] = field(default_factory=list)
    asks: list[BookLevel] = field(default_factory=list)
    last_ts_ns: int | None = None

    def apply_event(self, event: MarketEvent) -> None:
        if not event.is_book or event.book is None:
            return
        self.bids = sorted(event.book.bids, key=lambda level: level.price, reverse=True)
        self.asks = sorted(event.book.asks, key=lambda level: level.price)
        self.last_ts_ns = event.ts_ns

    def ready(self) -> bool:
        return self.best_bid() is not None and self.best_ask() is not None

    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    def best_bid_qty(self) -> float | None:
        return self.bids[0].qty if self.bids else None

    def best_ask_qty(self) -> float | None:
        return self.asks[0].qty if self.asks else None

    def mid_price(self) -> float | None:
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return (bid + ask) / 2.0

    def spread(self) -> float | None:
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return ask - bid

    def microprice(self) -> float | None:
        bid = self.best_bid()
        ask = self.best_ask()
        bid_qty = self.best_bid_qty()
        ask_qty = self.best_ask_qty()
        if bid is None or ask is None or bid_qty is None or ask_qty is None:
            return None
        denom = bid_qty + ask_qty
        if denom <= 0:
            return self.mid_price()
        return (ask * bid_qty + bid * ask_qty) / denom

    def imbalance(self, levels: int = 1) -> float | None:
        bid_qty = sum(level.qty for level in self.bids[:levels])
        ask_qty = sum(level.qty for level in self.asks[:levels])
        denom = bid_qty + ask_qty
        if denom <= 0:
            return None
        return (bid_qty - ask_qty) / denom

    def top_levels(self, n: int = 5) -> dict[str, list[tuple[float, float]]]:
        return {
            "bids": [(level.price, level.qty) for level in self.bids[:n]],
            "asks": [(level.price, level.qty) for level in self.asks[:n]],
        }

    @classmethod
    def from_levels(
        cls,
        bids: list[tuple[float, float]],
        asks: list[tuple[float, float]],
        ts_ns: int | None = None,
    ) -> "OrderBook":
        book = cls()
        snapshot = BookSnapshot(
            bids=tuple(BookLevel(price, qty) for price, qty in bids),
            asks=tuple(BookLevel(price, qty) for price, qty in asks),
        )
        book.apply_event(MarketEvent(ts_ns=ts_ns or 0, event_type="book", book=snapshot))
        return book

