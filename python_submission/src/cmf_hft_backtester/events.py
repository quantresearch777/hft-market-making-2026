from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BookLevel:
    price: float
    qty: float


@dataclass(frozen=True)
class BookSnapshot:
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]


@dataclass(frozen=True)
class MarketEvent:
    ts_ns: int
    event_type: str
    side: str | None = None
    price: float | None = None
    qty: float | None = None
    book: BookSnapshot | None = None

    @property
    def is_book(self) -> bool:
        return self.event_type == "book"

    @property
    def is_trade(self) -> bool:
        return self.event_type == "trade"


def timestamp_to_ns(raw_ts: int | str) -> int:
    """Normalize epoch timestamps that are commonly stored as us/ms/ns."""
    ts = int(raw_ts)
    if ts < 10_000_000_000_000:
        return ts * 1_000_000
    if ts < 10_000_000_000_000_000:
        return ts * 1_000
    return ts

