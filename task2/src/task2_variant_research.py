from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from task2_compare_rules import (
        MAX_LOOKBACK_US,
        TURNOVER_CONSTRAINT_PER_DAY,
        build_rule_flags,
        load_liq_with_lookback,
        split_name,
        stride_trades,
        weighted_mean,
    )
    from task2_evaluate import (
        DataPaths,
        HORIZONS,
        SYMBOLS,
        add_markout_arrays,
        date_to_us,
        iter_dates,
        load_bbo,
        load_trades,
        parse_date,
        safe_divide,
    )
except ModuleNotFoundError:
    from .task2_compare_rules import (
        MAX_LOOKBACK_US,
        TURNOVER_CONSTRAINT_PER_DAY,
        build_rule_flags,
        load_liq_with_lookback,
        split_name,
        stride_trades,
        weighted_mean,
    )
    from .task2_evaluate import (
        DataPaths,
        HORIZONS,
        SYMBOLS,
        add_markout_arrays,
        date_to_us,
        iter_dates,
        load_bbo,
        load_trades,
        parse_date,
        safe_divide,
    )


BASELINE = "baseline_liq1s_d200_gt_100k"

VARIANTS: dict[str, dict[int, str]] = {
    "baseline_liq": {
        30: BASELINE,
        120: BASELINE,
        300: BASELINE,
    },
    "current_hybrid": {
        30: "return5s_gt_50",
        120: BASELINE,
        300: BASELINE,
    },
    "sniper30_hybrid": {
        30: "liq2s_and_return5s_gt_20",
        120: BASELINE,
        300: BASELINE,
    },
    "bybit300_hybrid": {
        30: "return5s_gt_50",
        120: BASELINE,
        300: "bybit5s_d200_gt_2m",
    },
    "bybit_long_hybrid": {
        30: "return5s_gt_50",
        120: "bybit5s_d200_gt_2m",
        300: "bybit5s_d200_gt_2m",
    },
    "liq2_300_hybrid": {
        30: "return5s_gt_50",
        120: BASELINE,
        300: "liq2s_d200_gt_2m",
    },
    "liq2_long_hybrid": {
        30: "return5s_gt_50",
        120: "liq2s_d200_gt_2m",
        300: "liq2s_d200_gt_2m",
    },
    "liq2_120_bybit300_hybrid": {
        30: "return5s_gt_50",
        120: "liq2s_d200_gt_2m",
        300: "bybit5s_d200_gt_2m",
    },
    "sniper30_bybit300": {
        30: "liq2s_and_return5s_gt_20",
        120: BASELINE,
        300: "bybit5s_d200_gt_2m",
    },
    "sniper30_liq2_300": {
        30: "liq2s_and_return5s_gt_20",
        120: BASELINE,
        300: "liq2s_d200_gt_2m",
    },
    "negret120_bybit300": {
        30: "return5s_gt_50",
        120: "neg_return30s_gt_50",
        300: "bybit5s_d200_gt_2m",
    },
    "negret120_liq2_300": {
        30: "return5s_gt_50",
        120: "neg_return30s_gt_50",
        300: "liq2s_d200_gt_2m",
    },
    "ret30_long_hybrid": {
        30: "return5s_gt_50",
        120: "return30s_gt_50",
        300: "return30s_gt_50",
    },
    "ret5_all": {
        30: "return5s_gt_50",
        120: "return5s_gt_50",
        300: "return5s_gt_50",
    },
    "eth100_btc50_hybrid": {
        30: "symbol_return_eth100_btc50",
        120: BASELINE,
        300: BASELINE,
    },
    "eth100_btc50_bybit300": {
        30: "symbol_return_eth100_btc50",
        120: BASELINE,
        300: "bybit5s_d200_gt_2m",
    },
    "eth100_btc50_bybit_long": {
        30: "symbol_return_eth100_btc50",
        120: "bybit5s_d200_gt_2m",
        300: "bybit5s_d200_gt_2m",
    },
    "eth100_btc50_liq2_300": {
        30: "symbol_return_eth100_btc50",
        120: BASELINE,
        300: "liq2s_d200_gt_2m",
    },
    "eth100_btc50_liq2_long": {
        30: "symbol_return_eth100_btc50",
        120: "liq2s_d200_gt_2m",
        300: "liq2s_d200_gt_2m",
    },
    "eth100_btc50_liq2_120_bybit300": {
        30: "symbol_return_eth100_btc50",
        120: "liq2s_d200_gt_2m",
        300: "bybit5s_d200_gt_2m",
    },
    "eth100_btc50_baseline_and_ret20_long": {
        30: "symbol_return_eth100_btc50",
        120: "baseline_and_return5s_gt_20",
        300: "baseline_and_return5s_gt_20",
    },
    "eth100_btc50_baseline_or_ret50_long": {
        30: "symbol_return_eth100_btc50",
        120: "baseline_or_return5s_gt_50",
        300: "baseline_or_return5s_gt_50",
    },
    "eth100_btc50_liq2_and_ret20_long": {
        30: "symbol_return_eth100_btc50",
        120: "liq2s_and_return5s_gt_20",
        300: "liq2s_and_return5s_gt_20",
    },
    "eth100_btc50_liq2_or_ret50_long": {
        30: "symbol_return_eth100_btc50",
        120: "liq2s_or_return5s_gt_50",
        300: "liq2s_or_return5s_gt_50",
    },
    "eth100_btc50_bybit_or_ret50_long": {
        30: "symbol_return_eth100_btc50",
        120: "bybit5s_or_return5s_gt_50",
        300: "bybit5s_or_return5s_gt_50",
    },
    "eth100_btc50_ret5_long": {
        30: "symbol_return_eth100_btc50",
        120: "return5s_gt_50",
        300: "return5s_gt_50",
    },
}


