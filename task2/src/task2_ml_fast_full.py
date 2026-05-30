from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge, RidgeClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

try:
    from task2_evaluate import (
        DataPaths,
        HORIZONS,
        SYMBOLS,
        date_to_us,
        iter_dates,
        load_bbo,
        load_trades,
        parse_date,
        safe_divide,
    )
    from task2_ml_research import (
        FEATURE_NAMES,
        MAX_LOOKBACK_US,
        TURNOVER_CONSTRAINT_PER_DAY,
        build_features,
        load_liq_with_lookback,
        stride_trades,
    )
except ModuleNotFoundError:
    from .task2_evaluate import (
        DataPaths,
        HORIZONS,
        SYMBOLS,
        date_to_us,
        iter_dates,
        load_bbo,
        load_trades,
        parse_date,
        safe_divide,
    )
    from .task2_ml_research import (
        FEATURE_NAMES,
        MAX_LOOKBACK_US,
        TURNOVER_CONSTRAINT_PER_DAY,
        build_features,
        load_liq_with_lookback,
        stride_trades,
    )


KEEP_FRACTIONS = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20)


@dataclass
class FastModel:
    name: str
    horizon: int
    model: object
    center: np.ndarray
    scale: np.ndarray
    thresholds: dict[float, float]
    train_auc: float | None
    train_ap: float | None


def read_day_features(paths: DataPaths, current, symbol: str, trade_stride: int):
    start_us = date_to_us(current)
    end_us = date_to_us(current + timedelta(days=1))
    trades = stride_trades(load_trades(paths, symbol, start_us, end_us), trade_stride)
    if trades.is_empty():
        return np.empty((0, len(FEATURE_NAMES)), dtype=np.float32), np.empty(0, dtype=np.float32), {}
    bbo = load_bbo(paths, symbol, start_us - MAX_LOOKBACK_US, end_us + max(HORIZONS) * 1_000_000 + 1_000_000)
    liq_binance = load_liq_with_lookback(paths.liq_binance(symbol), start_us, end_us, MAX_LOOKBACK_US)
    liq_bybit = load_liq_with_lookback(paths.liq_bybit(symbol), start_us, end_us, MAX_LOOKBACK_US)
    return build_features(symbol, trades, bbo, liq_binance, liq_bybit)


