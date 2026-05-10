from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from ..events import MarketEvent
from ..order_book import OrderBook
from ..orders import OrderManager, Side
from ..portfolio import Portfolio
from ..rounding import ceil_to_tick, clamp, floor_to_tick


@dataclass
class Quote:
    bid: float | None
    ask: float | None


@dataclass
class StrategyState:
    mids: deque[float] = field(default_factory=lambda: deque(maxlen=500))

    def update_mid(self, mid: float | None) -> None:
        if mid is not None and math.isfinite(mid):
            self.mids.append(mid)

    def sigma(self, fallback: float) -> float:
        if len(self.mids) < 3:
            return fallback
        diffs = [self.mids[i] - self.mids[i - 1] for i in range(1, len(self.mids))]
        mean = sum(diffs) / len(diffs)
        var = sum((x - mean) ** 2 for x in diffs) / max(1, len(diffs) - 1)
        return max(fallback, math.sqrt(var))


class BaseStrategy:
    name = "base"

    def __init__(self, config: dict, market_config: dict, risk_config: dict) -> None:
        self.config = config
        self.market_config = market_config
        self.risk_config = risk_config
        self.tick_size = float(market_config.get("tick_size", 0.01))
        self.order_qty = float(risk_config.get("order_qty", 1.0))
        self.max_inventory = float(risk_config.get("max_inventory", 10.0))
        self.order_latency_ns = int(market_config.get("order_latency_ns", 0))
        vol_window = int(config.get("vol_window", 300))
        self.state = StrategyState(mids=deque(maxlen=vol_window))

    def on_market_event(
        self,
        event: MarketEvent,
        book: OrderBook,
        portfolio: Portfolio,
        orders: OrderManager,
    ) -> None:
        return None

    def on_quote(
        self,
        ts_ns: int,
        book: OrderBook,
        portfolio: Portfolio,
        orders: OrderManager,
    ) -> Quote:
        raise NotImplementedError

    def _replace_quotes(
        self,
        ts_ns: int,
        quote: Quote,
        book: OrderBook,
        portfolio: Portfolio,
        orders: OrderManager,
    ) -> Quote:
        orders.cancel_all()
        bid = quote.bid
        ask = quote.ask

        if portfolio.position >= self.max_inventory:
            bid = None
        if portfolio.position <= -self.max_inventory:
            ask = None

        if bid is not None:
            bid_qty = min(self.order_qty, max(0.0, self.max_inventory - portfolio.position))
            if bid_qty <= 0:
                bid = None
            else:
                orders.submit_limit_order(
                    Side.BUY,
                    bid,
                    bid_qty,
                    ts_ns,
                    self.name,
                    self.order_latency_ns,
                )
        if ask is not None:
            ask_qty = min(self.order_qty, max(0.0, self.max_inventory + portfolio.position))
            if ask_qty <= 0:
                ask = None
            else:
                orders.submit_limit_order(
                    Side.SELL,
                    ask,
                    ask_qty,
                    ts_ns,
                    self.name,
                    self.order_latency_ns,
                )
        return Quote(bid=bid, ask=ask)

    def _bound_passive_quote(self, bid: float, ask: float, book: OrderBook) -> Quote:
        best_bid = book.best_bid()
        best_ask = book.best_ask()
        if best_bid is None or best_ask is None:
            return Quote(None, None)
        bid = min(bid, best_bid)
        ask = max(ask, best_ask)
        bid = floor_to_tick(bid, self.tick_size)
        ask = ceil_to_tick(ask, self.tick_size)
        if bid >= ask:
            bid = floor_to_tick(best_bid, self.tick_size)
            ask = ceil_to_tick(best_ask, self.tick_size)
        return Quote(bid=bid, ask=ask)

    def _weighted_imbalance(self, book: OrderBook, levels: int, decay: float = 1.0) -> float:
        bid_qty = 0.0
        ask_qty = 0.0
        for idx, level in enumerate(book.bids[:levels]):
            bid_qty += level.qty * (decay**idx)
        for idx, level in enumerate(book.asks[:levels]):
            ask_qty += level.qty * (decay**idx)
        denom = bid_qty + ask_qty
        if denom <= 0:
            return 0.0
        return clamp((bid_qty - ask_qty) / denom, -1.0, 1.0)

    def _alpha_fair_price(self, book: OrderBook, alpha_ticks: float) -> float | None:
        mid = book.mid_price()
        if mid is None:
            return None
        max_alpha_ticks = float(self.config.get("max_alpha_ticks", 8))
        alpha_ticks = clamp(alpha_ticks, -max_alpha_ticks, max_alpha_ticks)
        return mid + alpha_ticks * self.tick_size
