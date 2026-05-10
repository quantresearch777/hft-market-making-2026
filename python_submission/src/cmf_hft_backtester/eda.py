from __future__ import annotations

import csv
import json
from pathlib import Path


def run_eda(data_dir: Path, output_dir: Path, lob_sample_rows: int, trade_sample_rows: int) -> dict:
    lob_path = data_dir / "lob.csv"
    trades_path = data_dir / "trades.csv"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "lob": _analyze_lob(lob_path, lob_sample_rows),
        "trades": _analyze_trades(trades_path, trade_sample_rows),
    }

    (output_dir / "eda_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "EDA_REPORT.md").write_text(_format_report(summary), encoding="utf-8")
    return summary


def _analyze_lob(path: Path, max_rows: int) -> dict:
    mids: list[float] = []
    spreads: list[float] = []
    imbalances: list[float] = []
    missing_cells = 0
    nonpositive_prices = 0
    negative_quantities = 0
    crossed_book_rows = 0
    locked_book_rows = 0
    duplicate_timestamps = 0
    nonmonotonic_timestamps = 0
    last_ts: int | None = None
    seen_ts: set[int] = set()
    rows = 0

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if rows >= max_rows:
                break
            rows += 1
            missing_cells += sum(1 for value in row.values() if value == "")
            ts = _to_int(row.get("local_timestamp"))
            if ts is not None:
                if ts in seen_ts:
                    duplicate_timestamps += 1
                if last_ts is not None and ts < last_ts:
                    nonmonotonic_timestamps += 1
                seen_ts.add(ts)
                last_ts = ts

            bid = _to_float(row.get("bids[0].price"))
            ask = _to_float(row.get("asks[0].price"))
            bid_qty = _to_float(row.get("bids[0].amount"))
            ask_qty = _to_float(row.get("asks[0].amount"))
            for value in (bid, ask):
                if value is not None and value <= 0:
                    nonpositive_prices += 1
            for value in (bid_qty, ask_qty):
                if value is not None and value < 0:
                    negative_quantities += 1
            if bid is None or ask is None:
                continue
            if bid > ask:
                crossed_book_rows += 1
            if bid == ask:
                locked_book_rows += 1
            mids.append((bid + ask) / 2.0)
            spreads.append(ask - bid)
            if bid_qty is not None and ask_qty is not None and bid_qty + ask_qty > 0:
                imbalances.append((bid_qty - ask_qty) / (bid_qty + ask_qty))

    return {
        "path": "lob.csv",
        "sample_rows": rows,
        "missing_cells": missing_cells,
        "nonpositive_prices": nonpositive_prices,
        "negative_quantities": negative_quantities,
        "crossed_book_rows": crossed_book_rows,
        "locked_book_rows": locked_book_rows,
        "duplicate_timestamps": duplicate_timestamps,
        "nonmonotonic_timestamps": nonmonotonic_timestamps,
        "mid": _stats(mids),
        "spread": _stats(spreads),
        "top_level_imbalance": _stats(imbalances),
    }


def _analyze_trades(path: Path, max_rows: int) -> dict:
    prices: list[float] = []
    amounts: list[float] = []
    notionals: list[float] = []
    side_counts: dict[str, int] = {}
    missing_rows = 0
    nonpositive_prices = 0
    nonpositive_quantities = 0
    duplicate_timestamps = 0
    nonmonotonic_timestamps = 0
    last_ts: int | None = None
    seen_ts: set[int] = set()
    rows = 0

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if rows >= max_rows:
                break
            rows += 1
            if any(value == "" for value in row.values()):
                missing_rows += 1
            ts = _to_int(row.get("local_timestamp"))
            if ts is not None:
                if ts in seen_ts:
                    duplicate_timestamps += 1
                if last_ts is not None and ts < last_ts:
                    nonmonotonic_timestamps += 1
                seen_ts.add(ts)
                last_ts = ts

            side = (row.get("side") or "unknown").lower()
            side_counts[side] = side_counts.get(side, 0) + 1
            price = _to_float(row.get("price"))
            amount = _to_float(row.get("amount"))
            if price is not None:
                prices.append(price)
                if price <= 0:
                    nonpositive_prices += 1
            if amount is not None:
                amounts.append(amount)
                if amount <= 0:
                    nonpositive_quantities += 1
            if price is not None and amount is not None:
                notionals.append(price * amount)

    return {
        "path": "trades.csv",
        "sample_rows": rows,
        "side_counts": side_counts,
        "missing_rows": missing_rows,
        "nonpositive_prices": nonpositive_prices,
        "nonpositive_quantities": nonpositive_quantities,
        "duplicate_timestamps": duplicate_timestamps,
        "nonmonotonic_timestamps": nonmonotonic_timestamps,
        "price": _stats(prices),
        "amount": _stats(amounts),
        "notional": _stats(notionals),
    }


def _stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    values_sorted = sorted(values)
    count = len(values_sorted)
    mean = sum(values_sorted) / count
    var = sum((x - mean) ** 2 for x in values_sorted) / max(1, count - 1)
    return {
        "count": count,
        "min": values_sorted[0],
        "max": values_sorted[-1],
        "mean": mean,
        "std": var**0.5,
        "p50": _percentile(values_sorted, 0.50),
        "p95": _percentile(values_sorted, 0.95),
        "p99": _percentile(values_sorted, 0.99),
    }


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * p))))
    return values[idx]


def _to_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _to_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def _format_report(summary: dict) -> str:
    lob = summary["lob"]
    trades = summary["trades"]
    return "\n".join(
        [
            "# EDA Report",
            "",
            "## LOB",
            "",
            f"- Sample rows: `{lob['sample_rows']}`",
            f"- Missing cells: `{lob['missing_cells']}`",
            f"- Crossed book rows: `{lob['crossed_book_rows']}`",
            f"- Locked book rows: `{lob['locked_book_rows']}`",
            f"- Nonmonotonic timestamps: `{lob['nonmonotonic_timestamps']}`",
            f"- Duplicate timestamps: `{lob['duplicate_timestamps']}`",
            f"- Mid mean: `{lob['mid'].get('mean')}`",
            f"- Spread mean: `{lob['spread'].get('mean')}`",
            "",
            "## Trades",
            "",
            f"- Sample rows: `{trades['sample_rows']}`",
            f"- Side counts: `{trades['side_counts']}`",
            f"- Missing rows: `{trades['missing_rows']}`",
            f"- Nonpositive prices: `{trades['nonpositive_prices']}`",
            f"- Nonpositive quantities: `{trades['nonpositive_quantities']}`",
            f"- Nonmonotonic timestamps: `{trades['nonmonotonic_timestamps']}`",
            f"- Duplicate timestamps: `{trades['duplicate_timestamps']}`",
            f"- Trade notional mean: `{trades['notional'].get('mean')}`",
            "",
            "## Notes",
            "",
            "- Preserve file order for duplicate trade timestamps.",
            "- Use the same cleaned data path across strategy comparisons.",
            "- Keep queue position and latency assumptions explicit in the backtest report.",
            "",
        ]
    )

