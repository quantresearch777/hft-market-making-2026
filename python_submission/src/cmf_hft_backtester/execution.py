from __future__ import annotations

from .events import MarketEvent
from .order_book import OrderBook
from .orders import Fill, LimitOrder, OrderManager, Side


class ExecutionModel:
    def __init__(self, partial_fills: bool = True, use_trade_events: bool = True) -> None:
        self.partial_fills = partial_fills
        self.use_trade_events = use_trade_events

    def match(
        self,
        event: MarketEvent,
        book: OrderBook,
        order_manager: OrderManager,
    ) -> list[Fill]:
        if event.is_trade and self.use_trade_events:
            return self._match_trade(event, order_manager)
        if event.is_book and not self.use_trade_events:
            return self._match_book_cross(event, book, order_manager)
        return []

    def _match_trade(self, event: MarketEvent, order_manager: OrderManager) -> list[Fill]:
        if event.price is None or event.side is None:
            return []

        remaining_trade_qty = event.qty if event.qty is not None else float("inf")
        fills: list[Fill] = []
        for order in list(order_manager.active_orders(event.ts_ns)):
            if remaining_trade_qty <= 0:
                break
            if not _trade_crosses_order(event, order):
                continue
            fill_qty = order.remaining_qty
            if self.partial_fills and remaining_trade_qty != float("inf"):
                fill_qty = min(fill_qty, remaining_trade_qty)
            if fill_qty <= 0:
                continue
            fill = Fill(
                order_id=order.order_id,
                ts_ns=event.ts_ns,
                side=order.side,
                price=order.price,
                qty=fill_qty,
            )
            fills.append(fill)
            order_manager.on_fill(fill)
            if remaining_trade_qty != float("inf"):
                remaining_trade_qty -= fill_qty
        return fills

    def _match_book_cross(
        self,
        event: MarketEvent,
        book: OrderBook,
        order_manager: OrderManager,
    ) -> list[Fill]:
        fills: list[Fill] = []
        best_ask = book.best_ask()
        best_bid = book.best_bid()
        for order in list(order_manager.active_orders(event.ts_ns)):
            crossed = False
            if order.side == Side.BUY and best_ask is not None and best_ask <= order.price:
                crossed = True
            if order.side == Side.SELL and best_bid is not None and best_bid >= order.price:
                crossed = True
            if not crossed:
                continue
            fill = Fill(
                order_id=order.order_id,
                ts_ns=event.ts_ns,
                side=order.side,
                price=order.price,
                qty=order.remaining_qty,
            )
            fills.append(fill)
            order_manager.on_fill(fill)
        return fills


def _trade_crosses_order(event: MarketEvent, order: LimitOrder) -> bool:
    side = event.side.lower()
    assert event.price is not None
    if order.side == Side.BUY:
        return side == "sell" and event.price <= order.price
    return side == "buy" and event.price >= order.price

