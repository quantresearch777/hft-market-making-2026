from __future__ import annotations

import argparse
import json
import pickle
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, roc_auc_score

try:
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
        add_markout_arrays,
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
class TrainedModel:
    model_name: str
    horizon: int
    model: object
    thresholds: dict[float, float]
    train_auc: float | None
    train_ap: float | None


def weighted_mean(values: np.ndarray, weight: np.ndarray, mask: np.ndarray) -> float:
    valid = mask & np.isfinite(values) & np.isfinite(weight) & (weight > 0)
    if not np.any(valid):
        return float("nan")
    w = weight[valid]
    return float(np.sum(w * values[valid]) / np.sum(w))


def summarize_daily(rows: list[dict], group_cols: list[str]) -> pd.DataFrame:
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


def metric_row(
    date_str: str,
    symbol: str,
    split: str,
    model_name: str,
    horizon: int,
    keep_fraction: float,
    pnl: np.ndarray,
    weight: np.ndarray,
    keep: np.ndarray,
) -> dict:
    valid = np.isfinite(pnl) & np.isfinite(weight) & (weight > 0)
    kept = valid & keep
    filtered = valid & ~keep
    return {
        "date": date_str,
        "symbol": symbol,
        "split": split,
        "model": model_name,
        "horizon_s": horizon,
        "keep_fraction": keep_fraction,
        "pnl_all": weighted_mean(pnl, weight, valid),
        "pnl_kept": weighted_mean(pnl, weight, kept),
        "pnl_filtered": weighted_mean(pnl, weight, filtered),
        "all_clipped_turnover": float(np.sum(weight[valid])),
        "kept_clipped_turnover": float(np.sum(weight[kept])),
        "filtered_clipped_turnover": float(np.sum(weight[filtered])),
        "kept_trade_count": int(np.sum(kept)),
        "filtered_trade_count": int(np.sum(filtered)),
    }


def read_day_features(
    paths: DataPaths,
    current,
    symbol: str,
    trade_stride: int,
) -> tuple[np.ndarray, np.ndarray, dict[int, np.ndarray]]:
    start_us = date_to_us(current)
    end_us = date_to_us(current + timedelta(days=1))
    trades = stride_trades(load_trades(paths, symbol, start_us, end_us), trade_stride)
    if trades.is_empty():
        return np.empty((0, len(FEATURE_NAMES)), dtype=np.float32), np.empty(0, dtype=np.float32), {}
    bbo = load_bbo(paths, symbol, start_us - MAX_LOOKBACK_US, end_us + max(HORIZONS) * 1_000_000 + 1_000_000)
    liq_binance = load_liq_with_lookback(paths.liq_binance(symbol), start_us, end_us, MAX_LOOKBACK_US)
    liq_bybit = load_liq_with_lookback(paths.liq_bybit(symbol), start_us, end_us, MAX_LOOKBACK_US)
    return build_features(symbol, trades, bbo, liq_binance, liq_bybit)


def collect_train_data(
    paths: DataPaths,
    train_start: str,
    train_end: str,
    symbols: tuple[str, ...],
    train_stride: int,
) -> tuple[dict[int, list[np.ndarray]], dict[int, list[np.ndarray]], dict[int, list[np.ndarray]], int]:
    x_by_horizon: dict[int, list[np.ndarray]] = defaultdict(list)
    y_by_horizon: dict[int, list[np.ndarray]] = defaultdict(list)
    w_by_horizon: dict[int, list[np.ndarray]] = defaultdict(list)
    days = 0

    for current in iter_dates(parse_date(train_start), parse_date(train_end)):
        days += 1
        date_str = current.isoformat()
        for symbol in symbols:
            print(f"[ml-full] train sample {date_str} {symbol}", flush=True)
            x, weight, pnl_by_horizon = read_day_features(paths, current, symbol, train_stride)
            if len(x) == 0:
                continue
            valid_base = np.isfinite(weight) & (weight > 0)
            for horizon, pnl in pnl_by_horizon.items():
                valid = valid_base & np.isfinite(pnl)
                if not np.any(valid):
                    continue
                x_by_horizon[horizon].append(x[valid])
                y_by_horizon[horizon].append(pnl[valid].astype(np.float32, copy=False))
                w_by_horizon[horizon].append(weight[valid].astype(np.float32, copy=False))

    return x_by_horizon, y_by_horizon, w_by_horizon, days


