from __future__ import annotations

import argparse
import ctypes
import gc
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import polars as pl
import pyarrow.parquet as pq


SYMBOLS = ("btcusdt", "ethusdt")
SOURCES = ("binance_trades", "binance_booktickers", "binance_liquidations", "bybit_liquidations")
BYBIT_DELAY_US = 200_000
HORIZONS_US = {"5s": 5_000_000, "30s": 30_000_000, "120s": 120_000_000, "300s": 300_000_000}
TRADE_FLOW_WINDOWS_US = {"1s": 1_000_000, "5s": 5_000_000, "30s": 30_000_000}


def release_memory() -> None:
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def collect_streaming(lf: pl.LazyFrame) -> pl.DataFrame:
    try:
        return lf.collect(engine="streaming")
    except TypeError:
        return lf.collect(streaming=True)


def utc_dt_to_us(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000)


def date_to_us(d: date) -> int:
    return utc_dt_to_us(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def iter_dates(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur < end:
        yield cur
        cur += timedelta(days=1)


def us_to_utc(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts / 1_000_000, tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class Paths:
    root: Path
    data: Path
    output: Path
    segments: Path

    @classmethod
    def from_root(cls, root: Path, output_dir: Path) -> "Paths":
        candidates = [
            root / "liquidation_task" / "data",
            root / "liquidation_task" / "liquidation_task" / "data",
        ]
        data = next((p for p in candidates if p.exists()), None)
        if data is None:
            raise FileNotFoundError(f"Cannot find data under {root}")
        output_dir.mkdir(parents=True, exist_ok=True)
        segments = output_dir / "segments"
        segments.mkdir(parents=True, exist_ok=True)
        return cls(root=root, data=data, output=output_dir, segments=segments)

    def file(self, source: str, symbol: str) -> Path:
        if source == "binance_trades":
            return self.data / "binance_trades" / f"perp_{symbol}.parquet"
        if source == "binance_booktickers":
            return self.data / "binance_booktickers" / f"perp_{symbol}.parquet"
        if source == "binance_liquidations":
            return self.data / "binance_liquidations" / f"perp_{symbol}.parquet"
        if source == "bybit_liquidations":
            return self.data / "bybit_liquidations" / f"{symbol}.parquet"
        raise ValueError(source)


def scan_file(paths: Paths, source: str, symbol: str, start_us: int | None = None, end_us: int | None = None) -> pl.LazyFrame:
    lf = pl.scan_parquet(paths.file(source, symbol))
    if start_us is not None:
        lf = lf.filter(pl.col("timestamp") >= start_us)
    if end_us is not None:
        lf = lf.filter(pl.col("timestamp") < end_us)
    return lf


def date_hour_exprs() -> list[pl.Expr]:
    dt = pl.from_epoch(pl.col("timestamp"), time_unit="us")
    return [dt.dt.date().alias("date"), dt.dt.hour().alias("hour")]


def source_out_path(paths: Paths, name: str, source: str, symbol: str) -> Path:
    return paths.segments / f"{name}__{source}__{symbol}.csv"


def write_df(path: Path, df: pl.DataFrame | pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(df, pl.DataFrame):
        df.write_csv(path)
    else:
        df.to_csv(path, index=False)


def parquet_metadata(paths: Paths) -> pl.DataFrame:
    rows = []
    for source in SOURCES:
        for symbol in SYMBOLS:
            path = paths.file(source, symbol)
            pf = pq.ParquetFile(path)
            md = pf.metadata
            ts_idx = pf.schema_arrow.get_field_index("timestamp")
            min_ts = None
            max_ts = None
            for rg_i in range(md.num_row_groups):
                stats = md.row_group(rg_i).column(ts_idx).statistics
                if stats is None:
                    continue
                min_ts = stats.min if min_ts is None else min(min_ts, stats.min)
                max_ts = stats.max if max_ts is None else max(max_ts, stats.max)
            rows.append(
                {
                    "source": source,
                    "symbol": symbol,
                    "path": str(path.relative_to(paths.root)),
                    "rows": md.num_rows,
                    "row_groups": md.num_row_groups,
                    "size_mb": path.stat().st_size / (1024**2),
                    "min_timestamp": min_ts,
                    "max_timestamp": max_ts,
                    "min_utc": us_to_utc(min_ts),
                    "max_utc": us_to_utc(max_ts),
                    "schema": ", ".join(f"{field.name}:{field.type}" for field in pf.schema_arrow),
                }
            )
    return pl.DataFrame(rows)


def source_profile(paths: Paths, source: str, symbol: str, start: date | None = None, end: date | None = None) -> None:
    print(f"[source-profile] {source} {symbol}", flush=True)
    if source == "binance_trades":
        trade_source_profile_chunked(paths, source, symbol, start or parse_date("2025-12-01"), end or parse_date("2026-03-01"))
        return
    lf = scan_file(paths, source, symbol)
    row_hash = pl.struct(pl.all()).hash(seed=42).alias("row_hash")
    gap_query = (
        lf.select([pl.all(), row_hash])
        .select(
            [
                pl.col("timestamp"),
                pl.col("row_hash"),
            ]
        )
        .with_columns(
            [
                pl.col("timestamp").diff().alias("dt_us"),
                (pl.col("row_hash") == pl.col("row_hash").shift(1)).alias("exact_adjacent_duplicate"),
            ]
        )
        .select(
            [
                pl.len().alias("rows"),
                pl.col("timestamp").min().alias("min_timestamp"),
                pl.col("timestamp").max().alias("max_timestamp"),
                (pl.col("dt_us") < 0).sum().alias("negative_time_jumps"),
                (pl.col("dt_us") == 0).sum().alias("same_timestamp_as_previous"),
                pl.col("exact_adjacent_duplicate").sum().alias("exact_adjacent_duplicates"),
                pl.col("dt_us").filter(pl.col("dt_us").is_not_null() & (pl.col("dt_us") >= 0)).quantile(0.50).alias("dt_us_p50"),
                pl.col("dt_us").filter(pl.col("dt_us").is_not_null() & (pl.col("dt_us") >= 0)).quantile(0.90).alias("dt_us_p90"),
                pl.col("dt_us").filter(pl.col("dt_us").is_not_null() & (pl.col("dt_us") >= 0)).quantile(0.99).alias("dt_us_p99"),
                pl.col("dt_us").filter(pl.col("dt_us").is_not_null() & (pl.col("dt_us") >= 0)).quantile(0.999).alias("dt_us_p999"),
                pl.col("dt_us").max().alias("dt_us_max"),
                (pl.col("dt_us") > 1_000_000).sum().alias("gaps_gt_1s"),
                (pl.col("dt_us") > 10_000_000).sum().alias("gaps_gt_10s"),
                (pl.col("dt_us") > 60_000_000).sum().alias("gaps_gt_60s"),
            ]
        )
    )
    gaps = collect_streaming(gap_query).with_columns(
        [
            pl.lit(source).alias("source"),
            pl.lit(symbol).alias("symbol"),
        ]
    )
    write_df(source_out_path(paths, "timestamp_gaps", source, symbol), gaps)
    del gap_query, gaps
    release_memory()


    if source == "binance_booktickers":
        mid = (pl.col("bid_price") + pl.col("ask_price")) / 2
        depth = pl.col("bid_amount") + pl.col("ask_amount")
        enriched = lf.with_columns(
            [
                *date_hour_exprs(),
                mid.alias("mid"),
                (pl.col("ask_price") - pl.col("bid_price")).alias("spread"),
                ((pl.col("ask_price") - pl.col("bid_price")) / mid * 10_000).alias("spread_bps"),
                ((pl.col("bid_amount") - pl.col("ask_amount")) / depth).alias("top_imbalance"),
                (pl.col("bid_price").is_null() | pl.col("ask_price").is_null() | pl.col("bid_amount").is_null() | pl.col("ask_amount").is_null()).alias("has_null"),
            ]
        )
        daily = collect_streaming(
            enriched.group_by("date")
            .agg(
                [
                    pl.len().alias("rows"),
                    pl.col("timestamp").min().alias("min_timestamp"),
                    pl.col("timestamp").max().alias("max_timestamp"),
                    (pl.col("bid_price") > pl.col("ask_price")).sum().alias("crossed_rows"),
                    (pl.col("spread") < 0).sum().alias("negative_spread_rows"),
                    (pl.col("spread") == 0).sum().alias("zero_spread_rows"),
                    (pl.col("bid_amount") <= 0).sum().alias("bad_bid_amount_rows"),
                    (pl.col("ask_amount") <= 0).sum().alias("bad_ask_amount_rows"),
                    pl.col("has_null").sum().alias("null_rows"),
                    pl.col("mid").min().alias("mid_min"),
                    pl.col("mid").max().alias("mid_max"),
                    pl.col("spread_bps").mean().alias("spread_bps_mean"),
                    pl.col("spread_bps").quantile(0.50).alias("spread_bps_p50"),
                    pl.col("spread_bps").quantile(0.90).alias("spread_bps_p90"),
                    pl.col("spread_bps").quantile(0.99).alias("spread_bps_p99"),
                    pl.col("spread_bps").quantile(0.999).alias("spread_bps_p999"),
                    pl.col("spread_bps").max().alias("spread_bps_max"),
                    pl.col("top_imbalance").mean().alias("top_imbalance_mean"),
                    pl.col("top_imbalance").quantile(0.01).alias("top_imbalance_p01"),
                    pl.col("top_imbalance").quantile(0.50).alias("top_imbalance_p50"),
                    pl.col("top_imbalance").quantile(0.99).alias("top_imbalance_p99"),
                ]
            )
            .sort("date")
        ).with_columns([pl.lit(source).alias("source"), pl.lit(symbol).alias("symbol")])
        hourly = collect_streaming(
            enriched.group_by(["date", "hour"])
            .agg(
                [
                    pl.len().alias("rows"),
                    pl.col("spread_bps").mean().alias("spread_bps_mean"),
                    pl.col("spread_bps").quantile(0.99).alias("spread_bps_p99"),
                    pl.col("top_imbalance").mean().alias("top_imbalance_mean"),
                ]
            )
            .sort(["date", "hour"])
        ).with_columns([pl.lit(source).alias("source"), pl.lit(symbol).alias("symbol")])
        outliers = collect_streaming(
            enriched.select(
                [
                    "timestamp",
                    pl.from_epoch(pl.col("timestamp"), time_unit="us").alias("utc"),
                    "ticker",
                    "bid_price",
                    "ask_price",
                    "bid_amount",
                    "ask_amount",
                    "spread_bps",
                    "top_imbalance",
                ]
            )
            .sort("spread_bps", descending=True)
            .limit(50)
        ).with_columns([pl.lit(source).alias("source"), pl.lit(symbol).alias("symbol")])
        write_df(source_out_path(paths, "source_daily", source, symbol), daily)
        write_df(source_out_path(paths, "source_hourly", source, symbol), hourly)
        write_df(source_out_path(paths, "source_outliers", source, symbol), outliers)
    else:
        enriched = lf.with_columns(
            [
                *date_hour_exprs(),
                pl.col("side").str.to_lowercase().alias("side_lower"),
                (pl.col("price") * pl.col("amount")).alias("notional"),
                (pl.col("price").is_null() | pl.col("amount").is_null() | pl.col("side").is_null()).alias("has_null"),
            ]
        )
        daily = collect_streaming(
            enriched.group_by("date")
            .agg(
                [
                    pl.len().alias("rows"),
                    pl.col("timestamp").min().alias("min_timestamp"),
                    pl.col("timestamp").max().alias("max_timestamp"),
                    (pl.col("price") <= 0).sum().alias("bad_price_rows"),
                    (pl.col("amount") <= 0).sum().alias("bad_amount_rows"),
                    pl.col("has_null").sum().alias("null_rows"),
                    (pl.col("side_lower") == "buy").sum().alias("buy_rows"),
                    (pl.col("side_lower") == "sell").sum().alias("sell_rows"),
                    pl.when(pl.col("side_lower") == "buy").then(pl.col("notional")).otherwise(0.0).sum().alias("buy_notional"),
                    pl.when(pl.col("side_lower") == "sell").then(pl.col("notional")).otherwise(0.0).sum().alias("sell_notional"),
                    pl.col("notional").sum().alias("notional_sum"),
                    pl.col("notional").mean().alias("notional_mean"),
                    pl.col("notional").quantile(0.50).alias("notional_p50"),
                    pl.col("notional").quantile(0.90).alias("notional_p90"),
                    pl.col("notional").quantile(0.99).alias("notional_p99"),
                    pl.col("notional").quantile(0.999).alias("notional_p999"),
                    pl.col("notional").max().alias("notional_max"),
                    pl.col("amount").quantile(0.50).alias("amount_p50"),
                    pl.col("amount").quantile(0.99).alias("amount_p99"),
                    pl.col("price").min().alias("price_min"),
                    pl.col("price").max().alias("price_max"),
                ]
            )
            .sort("date")
        ).with_columns([pl.lit(source).alias("source"), pl.lit(symbol).alias("symbol")])
        hourly = collect_streaming(
            enriched.group_by(["date", "hour"])
            .agg(
                [
                    pl.len().alias("rows"),
                    pl.col("notional").sum().alias("notional_sum"),
                    (pl.col("side_lower") == "buy").sum().alias("buy_rows"),
                    (pl.col("side_lower") == "sell").sum().alias("sell_rows"),
                    pl.when(pl.col("side_lower") == "buy").then(pl.col("notional")).otherwise(0.0).sum().alias("buy_notional"),
                    pl.when(pl.col("side_lower") == "sell").then(pl.col("notional")).otherwise(0.0).sum().alias("sell_notional"),
                    pl.col("notional").quantile(0.99).alias("notional_p99"),
                ]
            )
            .sort(["date", "hour"])
        ).with_columns([pl.lit(source).alias("source"), pl.lit(symbol).alias("symbol")])
        outliers = collect_streaming(
            enriched.select(
                [
                    "timestamp",
                    pl.from_epoch(pl.col("timestamp"), time_unit="us").alias("utc"),
                    "ticker",
                    "side",
                    "price",
                    "amount",
                    "notional",
                ]
            )
            .sort("notional", descending=True)
            .limit(50)
        ).with_columns([pl.lit(source).alias("source"), pl.lit(symbol).alias("symbol")])
        write_df(source_out_path(paths, "source_daily", source, symbol), daily)
        write_df(source_out_path(paths, "source_hourly", source, symbol), hourly)
        write_df(source_out_path(paths, "source_outliers", source, symbol), outliers)
    release_memory()


def trade_source_profile_chunked(paths: Paths, source: str, symbol: str, start: date, end: date) -> None:
    """Memory-bounded profile for the huge Binance trade files."""
    daily_frames: list[pl.DataFrame] = []
    hourly_frames: list[pl.DataFrame] = []
    gap_rows: list[dict] = []
    outlier_frames: list[pl.DataFrame] = []

    for d in iter_dates(start, end):
        start_us = date_to_us(d)
        end_us = date_to_us(d + timedelta(days=1))
        lf = scan_file(paths, source, symbol, start_us, end_us)
        enriched = lf.with_columns(
            [
                *date_hour_exprs(),
                pl.col("side").str.to_lowercase().alias("side_lower"),
                (pl.col("price") * pl.col("amount")).alias("notional"),
                (pl.col("price").is_null() | pl.col("amount").is_null() | pl.col("side").is_null()).alias("has_null"),
            ]
        )
        daily = collect_streaming(
            enriched.group_by("date").agg(
                [
                    pl.len().alias("rows"),
                    pl.col("timestamp").min().alias("min_timestamp"),
                    pl.col("timestamp").max().alias("max_timestamp"),
                    (pl.col("price") <= 0).sum().alias("bad_price_rows"),
                    (pl.col("amount") <= 0).sum().alias("bad_amount_rows"),
                    pl.col("has_null").sum().alias("null_rows"),
                    (pl.col("side_lower") == "buy").sum().alias("buy_rows"),
                    (pl.col("side_lower") == "sell").sum().alias("sell_rows"),
                    pl.when(pl.col("side_lower") == "buy").then(pl.col("notional")).otherwise(0.0).sum().alias("buy_notional"),
                    pl.when(pl.col("side_lower") == "sell").then(pl.col("notional")).otherwise(0.0).sum().alias("sell_notional"),
                    pl.col("notional").sum().alias("notional_sum"),
                    pl.col("notional").mean().alias("notional_mean"),
                    pl.col("notional").quantile(0.50).alias("notional_p50"),
                    pl.col("notional").quantile(0.90).alias("notional_p90"),
                    pl.col("notional").quantile(0.99).alias("notional_p99"),
                    pl.col("notional").quantile(0.999).alias("notional_p999"),
                    pl.col("notional").max().alias("notional_max"),
                    pl.col("amount").quantile(0.50).alias("amount_p50"),
                    pl.col("amount").quantile(0.99).alias("amount_p99"),
                    pl.col("price").min().alias("price_min"),
                    pl.col("price").max().alias("price_max"),
                ]
            )
        )
        hourly = collect_streaming(
            enriched.group_by(["date", "hour"]).agg(
                [
                    pl.len().alias("rows"),
                    pl.col("notional").sum().alias("notional_sum"),
                    (pl.col("side_lower") == "buy").sum().alias("buy_rows"),
                    (pl.col("side_lower") == "sell").sum().alias("sell_rows"),
                    pl.when(pl.col("side_lower") == "buy").then(pl.col("notional")).otherwise(0.0).sum().alias("buy_notional"),
                    pl.when(pl.col("side_lower") == "sell").then(pl.col("notional")).otherwise(0.0).sum().alias("sell_notional"),
                    pl.col("notional").quantile(0.99).alias("notional_p99"),
                ]
            )
        )
        gaps = collect_streaming(
            lf.select("timestamp")
            .with_columns(pl.col("timestamp").diff().alias("dt_us"))
            .select(
                [
                    pl.len().alias("rows"),
                    pl.col("timestamp").min().alias("min_timestamp"),
                    pl.col("timestamp").max().alias("max_timestamp"),
                    (pl.col("dt_us") < 0).sum().alias("negative_time_jumps"),
                    (pl.col("dt_us") == 0).sum().alias("same_timestamp_as_previous"),
                    pl.lit(None, dtype=pl.Int64).alias("exact_adjacent_duplicates"),
                    pl.col("dt_us").filter(pl.col("dt_us").is_not_null() & (pl.col("dt_us") >= 0)).quantile(0.50).alias("dt_us_p50"),
                    pl.col("dt_us").filter(pl.col("dt_us").is_not_null() & (pl.col("dt_us") >= 0)).quantile(0.90).alias("dt_us_p90"),
                    pl.col("dt_us").filter(pl.col("dt_us").is_not_null() & (pl.col("dt_us") >= 0)).quantile(0.99).alias("dt_us_p99"),
                    pl.col("dt_us").filter(pl.col("dt_us").is_not_null() & (pl.col("dt_us") >= 0)).quantile(0.999).alias("dt_us_p999"),
                    pl.col("dt_us").max().alias("dt_us_max"),
                    (pl.col("dt_us") > 1_000_000).sum().alias("gaps_gt_1s"),
                    (pl.col("dt_us") > 10_000_000).sum().alias("gaps_gt_10s"),
                    (pl.col("dt_us") > 60_000_000).sum().alias("gaps_gt_60s"),
                ]
            )
        )
        outliers = collect_streaming(
            enriched.select(
                [
                    "timestamp",
                    pl.from_epoch(pl.col("timestamp"), time_unit="us").alias("utc"),
                    "ticker",
                    "side",
                    "price",
                    "amount",
                    "notional",
                ]
            )
            .sort("notional", descending=True)
            .limit(20)
        )
        if not daily.is_empty():
            daily_frames.append(daily)
        if not hourly.is_empty():
            hourly_frames.append(hourly)
        if not gaps.is_empty():
            row = gaps.to_dicts()[0]
            row["date"] = d.isoformat()
            gap_rows.append(row)
        if not outliers.is_empty():
            outlier_frames.append(outliers)
        del lf, enriched, daily, hourly, gaps, outliers
        release_memory()

    daily_all = pl.concat(daily_frames, how="vertical").sort("date").with_columns([pl.lit(source).alias("source"), pl.lit(symbol).alias("symbol")])
    hourly_all = pl.concat(hourly_frames, how="vertical").sort(["date", "hour"]).with_columns([pl.lit(source).alias("source"), pl.lit(symbol).alias("symbol")])
    gaps_all = pl.DataFrame(gap_rows).with_columns([pl.lit(source).alias("source"), pl.lit(symbol).alias("symbol")])
    outliers_all = (
        pl.concat(outlier_frames, how="vertical")
        .sort("notional", descending=True)
        .head(50)
        .with_columns([pl.lit(source).alias("source"), pl.lit(symbol).alias("symbol")])
    )
    write_df(source_out_path(paths, "source_daily", source, symbol), daily_all)
    write_df(source_out_path(paths, "source_hourly", source, symbol), hourly_all)
    write_df(source_out_path(paths, "timestamp_gaps", source, symbol), gaps_all)
    write_df(source_out_path(paths, "source_outliers", source, symbol), outliers_all)
    release_memory()


def load_trades_day(paths: Paths, symbol: str, start_us: int, end_us: int) -> pl.DataFrame:
    return collect_streaming(
        scan_file(paths, "binance_trades", symbol, start_us, end_us)
        .select(["timestamp", "ticker", "side", "price", "amount"])
        .with_columns(
            [
                pl.col("side").str.to_lowercase().alias("side_lower"),
                (pl.col("price") * pl.col("amount")).alias("notional"),
            ]
        )
        .with_columns(
            [
                pl.min_horizontal(pl.col("notional"), pl.lit(100_000.0)).alias("weight"),
                pl.when(pl.col("side_lower") == "buy").then(1.0).otherwise(-1.0).alias("maker_short_sign"),
                pl.from_epoch(pl.col("timestamp"), time_unit="us").dt.hour().alias("hour"),
            ]
        )
        .sort("timestamp")
    )


def load_bbo_range(paths: Paths, symbol: str, start_us: int, end_us: int) -> pl.DataFrame:
    depth = pl.col("bid_amount") + pl.col("ask_amount")
    mid = (pl.col("bid_price") + pl.col("ask_price")) / 2
    microprice = (pl.col("ask_price") * pl.col("bid_amount") + pl.col("bid_price") * pl.col("ask_amount")) / depth
    return collect_streaming(
        scan_file(paths, "binance_booktickers", symbol, start_us, end_us)
        .select(["timestamp", "ticker", "bid_price", "bid_amount", "ask_price", "ask_amount"])
        .with_columns(
            [
                mid.alias("mid"),
                (pl.col("ask_price") - pl.col("bid_price")).alias("spread"),
                ((pl.col("ask_price") - pl.col("bid_price")) / mid * 10_000).alias("spread_bps"),
                ((pl.col("bid_amount") - pl.col("ask_amount")) / depth).alias("top_imbalance"),
                ((microprice - mid) / mid * 10_000).alias("microprice_offset_bps"),
            ]
        )
        .sort("timestamp")
    )


def load_liq_day(paths: Paths, symbol: str, start_us: int, end_us: int) -> pl.DataFrame:
    frames = []
    for source in ("binance_liquidations", "bybit_liquidations"):
        shift = BYBIT_DELAY_US if source == "bybit_liquidations" else 0
        raw = collect_streaming(
            scan_file(paths, source, symbol, start_us - shift, end_us - shift)
            .select(["timestamp", "ticker", "side", "price", "amount"])
            .with_columns(
                [
                    pl.lit(source.replace("_liquidations", "")).alias("source"),
                    pl.col("timestamp").alias("raw_timestamp"),
                    (pl.col("timestamp") + shift).alias("timestamp"),
                    pl.col("side").str.to_lowercase().alias("side_lower"),
                    (pl.col("price") * pl.col("amount")).alias("notional"),
                ]
            )
            .with_columns(
                [
                    pl.when(pl.col("side_lower") == "buy").then(1.0).otherwise(-1.0).alias("liq_sign"),
                ]
            )
            .with_columns((pl.col("liq_sign") * pl.col("notional")).alias("signed_notional"))
        )
        frames.append(raw)
    return pl.concat(frames, how="vertical").sort("timestamp") if frames else pl.DataFrame()


def asof_values(base_ts: np.ndarray, values: np.ndarray, query_ts: np.ndarray) -> np.ndarray:
    idx = np.searchsorted(base_ts, query_ts, side="right") - 1
    out = np.full(len(query_ts), np.nan, dtype=np.float64)
    ok = idx >= 0
    out[ok] = values[idx[ok]]
    return out


def rolling_sum(event_ts: np.ndarray, values: np.ndarray, query_ts: np.ndarray, window_us: int) -> np.ndarray:
    if len(event_ts) == 0:
        return np.zeros(len(query_ts), dtype=np.float64)
    right = np.searchsorted(event_ts, query_ts, side="right")
    left = np.searchsorted(event_ts, query_ts - window_us, side="right")
    cum = np.concatenate([[0.0], np.cumsum(values, dtype=np.float64)])
    return cum[right] - cum[left]


def size_bucket(notional: np.ndarray) -> np.ndarray:
    bins = np.array([0.0, 1_000.0, 10_000.0, 100_000.0, 1_000_000.0, np.inf])
    labels = np.array(["00_<1k", "01_1k_10k", "02_10k_100k", "03_100k_1m", "04_>1m"], dtype=object)
    idx = np.digitize(notional, bins[1:-1], right=False)
    return labels[idx]


def agg_weighted(values: np.ndarray, weights: np.ndarray) -> float:
    ok = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not np.any(ok):
        return math.nan
    return float(np.sum(values[ok] * weights[ok]) / np.sum(weights[ok]))


def process_relationship_segment(paths: Paths, symbol: str, start: date, end: date) -> None:
    print(f"[relationships] {symbol} {start} {end}", flush=True)
    trade_bbo_rows = []
    liq_event_rows = []
    liq_alignment_rows = []
    convention_rows = []

    for d in iter_dates(start, end):
        day = d.isoformat()
        start_us = date_to_us(d)
        end_us = date_to_us(d + timedelta(days=1))
        trades = load_trades_day(paths, symbol, start_us, end_us)
        bbo = load_bbo_range(paths, symbol, start_us - 300_000_000, end_us + 300_000_000)
        if trades.is_empty() or bbo.is_empty():
            continue
        joined = trades.join_asof(
            bbo.select(["timestamp", "bid_price", "ask_price", "mid", "spread_bps", "top_imbalance", "microprice_offset_bps"]),
            on="timestamp",
            strategy="backward",
        )
        joined = joined.with_columns(
            [
                ((pl.col("price") - pl.col("bid_price")) / pl.col("price") * 10_000).alias("price_minus_bid_bps"),
                ((pl.col("price") - pl.col("ask_price")) / pl.col("price") * 10_000).alias("price_minus_ask_bps"),
                (abs(pl.col("price") - pl.col("ask_price")) <= abs(pl.col("price") - pl.col("bid_price"))).alias("closer_to_ask"),
                (abs(pl.col("price") - pl.col("bid_price")) <= abs(pl.col("price") - pl.col("ask_price"))).alias("closer_to_bid"),
                (pl.col("price") > pl.col("ask_price")).alias("trade_above_ask"),
                (pl.col("price") < pl.col("bid_price")).alias("trade_below_bid"),
                ((pl.col("price") - pl.col("mid")) / pl.col("price") * 10_000).alias("trade_vs_mid_bps"),
            ]
        )
        buy = joined.filter(pl.col("side_lower") == "buy")
        sell = joined.filter(pl.col("side_lower") == "sell")
        row = {
            "date": day,
            "symbol": symbol,
            "trades": joined.height,
            "buy_trades": buy.height,
            "sell_trades": sell.height,
            "buy_closer_to_ask_share": float(buy["closer_to_ask"].mean()) if buy.height else math.nan,
            "sell_closer_to_bid_share": float(sell["closer_to_bid"].mean()) if sell.height else math.nan,
            "trade_above_ask_share": float(joined["trade_above_ask"].mean()),
            "trade_below_bid_share": float(joined["trade_below_bid"].mean()),
            "spread_bps_at_trade_mean": float(joined["spread_bps"].mean()),
            "spread_bps_at_trade_p50": float(joined["spread_bps"].median()),
            "spread_bps_at_trade_p99": float(joined["spread_bps"].quantile(0.99)),
            "top_imbalance_at_trade_mean": float(joined["top_imbalance"].mean()),
            "microprice_offset_at_trade_mean": float(joined["microprice_offset_bps"].mean()),
            "buy_price_minus_ask_bps_p50": float(buy["price_minus_ask_bps"].median()) if buy.height else math.nan,
            "sell_price_minus_bid_bps_p50": float(sell["price_minus_bid_bps"].median()) if sell.height else math.nan,
            "trade_vs_mid_bps_p01": float(joined["trade_vs_mid_bps"].quantile(0.01)),
            "trade_vs_mid_bps_p50": float(joined["trade_vs_mid_bps"].median()),
            "trade_vs_mid_bps_p99": float(joined["trade_vs_mid_bps"].quantile(0.99)),
        }
        trade_bbo_rows.append(row)
        if len(convention_rows) < 20:
            examples = joined.head(4).select(
                [
                    "timestamp",
                    pl.from_epoch(pl.col("timestamp"), time_unit="us").alias("utc"),
                    pl.lit(symbol).alias("symbol"),
                    "side",
                    "price",
                    "bid_price",
                    "ask_price",
                    "price_minus_bid_bps",
                    "price_minus_ask_bps",
                ]
            )
            convention_rows.extend(examples.to_dicts())

        bbo_ts = bbo["timestamp"].to_numpy()
        mid = bbo["mid"].to_numpy().astype(np.float64, copy=False)
        spread = bbo["spread_bps"].to_numpy().astype(np.float64, copy=False)
        trade_ts = trades["timestamp"].to_numpy()
        trade_notional = trades["notional"].to_numpy().astype(np.float64, copy=False)
        trade_signed = (trades["maker_short_sign"].to_numpy().astype(np.float64, copy=False) * trade_notional)

        liq = load_liq_day(paths, symbol, start_us, end_us)
        if not liq.is_empty():
            liq_ts = liq["timestamp"].to_numpy()
            liq_notional = liq["notional"].to_numpy().astype(np.float64, copy=False)
            liq_signed = liq["signed_notional"].to_numpy().astype(np.float64, copy=False)
            liq_source = np.array(liq["source"].to_list(), dtype=object)
            liq_side = np.array(liq["side_lower"].to_list(), dtype=object)
            liq_bucket = size_bucket(liq_notional)
            mid_t = asof_values(bbo_ts, mid, liq_ts)
            spread_t = asof_values(bbo_ts, spread, liq_ts)
            data = {
                "date": day,
                "symbol": symbol,
                "source": liq_source,
                "side": liq_side,
                "size_bucket": liq_bucket,
                "events": np.ones(len(liq_ts), dtype=np.float64),
                "notional": liq_notional,
                "spread_bps_at_event": spread_t,
            }
            for label, horizon_us in HORIZONS_US.items():
                before_mid = asof_values(bbo_ts, mid, liq_ts - horizon_us)
                after_mid = asof_values(bbo_ts, mid, liq_ts + horizon_us)
                data[f"mid_ret_before_{label}_bps"] = (mid_t - before_mid) / before_mid * 10_000
                data[f"mid_ret_after_{label}_bps"] = (after_mid - mid_t) / mid_t * 10_000
                data[f"signed_mid_ret_after_{label}_bps"] = np.where(liq_side == "buy", 1.0, -1.0) * data[f"mid_ret_after_{label}_bps"]
            for label, window_us in TRADE_FLOW_WINDOWS_US.items():
                before_notional = rolling_sum(trade_ts, trade_notional, liq_ts, window_us)
                before_signed = rolling_sum(trade_ts, trade_signed, liq_ts, window_us)
                after_notional = rolling_sum(trade_ts, trade_notional, liq_ts + window_us, window_us)
                after_signed = rolling_sum(trade_ts, trade_signed, liq_ts + window_us, window_us)
                data[f"trade_notional_before_{label}"] = before_notional
                data[f"trade_notional_after_{label}"] = after_notional
                data[f"signed_trade_notional_before_{label}"] = before_signed
                data[f"signed_trade_notional_after_{label}"] = after_signed
            event_df = pd.DataFrame(data)
            group_cols = ["date", "symbol", "source", "side", "size_bucket"]
            agg = event_df.groupby(group_cols, dropna=False).agg(
                events=("events", "sum"),
                notional_sum=("notional", "sum"),
                notional_p50=("notional", "median"),
                notional_max=("notional", "max"),
                spread_bps_at_event_mean=("spread_bps_at_event", "mean"),
                **{c: (c, "mean") for c in event_df.columns if c.startswith("mid_ret_") or c.startswith("signed_mid_ret_") or c.startswith("trade_notional_") or c.startswith("signed_trade_notional_")},
            ).reset_index()
            liq_event_rows.append(agg)

            for source in ("binance", "bybit"):
                mask = liq_source == source
                other_mask = liq_source != source
                if not np.any(mask) or not np.any(other_mask):
                    continue
                q_ts = liq_ts[mask]
                other_ts = liq_ts[other_mask]
                other_signed = liq_signed[other_mask]
                other_abs = np.abs(other_signed)
                align_data = {
                    "date": day,
                    "symbol": symbol,
                    "source": source,
                    "side": liq_side[mask],
                    "size_bucket": liq_bucket[mask],
                    "events": np.ones(np.sum(mask), dtype=np.float64),
                }
                for label, window_us in TRADE_FLOW_WINDOWS_US.items():
                    align_data[f"other_liq_notional_prev_{label}"] = rolling_sum(other_ts, other_abs, q_ts, window_us)
                    align_data[f"other_signed_liq_prev_{label}"] = rolling_sum(other_ts, other_signed, q_ts, window_us)
                    align_data[f"other_liq_notional_next_{label}"] = rolling_sum(other_ts, other_abs, q_ts + window_us, window_us)
                    align_data[f"other_signed_liq_next_{label}"] = rolling_sum(other_ts, other_signed, q_ts + window_us, window_us)
                align_df = pd.DataFrame(align_data)
                align_agg = align_df.groupby(["date", "symbol", "source", "side", "size_bucket"], dropna=False).agg(
                    events=("events", "sum"),
                    **{c: (c, "mean") for c in align_df.columns if c.startswith("other_")},
                ).reset_index()
                liq_alignment_rows.append(align_agg)

        del trades, bbo, joined
        release_memory()

    stem = f"{symbol}__{start.isoformat()}__{end.isoformat()}"
    if trade_bbo_rows:
        write_df(paths.segments / f"trade_bbo_sanity__{stem}.csv", pd.DataFrame(trade_bbo_rows))
    if liq_event_rows:
        write_df(paths.segments / f"liquidation_event_context__{stem}.csv", pd.concat(liq_event_rows, ignore_index=True))
    if liq_alignment_rows:
        write_df(paths.segments / f"liquidation_cross_exchange_alignment__{stem}.csv", pd.concat(liq_alignment_rows, ignore_index=True))
    if convention_rows:
        write_df(paths.segments / f"trade_convention_examples__{stem}.csv", pd.DataFrame(convention_rows))


def write_convention_liq_examples(paths: Paths) -> None:
    rows = []
    for symbol in SYMBOLS:
        for source in ("binance_liquidations", "bybit_liquidations"):
            shift = BYBIT_DELAY_US if source == "bybit_liquidations" else 0
            df = (
                pl.read_parquet(paths.file(source, symbol))
                .with_columns(
                    [
                        pl.lit(source.replace("_liquidations", "")).alias("source"),
                        pl.col("timestamp").alias("raw_timestamp"),
                        (pl.col("timestamp") + shift).alias("available_timestamp"),
                        pl.from_epoch(pl.col("timestamp"), time_unit="us").alias("raw_utc"),
                        pl.from_epoch(pl.col("timestamp") + shift, time_unit="us").alias("available_utc"),
                        pl.col("side").str.to_lowercase().alias("side_lower"),
                        (pl.col("price") * pl.col("amount")).alias("notional"),
                    ]
                )
                .sort("timestamp")
            )
            rows.extend(df.filter(pl.col("side_lower") == "buy").head(3).to_dicts())
            rows.extend(df.filter(pl.col("side_lower") == "sell").head(3).to_dicts())
    write_df(paths.segments / "liquidation_convention_examples.csv", pd.DataFrame(rows))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/mnt/d/Python/CMF/HFT_School/Task_1")
    parser.add_argument("--output-dir", default="/mnt/d/Python/CMF/HFT_School/Task_1/outputs_full_eda")
    parser.add_argument("--mode", choices=["metadata", "source-profile", "relationships", "liq-examples"], required=True)
    parser.add_argument("--source", choices=SOURCES)
    parser.add_argument("--symbol", choices=SYMBOLS)
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    paths = Paths.from_root(root, Path(args.output_dir).resolve())
    if args.mode == "metadata":
        meta = parquet_metadata(paths)
        write_df(paths.segments / "dataset_overview.csv", meta)
        (paths.output / "run_config.json").write_text(
            json.dumps({"root": str(root), "output_dir": str(paths.output)}, indent=2),
            encoding="utf-8",
        )
    elif args.mode == "source-profile":
        if args.source is None or args.symbol is None:
            raise ValueError("--source and --symbol are required")
        source_profile(
            paths,
            args.source,
            args.symbol,
            parse_date(args.start) if args.start else None,
            parse_date(args.end) if args.end else None,
        )
    elif args.mode == "relationships":
        if args.symbol is None or args.start is None or args.end is None:
            raise ValueError("--symbol, --start, and --end are required")
        process_relationship_segment(paths, args.symbol, parse_date(args.start), parse_date(args.end))
    elif args.mode == "liq-examples":
        write_convention_liq_examples(paths)


if __name__ == "__main__":
    main()
