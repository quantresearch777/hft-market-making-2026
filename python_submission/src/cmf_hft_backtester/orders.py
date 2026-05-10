from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"


@dataclass
class LimitOrder:
    order_id: int
    side: Side
    price: float
    qty: float
    remaining_qty: float
    ts_created_ns: int
    ts_active_ns: int
    status: OrderStatus
    strategy_name: str

    def is_live_at(self, ts_ns: int) -> bool:
        return self.status in {OrderStatus.ACTIVE, OrderStatus.PENDING} and ts_ns >= self.ts_active_ns


@dataclass(frozen=True)
class Fill:
    order_id: int
    ts_ns: int
    side: Side
    price: float
    qty: float
    maker: bool = True


class OrderManager:
    def __init__(self) -> None:
        self._next_order_id = 1
        self.orders: dict[int, LimitOrder] = {}
        self._live_order_ids: set[int] = set()

    def submit_limit_order(
        self,
        side: Side,
        price: float,
        qty: float,
        ts_ns: int,
        strategy_name: str,
        order_latency_ns: int = 0,
    ) -> LimitOrder:
        status = OrderStatus.PENDING if order_latency_ns > 0 else OrderStatus.ACTIVE
        order = LimitOrder(
            order_id=self._next_order_id,
            side=side,
            price=price,
            qty=qty,
            remaining_qty=qty,
            ts_created_ns=ts_ns,
            ts_active_ns=ts_ns + order_latency_ns,
            status=status,
            strategy_name=strategy_name,
        )
        self.orders[order.order_id] = order
        self._live_order_ids.add(order.order_id)
        self._next_order_id += 1
        return order

    def activate_due_orders(self, ts_ns: int) -> None:
        for order_id in list(self._live_order_ids):
            order = self.orders[order_id]
            if order.status == OrderStatus.PENDING and ts_ns >= order.ts_active_ns:
                order.status = OrderStatus.ACTIVE

    def cancel_order(self, order_id: int) -> None:
        order = self.orders.get(order_id)
        if order and order.status in {OrderStatus.PENDING, OrderStatus.ACTIVE, OrderStatus.PARTIALLY_FILLED}:
            order.status = OrderStatus.CANCELLED
            self._live_order_ids.discard(order_id)

    def cancel_all(self) -> None:
        for order_id in list(self._live_order_ids):
            order = self.orders[order_id]
            if order.status in {OrderStatus.PENDING, OrderStatus.ACTIVE, OrderStatus.PARTIALLY_FILLED}:
                order.status = OrderStatus.CANCELLED
            self._live_order_ids.discard(order_id)

    def active_orders(self, ts_ns: int) -> list[LimitOrder]:
        self.activate_due_orders(ts_ns)
        active: list[LimitOrder] = []
        for order_id in self._live_order_ids:
            order = self.orders[order_id]
            if order.status in {OrderStatus.ACTIVE, OrderStatus.PARTIALLY_FILLED}:
                active.append(order)
        return active

    def live_orders(self, ts_ns: int) -> list[LimitOrder]:
        self.activate_due_orders(ts_ns)
        live: list[LimitOrder] = []
        for order_id in self._live_order_ids:
            order = self.orders[order_id]
            if order.status in {OrderStatus.PENDING, OrderStatus.ACTIVE, OrderStatus.PARTIALLY_FILLED}:
                live.append(order)
        return live

    def on_fill(self, fill: Fill) -> None:
        order = self.orders[fill.order_id]
        order.remaining_qty = max(0.0, order.remaining_qty - fill.qty)
        if order.remaining_qty <= 1e-12:
            order.status = OrderStatus.FILLED
            self._live_order_ids.discard(order.order_id)
        else:
            order.status = OrderStatus.PARTIALLY_FILLED

    def active_quote_prices(self, ts_ns: int) -> tuple[float | None, float | None]:
        bid = None
        ask = None
        for order in self.active_orders(ts_ns):
            if order.side == Side.BUY:
                bid = order.price if bid is None else max(bid, order.price)
            else:
                ask = order.price if ask is None else min(ask, order.price)
        return bid, ask