def predict_scores(model_name: str, model: object, x: np.ndarray) -> np.ndarray:
    if model_name == "hgb_classifier":
        return model.predict_proba(x)[:, 1]
    return model.predict(x)


def safe_auc(y_true: np.ndarray, score: np.ndarray) -> tuple[float | None, float | None]:
    target = y_true > 0
    if len(np.unique(target)) < 2:
        return None, None
    return float(roc_auc_score(target, score)), float(average_precision_score(target, score))


def train_models(
    x_by_horizon: dict[int, list[np.ndarray]],
    y_by_horizon: dict[int, list[np.ndarray]],
    w_by_horizon: dict[int, list[np.ndarray]],
    output_dir: Path,
) -> tuple[list[TrainedModel], pd.DataFrame, pd.DataFrame]:
    trained: list[TrainedModel] = []
    threshold_rows = []
    importance_rows = []
    model_dir = output_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    for horizon in HORIZONS:
        x = np.vstack(x_by_horizon[horizon])
        y = np.concatenate(y_by_horizon[horizon])
        w = np.concatenate(w_by_horizon[horizon])
        sample_weight = np.minimum(w, 100_000.0)

        model_specs = [
            (
                "hgb_regressor_clip100",
                HistGradientBoostingRegressor(
                    max_iter=180,
                    learning_rate=0.05,
                    max_leaf_nodes=31,
                    l2_regularization=1.0,
                    random_state=100 + horizon,
                ),
                np.clip(y, -100.0, 100.0),
            ),
            (
                "hgb_classifier",
                HistGradientBoostingClassifier(
                    max_iter=180,
                    learning_rate=0.05,
                    max_leaf_nodes=31,
                    l2_regularization=1.0,
                    random_state=200 + horizon,
                ),
                (y > 0).astype(np.int8),
            ),
        ]

        for model_name, model, target in model_specs:
            print(f"[ml-full] fit {model_name} horizon={horizon} rows={len(x):,}", flush=True)
            model.fit(x, target, sample_weight=sample_weight)
            score = predict_scores(model_name, model, x)
            auc, ap = safe_auc(y, score)
            thresholds = {fraction: float(np.quantile(score[np.isfinite(score)], 1.0 - fraction)) for fraction in KEEP_FRACTIONS}
            trained.append(TrainedModel(model_name, horizon, model, thresholds, auc, ap))

            for fraction, threshold in thresholds.items():
                keep = score > threshold
                threshold_rows.append(
                    {
                        "model": model_name,
                        "horizon_s": horizon,
                        "keep_fraction": fraction,
                        "threshold": threshold,
                        "train_rows": int(len(x)),
                        "train_auc_positive_pnl": auc,
                        "train_average_precision": ap,
                        "train_pnl_all": weighted_mean(y, w, np.ones(len(y), dtype=bool)),
                        "train_pnl_kept": weighted_mean(y, w, keep),
                        "train_score": weighted_mean(y, w, keep) - weighted_mean(y, w, np.ones(len(y), dtype=bool)),
                        "train_kept_turnover": float(np.sum(w[keep])),
                    }
                )

            rng = np.random.default_rng(50_000 + horizon)
            importance_n = min(len(x), 100_000)
            idx = rng.choice(len(x), size=importance_n, replace=False)
            scoring = "average_precision" if model_name == "hgb_classifier" else "neg_mean_squared_error"
            result = permutation_importance(
                model,
                x[idx],
                target[idx],
                sample_weight=sample_weight[idx],
                n_repeats=3,
                random_state=60_000 + horizon,
                scoring=scoring,
            )
            for feature, mean, std in zip(FEATURE_NAMES, result.importances_mean, result.importances_std):
                importance_rows.append(
                    {
                        "model": model_name,
                        "horizon_s": horizon,
                        "feature": feature,
                        "importance_mean": float(mean),
                        "importance_std": float(std),
                    }
                )

            with (model_dir / f"{model_name}_{horizon}.pkl").open("wb") as f:
                pickle.dump({"model": model, "thresholds": thresholds, "features": FEATURE_NAMES}, f)

    return trained, pd.DataFrame(threshold_rows), pd.DataFrame(importance_rows)


