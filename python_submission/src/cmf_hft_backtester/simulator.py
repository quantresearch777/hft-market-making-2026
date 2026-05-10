from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from .data_loader import iter_market_events
from .execution import ExecutionModel
from .order_book import OrderBook
from .orders import Fill, OrderManager
from .portfolio import Portfolio
from .strategies import BaseStrategy, build_strategy


@dataclass
class BacktestResult:
    records: list[dict]
    fills: list[Fill]
    metrics: dict


class Simulator:
    def __init__(self, config: dict, project_root: Path) -> None:
        self.config = config
        self.project_root = project_root
        self.market_config = config.get("market", {})
        self.sim_config = config.get("simulation", {})
        self.data_config = config.get("data", {})
        self.risk_config = config.get("risk", {})
        self.strategy_config = config.get("strategy", {})

        self.book = OrderBook()
        self.orders = OrderManager()
        self.portfolio = Portfolio(
            cash=float(self.sim_config.get("initial_cash", 0.0)),
            maker_fee_bps=float(self.market_config.get("maker_fee_bps", 0.0)),
        )
        self.execution = ExecutionModel(
            partial_fills=bool(self.sim_config.get("partial_fills", True)),
            use_trade_events=bool(self.sim_config.get("use_trade_events", True)),
        )
        self.strategy: BaseStrategy = build_strategy(
            self.strategy_config,
            {
                **self.market_config,
                "order_latency_ns": int(self.sim_config.get("order_latency_ns", 0)),
            },
            self.risk_config,
        )

    def run(self) -> BacktestResult:
        quote_interval_ns = int(self.sim_config.get("quote_interval_ns", 100_000_000))
        record_interval_ns = int(self.sim_config.get("record_interval_ns", quote_interval_ns))
        max_events = self.data_config.get("max_events")

        next_quote_ts: int | None = None
        next_record_ts: int | None = None
        records: list[dict] = []
        fills: list[Fill] = []
        processed_events = 0
        start = perf_counter()

        data_config = dict(self.data_config)
        if max_events is not None:
            data_config["max_events"] = int(max_events)

        for event in iter_market_events(data_config, self.project_root):
            processed_events += 1
            if event.is_book:
                self.book.apply_event(event)

            self.orders.activate_due_orders(event.ts_ns)
            new_fills = self.execution.match(event, self.book, self.orders)
            for fill in new_fills:
                self.portfolio.on_fill(fill)
            fills.extend(new_fills)
            self.strategy.on_market_event(event, self.book, self.portfolio, self.orders)

            if self.book.ready():
                if next_quote_ts is None:
                    next_quote_ts = event.ts_ns
                if next_record_ts is None:
                    next_record_ts = event.ts_ns

                if event.ts_ns >= next_quote_ts:
                    self.strategy.on_quote(event.ts_ns, self.book, self.portfolio, self.orders)
                    while next_quote_ts <= event.ts_ns:
                        next_quote_ts += quote_interval_ns

                if event.ts_ns >= next_record_ts:
                    records.append(self._record_state(event.ts_ns, processed_events, len(fills)))
                    while next_record_ts <= event.ts_ns:
                        next_record_ts += record_interval_ns

        runtime = perf_counter() - start
        if self.book.ready():
            last_ts = self.book.last_ts_ns or (records[-1]["ts_ns"] if records else 0)
            records.append(self._record_state(last_ts, processed_events, len(fills)))

        from .metrics import compute_metrics

        metrics = compute_metrics(records, fills)
        metrics.update(
            {
                "processed_events": processed_events,
                "runtime_seconds": runtime,
                "strategy": self.strategy.name,
            }
        )
        return BacktestResult(records=records, fills=fills, metrics=metrics)

    def _record_state(self, ts_ns: int, processed_events: int, fills_count: int) -> dict:
        mid = self.book.mid_price()
        bid_quote, ask_quote = self.orders.active_quote_prices(ts_ns)
        snapshot = self.portfolio.snapshot(ts_ns, mid)
        snapshot.update(
            {
                "processed_events": processed_events,
                "best_bid": self.book.best_bid(),
                "best_ask": self.book.best_ask(),
                "mid": mid,
                "microprice": self.book.microprice(),
                "spread": self.book.spread(),
                "imbalance": self.book.imbalance(levels=1),
                "active_bid": bid_quote,
                "active_ask": ask_quote,
                "fills_count": fills_count,
            }
        )
        return snapshot
