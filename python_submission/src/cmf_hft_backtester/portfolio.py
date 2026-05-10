from __future__ import annotations

from dataclasses import dataclass

from .orders import Fill, Side


@dataclass
class Portfolio:
    cash: float = 0.0
    position: float = 0.0
    fees_paid: float = 0.0
    turnover: float = 0.0
    maker_fee_bps: float = 0.0

    def on_fill(self, fill: Fill) -> None:
        notional = fill.price * fill.qty
        fee = abs(notional) * self.maker_fee_bps / 10_000.0
        if fill.side == Side.BUY:
            self.cash -= notional
            self.position += fill.qty
        else:
            self.cash += notional
            self.position -= fill.qty
        self.cash -= fee
        self.fees_paid += fee
        self.turnover += abs(notional)

    def equity(self, mark_price: float | None) -> float:
        if mark_price is None:
            return self.cash
        return self.cash + self.position * mark_price

    def snapshot(self, ts_ns: int, mid_price: float | None) -> dict[str, float | int]:
        return {
            "ts_ns": ts_ns,
            "cash": self.cash,
            "position": self.position,
            "fees_paid": self.fees_paid,
            "turnover": self.turnover,
            "equity": self.equity(mid_price),
        }