def score_variants(
    date_str: str,
    split: str,
    symbol: str,
    trades,
    bbo,
    liq_binance,
    liq_bybit,
    variant_names: tuple[str, ...],
) -> list[dict]:
    if trades.is_empty() or bbo.is_empty():
        return []

    weight, pnl_by_horizon, _ = add_markout_arrays(trades, bbo)
    rule_flags = build_rule_flags(trades, bbo, liq_binance, liq_bybit, "core")
    rows = []

    for variant in variant_names:
        mapping = VARIANTS[variant]
        for horizon in HORIZONS:
            rule_name = mapping[horizon]
            if rule_name == "symbol_return_eth100_btc50":
                selected_rule = "return5s_gt_100" if symbol == "ethusdt" else "return5s_gt_50"
            else:
                selected_rule = rule_name
            flags = np.asarray(rule_flags[selected_rule][horizon]).astype(bool)
            pnl = pnl_by_horizon[horizon]
            valid = np.isfinite(pnl) & np.isfinite(weight) & (weight > 0)
            kept = valid & ~flags
            filtered = valid & flags
            rows.append(
                {
                    "date": date_str,
                    "split": split,
                    "symbol": symbol,
                    "variant": variant,
                    "horizon_s": horizon,
                    "rule": selected_rule,
                    "pnl_all": weighted_mean(pnl, weight, valid),
                    "pnl_kept": weighted_mean(pnl, weight, kept),
                    "pnl_filtered": weighted_mean(pnl, weight, filtered),
                    "all_clipped_turnover": float(np.sum(weight[valid])),
                    "kept_clipped_turnover": float(np.sum(weight[kept])),
                    "filtered_clipped_turnover": float(np.sum(weight[filtered])),
                    "kept_trade_count": int(np.sum(kept)),
                    "filtered_trade_count": int(np.sum(filtered)),
                }
            )
    return rows


