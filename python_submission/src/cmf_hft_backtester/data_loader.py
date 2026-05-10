from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from .events import BookLevel, BookSnapshot, MarketEvent, timestamp_to_ns


def iter_market_events(config: dict, project_root: Path) -> Iterator[MarketEvent]:
    source = config.get("source", "cmf")
    if source == "cmf":
        data_dir = _resolve_path(project_root, config.get("data_dir", "data/MD"))
        yield from iter_cmf_events(
            data_dir=data_dir,
            levels=int(config.get("levels", 5)),
            max_events=config.get("max_events"),
            max_lob_rows=config.get("max_lob_rows"),
            max_trade_rows=config.get("max_trade_rows"),
            start_ts_ns=config.get("start_ts_ns"),
            end_ts_ns=config.get("end_ts_ns"),
        )
    else:
        raise ValueError(f"Unknown data source: {source}")


def iter_cmf_events(
    data_dir: Path,
    levels: int = 5,
    max_events: int | None = None,
    max_lob_rows: int | None = None,
    max_trade_rows: int | None = None,
    start_ts_ns: int | None = None,
    end_ts_ns: int | None = None,
) -> Iterator[MarketEvent]:
    lob_path = data_dir / "lob.csv"
    trades_path = data_dir / "trades.csv"
    with lob_path.open(newline="") as lob_file, trades_path.open(newline="") as trades_file:
        lob_rows = csv.DictReader(lob_file)
        trade_rows = csv.DictReader(trades_file)
        lob_iter = _iter_lob_rows(lob_rows, levels, max_lob_rows)
        trade_iter = _iter_trade_rows(trade_rows, max_trade_rows)
        next_lob = next(lob_iter, None)
        next_trade = next(trade_iter, None)
        emitted = 0

        while next_lob is not None or next_trade is not None:
            if next_trade is None or (next_lob is not None and next_lob.ts_ns <= next_trade.ts_ns):
                event = next_lob
                next_lob = next(lob_iter, None)
            else:
                event = next_trade
                next_trade = next(trade_iter, None)

            assert event is not None
            if start_ts_ns is not None and event.ts_ns < int(start_ts_ns):
                continue
            if end_ts_ns is not None and event.ts_ns > int(end_ts_ns):
                break

            yield event
            emitted += 1
            if max_events is not None and emitted >= int(max_events):
                break


def inspect_cmf_data(data_dir: Path, sample_rows: int = 100_000) -> dict:
    lob_path = data_dir / "lob.csv"
    trades_path = data_dir / "trades.csv"
    summary: dict = {
        "lob_path": str(lob_path),
        "trades_path": str(trades_path),
        "sample_rows": sample_rows,
        "trade_side_counts": {},
    }

    with lob_path.open(newline="") as f:
        reader = csv.DictReader(f)
        summary["lob_columns"] = reader.fieldnames
        first_ts = None
        last_ts = None
        rows = 0
        for row in reader:
            rows += 1
            ts = timestamp_to_ns(row["local_timestamp"])
            if first_ts is None:
                first_ts = ts
            last_ts = ts
            if rows >= sample_rows:
                break
        summary["lob_sample_rows"] = rows
        summary["lob_first_ts_ns"] = first_ts
        summary["lob_last_ts_ns"] = last_ts

    side_counts: dict[str, int] = {}
    with trades_path.open(newline="") as f:
        reader = csv.DictReader(f)
        summary["trades_columns"] = reader.fieldnames
        first_ts = None
        last_ts = None
        rows = 0
        for row in reader:
            rows += 1
            ts = timestamp_to_ns(row["local_timestamp"])
            if first_ts is None:
                first_ts = ts
            last_ts = ts
            side = row["side"].strip().lower()
            side_counts[side] = side_counts.get(side, 0) + 1
            if rows >= sample_rows:
                break
        summary["trades_sample_rows"] = rows
        summary["trades_first_ts_ns"] = first_ts
        summary["trades_last_ts_ns"] = last_ts
        summary["trade_side_counts"] = side_counts
    return summary


def _iter_lob_rows(reader: csv.DictReader, levels: int, max_rows: int | None) -> Iterator[MarketEvent]:
    for idx, row in enumerate(reader):
        if max_rows is not None and idx >= int(max_rows):
            break
        bids: list[BookLevel] = []
        asks: list[BookLevel] = []
        for level in range(levels):
            ask_px = _safe_float(row.get(f"asks[{level}].price"))
            ask_qty = _safe_float(row.get(f"asks[{level}].amount"))
            bid_px = _safe_float(row.get(f"bids[{level}].price"))
            bid_qty = _safe_float(row.get(f"bids[{level}].amount"))
            if ask_px is not None and ask_qty is not None and ask_qty > 0:
                asks.append(BookLevel(ask_px, ask_qty))
            if bid_px is not None and bid_qty is not None and bid_qty > 0:
                bids.append(BookLevel(bid_px, bid_qty))
        yield MarketEvent(
            ts_ns=timestamp_to_ns(row["local_timestamp"]),
            event_type="book",
            book=BookSnapshot(bids=tuple(bids), asks=tuple(asks)),
        )


def _iter_trade_rows(reader: csv.DictReader, max_rows: int | None) -> Iterator[MarketEvent]:
    for idx, row in enumerate(reader):
        if max_rows is not None and idx >= int(max_rows):
            break
        yield MarketEvent(
            ts_ns=timestamp_to_ns(row["local_timestamp"]),
            event_type="trade",
            side=row["side"].strip().lower(),
            price=float(row["price"]),
            qty=float(row["amount"]),
        )


def _safe_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _resolve_path(project_root: Path, path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return (project_root / path).resolve()