def evaluate_full_split(
    paths: DataPaths,
    trained: list[TrainedModel],
    split_name: str,
    start: str,
    end: str,
    symbols: tuple[str, ...],
    output_dir: Path,
) -> pd.DataFrame:
    rows = []
    grouped: dict[int, list[TrainedModel]] = defaultdict(list)
    for item in trained:
        grouped[item.horizon].append(item)

    for current in iter_dates(parse_date(start), parse_date(end)):
        date_str = current.isoformat()
        for symbol in symbols:
            print(f"[ml-full] evaluate {split_name} {date_str} {symbol}", flush=True)
            x, weight, pnl_by_horizon = read_day_features(paths, current, symbol, trade_stride=1)
            if len(x) == 0:
                continue
            for horizon, pnl in pnl_by_horizon.items():
                for item in grouped[horizon]:
                    score = predict_scores(item.model_name, item.model, x)
                    for keep_fraction, threshold in item.thresholds.items():
                        keep = score > threshold
                        rows.append(
                            metric_row(
                                date_str,
                                symbol,
                                split_name,
                                item.model_name,
                                horizon,
                                keep_fraction,
                                pnl,
                                weight,
                                keep,
                            )
                        )

    daily = pd.DataFrame(rows)
    daily.to_csv(output_dir / f"ml_{split_name}_daily_metrics.csv", index=False)
    summary = summarize_daily(daily.to_dict("records"), ["split", "model", "horizon_s", "keep_fraction"])
    summary.to_csv(output_dir / f"ml_{split_name}_summary.csv", index=False)
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
) -> None:
    paths = DataPaths.from_root(data_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    x_by_horizon, y_by_horizon, w_by_horizon, train_days = collect_train_data(
        paths, train_start, train_end, symbols, train_stride
    )
    trained, threshold_summary, importance = train_models(x_by_horizon, y_by_horizon, w_by_horizon, output_dir)
    threshold_summary.to_csv(output_dir / "ml_train_thresholds.csv", index=False)
    importance.sort_values(["model", "horizon_s", "importance_mean"], ascending=[True, True, False]).to_csv(
        output_dir / "ml_permutation_importance.csv", index=False
    )

    validation_summary = evaluate_full_split(
        paths, trained, "validation", validation_start, validation_end, symbols, output_dir
    )
    best = validation_summary[validation_summary["constraint_ok"]].sort_values(
        ["model", "horizon_s", "score"], ascending=[True, True, False]
    )
    best.groupby(["model", "horizon_s"]).head(5).to_csv(output_dir / "ml_validation_best.csv", index=False)

    (output_dir / "ml_full_config.json").write_text(
        json.dumps(
            {
                "data_root": str(paths.data),
                "train_start": train_start,
                "train_end": train_end,
                "validation_start": validation_start,
                "validation_end": validation_end,
                "symbols": symbols,
                "train_stride": train_stride,
                "train_days": train_days,
                "keep_fractions": KEEP_FRACTIONS,
                "features": FEATURE_NAMES,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\nBest validation rows", flush=True)
    print(best.groupby(["model", "horizon_s"]).head(5).to_string(index=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-dir", default="outputs_ml_full_research")
    parser.add_argument("--train-start", default="2025-12-01")
    parser.add_argument("--train-end", default="2026-02-01")
    parser.add_argument("--validation-start", default="2026-02-01")
    parser.add_argument("--validation-end", default="2026-03-01")
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS), choices=list(SYMBOLS))
    parser.add_argument("--train-stride", type=int, default=1000)
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
    )


if __name__ == "__main__":
    main()