def fit_transform_stats(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    center = np.nanmedian(x, axis=0).astype(np.float32)
    filled = np.where(np.isfinite(x), x, center)
    scale = np.nanstd(filled, axis=0).astype(np.float32)
    scale = np.where(scale > 1e-12, scale, 1.0).astype(np.float32)
    return ((filled - center) / scale).astype(np.float32, copy=False), center, scale


def transform(x: np.ndarray, center: np.ndarray, scale: np.ndarray) -> np.ndarray:
    filled = np.where(np.isfinite(x), x, center)
    return ((filled - center) / scale).astype(np.float32, copy=False)


def predict_score(item: FastModel, x: np.ndarray) -> np.ndarray:
    z = transform(x, item.center, item.scale)
    if item.name == "ridge_classifier_positive":
        return item.model.decision_function(z)
    return item.model.predict(z)


def weighted_mean(values: np.ndarray, weight: np.ndarray, mask: np.ndarray) -> float:
    valid = mask & np.isfinite(values) & np.isfinite(weight) & (weight > 0)
    if not np.any(valid):
        return float("nan")
    w = weight[valid]
    return float(np.sum(w * values[valid]) / np.sum(w))


def safe_auc(y: np.ndarray, score: np.ndarray) -> tuple[float | None, float | None]:
    target = y > 0
    if len(np.unique(target)) < 2:
        return None, None
    return float(roc_auc_score(target, score)), float(average_precision_score(target, score))


def collect_train(paths: DataPaths, start: str, end: str, symbols: tuple[str, ...], train_stride: int):
    x_by_h: dict[int, list[np.ndarray]] = defaultdict(list)
    y_by_h: dict[int, list[np.ndarray]] = defaultdict(list)
    w_by_h: dict[int, list[np.ndarray]] = defaultdict(list)
    days = 0
    for current in iter_dates(parse_date(start), parse_date(end)):
        days += 1
        date_str = current.isoformat()
        for symbol in symbols:
            print(f"[ml-fast] train features {date_str} {symbol}", flush=True)
            x, weight, pnl_by_h = read_day_features(paths, current, symbol, train_stride)
            if len(x) == 0:
                continue
            valid_base = np.isfinite(weight) & (weight > 0)
            for horizon, pnl in pnl_by_h.items():
                valid = valid_base & np.isfinite(pnl)
                if not np.any(valid):
                    continue
                x_by_h[horizon].append(x[valid])
                y_by_h[horizon].append(pnl[valid].astype(np.float32, copy=False))
                w_by_h[horizon].append(weight[valid].astype(np.float32, copy=False))
    return x_by_h, y_by_h, w_by_h, days


def train_fast_models(x_by_h, y_by_h, w_by_h) -> tuple[list[FastModel], pd.DataFrame, pd.DataFrame]:
    models: list[FastModel] = []
    threshold_rows = []
    coef_rows = []
    for horizon in HORIZONS:
        x = np.vstack(x_by_h[horizon])
        y = np.concatenate(y_by_h[horizon])
        w = np.concatenate(w_by_h[horizon])
        z, center, scale = fit_transform_stats(x)
        sample_weight = np.minimum(w, 100_000.0)
        specs = [
            ("ridge_regressor_clip100", Ridge(alpha=25.0), np.clip(y, -100.0, 100.0)),
            ("ridge_classifier_positive", RidgeClassifier(alpha=25.0), (y > 0).astype(np.int8)),
        ]

        for name, model, target in specs:
            print(f"[ml-fast] fit {name} h={horizon} rows={len(z):,}", flush=True)
            model.fit(z, target, sample_weight=sample_weight)
            score = model.decision_function(z) if name == "ridge_classifier_positive" else model.predict(z)
            auc, ap = safe_auc(y, score)
            thresholds = {fraction: float(np.quantile(score[np.isfinite(score)], 1.0 - fraction)) for fraction in KEEP_FRACTIONS}
            models.append(FastModel(name, horizon, model, center, scale, thresholds, auc, ap))

            coef = np.asarray(model.coef_).reshape(-1)
            for feature, value in zip(FEATURE_NAMES, coef):
                coef_rows.append(
                    {
                        "model": name,
                        "horizon_s": horizon,
                        "feature": feature,
                        "coef_on_scaled_feature": float(value),
                        "abs_coef": float(abs(value)),
                    }
                )

            for fraction, threshold in thresholds.items():
                keep = score > threshold
                pnl_all = weighted_mean(y, w, np.ones(len(y), dtype=bool))
                pnl_kept = weighted_mean(y, w, keep)
                threshold_rows.append(
                    {
                        "model": name,
                        "horizon_s": horizon,
                        "keep_fraction": fraction,
                        "threshold": threshold,
                        "train_rows": int(len(y)),
                        "train_auc_positive_pnl": auc,
                        "train_average_precision": ap,
                        "train_pnl_all": pnl_all,
                        "train_pnl_kept": pnl_kept,
                        "train_score": pnl_kept - pnl_all,
                        "train_kept_turnover": float(np.sum(w[keep])),
                    }
                )
    return models, pd.DataFrame(threshold_rows), pd.DataFrame(coef_rows)


def metric_row(date_str, symbol, split, item: FastModel, fraction, pnl, weight, keep):
    valid = np.isfinite(pnl) & np.isfinite(weight) & (weight > 0)
    kept = valid & keep
    filtered = valid & ~keep
    return {
        "date": date_str,
        "symbol": symbol,
        "split": split,
        "model": item.name,
        "horizon_s": item.horizon,
        "keep_fraction": fraction,
        "pnl_all": weighted_mean(pnl, weight, valid),
        "pnl_kept": weighted_mean(pnl, weight, kept),
        "pnl_filtered": weighted_mean(pnl, weight, filtered),
        "all_clipped_turnover": float(np.sum(weight[valid])),
        "kept_clipped_turnover": float(np.sum(weight[kept])),
        "filtered_clipped_turnover": float(np.sum(weight[filtered])),
        "kept_trade_count": int(np.sum(kept)),
        "filtered_trade_count": int(np.sum(filtered)),
    }


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


def evaluate_split(
    paths: DataPaths,
    models: list[FastModel],
    split: str,
    start: str,
    end: str,
    symbols: tuple[str, ...],
    output_dir: Path,
    validation_stride: int,
):
    by_horizon: dict[int, list[FastModel]] = defaultdict(list)
    for item in models:
        by_horizon[item.horizon].append(item)

    rows = []
    for current in iter_dates(parse_date(start), parse_date(end)):
        date_str = current.isoformat()
        for symbol in symbols:
            print(f"[ml-fast] eval {split} {date_str} {symbol}", flush=True)
            x, weight, pnl_by_h = read_day_features(paths, current, symbol, trade_stride=validation_stride)
            if len(x) == 0:
                continue
            for horizon, pnl in pnl_by_h.items():
                for item in by_horizon[horizon]:
                    score = predict_score(item, x)
                    for fraction, threshold in item.thresholds.items():
                        rows.append(metric_row(date_str, symbol, split, item, fraction, pnl, weight, score > threshold))
    daily = pd.DataFrame(rows)
    daily.to_csv(output_dir / f"ml_fast_{split}_daily_metrics.csv", index=False)
    summary = summarize(rows, ["split", "model", "horizon_s", "keep_fraction"])
    summary.to_csv(output_dir / f"ml_fast_{split}_summary.csv", index=False)
    return summary


def run(
    data_root: Path,
    output_dir: Path,
    train_start: str,
    train_end: str,
    validation_start: str,
    validation_end: str,
    symbols: tuple[str, ...],
    train_stride: int,
    validation_stride: int,
):
    paths = DataPaths.from_root(data_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    x_by_h, y_by_h, w_by_h, train_days = collect_train(paths, train_start, train_end, symbols, train_stride)
    models, thresholds, coefs = train_fast_models(x_by_h, y_by_h, w_by_h)
    thresholds.to_csv(output_dir / "ml_fast_train_thresholds.csv", index=False)
    coefs.sort_values(["model", "horizon_s", "abs_coef"], ascending=[True, True, False]).to_csv(output_dir / "ml_fast_coefficients.csv", index=False)
    validation = evaluate_split(
        paths,
        models,
        "validation",
        validation_start,
        validation_end,
        symbols,
        output_dir,
        validation_stride,
    )
    best = validation[validation["constraint_ok"]].sort_values(["model", "horizon_s", "score"], ascending=[True, True, False])
    best.groupby(["model", "horizon_s"]).head(5).to_csv(output_dir / "ml_fast_validation_best.csv", index=False)
    (output_dir / "ml_fast_config.json").write_text(
        json.dumps(
            {
                "data_root": str(paths.data),
                "train_start": train_start,
                "train_end": train_end,
                "validation_start": validation_start,
                "validation_end": validation_end,
                "symbols": symbols,
                "train_stride": train_stride,
                "validation_stride": validation_stride,
                "train_days": train_days,
                "keep_fractions": KEEP_FRACTIONS,
                "features": FEATURE_NAMES,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(best.groupby(["model", "horizon_s"]).head(5).to_string(index=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-dir", default="outputs_ml_fast_full")
    parser.add_argument("--train-start", default="2025-12-01")
    parser.add_argument("--train-end", default="2026-02-01")
    parser.add_argument("--validation-start", default="2026-02-01")
    parser.add_argument("--validation-end", default="2026-03-01")
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS), choices=list(SYMBOLS))
    parser.add_argument("--train-stride", type=int, default=1000)
    parser.add_argument("--validation-stride", type=int, default=1)
    args = parser.parse_args()
    run(
        data_root=Path(args.data_root).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        train_start=args.train_start,
        train_end=args.train_end,
        validation_start=args.validation_start,
        validation_end=args.validation_end,
        symbols=tuple(args.symbols),
        train_stride=max(1, args.train_stride),
        validation_stride=max(1, args.validation_stride),
    )


if __name__ == "__main__":
    main()