def summarize(rows: list[dict], group_cols: list[str]) -> pd.DataFrame:
    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily

    daily["all_weighted_pnl_sum"] = daily["pnl_all"] * daily["all_clipped_turnover"]
    daily["kept_weighted_pnl_sum"] = daily["pnl_kept"].fillna(0.0) * daily["kept_clipped_turnover"]
    daily["filtered_weighted_pnl_sum"] = daily["pnl_filtered"].fillna(0.0) * daily["filtered_clipped_turnover"]
    out = (
        daily.groupby(group_cols, as_index=False)
        .agg(
            days=("date", "nunique"),
            all_clipped_turnover=("all_clipped_turnover", "sum"),
            kept_clipped_turnover=("kept_clipped_turnover", "sum"),
            filtered_clipped_turnover=("filtered_clipped_turnover", "sum"),
            all_weighted_pnl_sum=("all_weighted_pnl_sum", "sum"),
            kept_weighted_pnl_sum=("kept_weighted_pnl_sum", "sum"),
            filtered_weighted_pnl_sum=("filtered_weighted_pnl_sum", "sum"),
            kept_trade_count=("kept_trade_count", "sum"),
            filtered_trade_count=("filtered_trade_count", "sum"),
        )
    )
    out["pnl_all"] = safe_divide(out["all_weighted_pnl_sum"], out["all_clipped_turnover"])
    out["pnl_kept"] = safe_divide(out["kept_weighted_pnl_sum"], out["kept_clipped_turnover"])
    out["pnl_filtered"] = safe_divide(out["filtered_weighted_pnl_sum"], out["filtered_clipped_turnover"])
    out["score"] = out["pnl_kept"] - out["pnl_all"]
    out["kept_turnover_per_day"] = out["kept_clipped_turnover"] / out["days"]
    out["constraint_ok"] = out["kept_turnover_per_day"] >= TURNOVER_CONSTRAINT_PER_DAY
    return out[
        [
            *group_cols,
            "days",
            "pnl_all",
            "pnl_kept",
            "pnl_filtered",
            "score",
            "kept_turnover_per_day",
            "constraint_ok",
            "kept_trade_count",
            "filtered_trade_count",
            "all_clipped_turnover",
            "kept_clipped_turnover",
            "filtered_clipped_turnover",
        ]
    ]


def run(
    data_root: Path,
    output_dir: Path,
    start: str,
    end: str,
    symbols: tuple[str, ...],
    variants: tuple[str, ...],
    trade_stride: int,
) -> None:
    paths = DataPaths.from_root(data_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for current in iter_dates(parse_date(start), parse_date(end)):
        date_str = current.isoformat()
        start_us = date_to_us(current)
        end_us = date_to_us(current + timedelta(days=1))
        split = split_name(current)
        for symbol in symbols:
            print(f"[variant] {date_str} {symbol}", flush=True)
            trades = stride_trades(load_trades(paths, symbol, start_us, end_us), trade_stride)
            if trades.is_empty():
                continue
            bbo = load_bbo(paths, symbol, start_us - MAX_LOOKBACK_US, end_us + max(HORIZONS) * 1_000_000 + 1_000_000)
            liq_binance = load_liq_with_lookback(paths.liq_binance(symbol), start_us, end_us, MAX_LOOKBACK_US)
            liq_bybit = load_liq_with_lookback(paths.liq_bybit(symbol), start_us, end_us, MAX_LOOKBACK_US)
            rows.extend(score_variants(date_str, split, symbol, trades, bbo, liq_binance, liq_bybit, variants))

    daily = pd.DataFrame(rows)
    daily.to_csv(output_dir / "variant_daily_metrics.csv", index=False)
    by_split = summarize(rows, ["split", "variant", "horizon_s"])
    overall = summarize(rows, ["variant", "horizon_s"])
    by_symbol = summarize(rows, ["variant", "horizon_s", "symbol"])
    by_split.to_csv(output_dir / "variant_summary_by_split.csv", index=False)
    overall.to_csv(output_dir / "variant_summary_overall.csv", index=False)
    by_symbol.to_csv(output_dir / "variant_summary_by_symbol.csv", index=False)
    (output_dir / "variant_config.json").write_text(
        json.dumps(
            {
                "data_root": str(paths.data),
                "start": start,
                "end": end,
                "symbols": symbols,
                "variants": variants,
                "variant_mappings": {name: VARIANTS[name] for name in variants},
                "trade_stride": trade_stride,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nTop overall variants", flush=True)
    print(
        overall[overall["constraint_ok"]]
        .sort_values(["horizon_s", "score"], ascending=[True, False])
        .groupby("horizon_s")
        .head(10)
        .to_string(index=False),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-dir", default="outputs_variant_research")
    parser.add_argument("--start", default="2025-12-01")
    parser.add_argument("--end", default="2026-03-01")
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS), choices=list(SYMBOLS))
    parser.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=list(VARIANTS))
    parser.add_argument("--trade-stride", type=int, default=1)
    args = parser.parse_args()
    run(
        data_root=Path(args.data_root).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        start=args.start,
        end=args.end,
        symbols=tuple(args.symbols),
        variants=tuple(args.variants),
        trade_stride=max(1, args.trade_stride),
    )


if __name__ == "__main__":
    main()
