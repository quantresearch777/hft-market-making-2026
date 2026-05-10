from __future__ import annotations

import csv
import json
from pathlib import Path

from .orders import Fill


STRATEGY_NOTES = {
    "fixed_spread": {
        "idea": "Baseline market maker around mid price with fixed half-spread and simple inventory skew.",
        "strengths": "Very easy to explain; useful benchmark; few parameters.",
        "weaknesses": "Does not read short-term order-book pressure; can overtrade in adverse flow.",
    },
    "avellaneda_stoikov_mid": {
        "idea": "Classical Avellaneda-Stoikov reservation price and optimal spread using mid price as fair value.",
        "strengths": "Clear inventory/risk logic; standard academic baseline.",
        "weaknesses": "Fair value ignores imbalance; parameters are sensitive.",
    },
    "avellaneda_stoikov_microprice": {
        "idea": "Avellaneda-Stoikov with microprice fair value from top-of-book imbalance.",
        "strengths": "Keeps AS risk control while reacting to near-term book pressure.",
        "weaknesses": "Only uses level 1; microprice can be noisy.",
    },
    "as_obi_hybrid": {
        "idea": "Avellaneda-Stoikov risk engine with multi-level OBI fair-value adjustment.",
        "strengths": "Combines inventory control with an explainable L2 alpha.",
        "weaknesses": "More parameters than pure AS; alpha can fight inventory skew if over-tuned.",
    },
    "as_ewma_vol": {
        "idea": "Avellaneda-Stoikov variant that widens risk/spread when recent realized volatility rises.",
        "strengths": "More defensive in noisy regimes; still easy to describe.",
        "weaknesses": "May miss profitable fills when volatility estimate is too reactive.",
    },
}


def write_outputs(output_dir: Path, records: list[dict], fills: list[Fill], metrics: dict, config: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "figures").mkdir(exist_ok=True)
    _write_json(output_dir / "metrics.json", metrics)
    _write_json(output_dir / "config_used.json", config)
    _write_records_csv(output_dir / "records.csv", records)
    _write_fills_csv(output_dir / "fills.csv", fills)
    _write_metrics_csv(output_dir / "metrics.csv", metrics)
    _write_svg_line(output_dir / "figures" / "equity.svg", records, "equity", "Equity")
    _write_svg_line(output_dir / "figures" / "inventory.svg", records, "position", "Inventory")
    _write_report(output_dir / "REPORT.md", records, fills, metrics, config)


def write_comparison_outputs(output_dir: Path, results: dict[str, tuple[list[dict], dict]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(exist_ok=True)

    metrics_rows = sorted(
        [metrics for _, metrics in results.values()],
        key=lambda row: float(row.get("final_pnl", 0.0)),
        reverse=True,
    )
    _write_comparison_csv(output_dir / "comparison.csv", metrics_rows)
    _write_bar_svg(figure_dir / "final_pnl.svg", metrics_rows, "final_pnl", "Final PnL")
    _write_bar_svg(figure_dir / "max_drawdown.svg", metrics_rows, "max_drawdown", "Max Drawdown")
    _write_bar_svg(figure_dir / "turnover.svg", metrics_rows, "turnover", "Turnover")
    _write_bar_svg(figure_dir / "num_fills.svg", metrics_rows, "num_fills", "Number of Fills")
    _write_bar_svg(figure_dir / "mean_abs_inventory.svg", metrics_rows, "mean_abs_inventory", "Mean Abs Inventory")
    _write_multi_line_svg(
        figure_dir / "equity_comparison.svg",
        {name: records for name, (records, _) in results.items()},
        "equity",
        "Equity Curves",
    )
    _write_multi_line_svg(
        figure_dir / "inventory_comparison.svg",
        {name: records for name, (records, _) in results.items()},
        "position",
        "Inventory Curves",
    )
    _write_comparison_report(output_dir / "comparison.md", metrics_rows)


def _write_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def _write_records_csv(path: Path, records: list[dict]) -> None:
    if not records:
        path.write_text("", encoding="utf-8")
        return
    fields = list(records[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def _write_fills_csv(path: Path, fills: list[Fill]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ts_ns", "order_id", "side", "price", "qty", "maker"])
        writer.writeheader()
        for fill in fills:
            writer.writerow(
                {
                    "ts_ns": fill.ts_ns,
                    "order_id": fill.order_id,
                    "side": fill.side.value,
                    "price": fill.price,
                    "qty": fill.qty,
                    "maker": fill.maker,
                }
            )


def _write_metrics_csv(path: Path, metrics: dict) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for key, value in metrics.items():
            writer.writerow([key, value])


def _write_comparison_csv(path: Path, rows: list[dict]) -> None:
    fields = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_svg_line(path: Path, records: list[dict], field: str, title: str) -> None:
    width = 900
    height = 320
    margin = 40
    values = [float(r[field]) for r in records if r.get(field) is not None]
    if len(values) < 2:
        path.write_text(f"<svg width='{width}' height='{height}'><text x='20' y='40'>{title}: no data</text></svg>")
        return
    lo = min(values)
    hi = max(values)
    if hi == lo:
        hi = lo + 1.0
    points = []
    for i, value in enumerate(values):
        x = margin + i * (width - 2 * margin) / (len(values) - 1)
        y = height - margin - (value - lo) * (height - 2 * margin) / (hi - lo)
        points.append(f"{x:.2f},{y:.2f}")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="white"/>
  <text x="{margin}" y="24" font-family="monospace" font-size="16">{title}</text>
  <line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="#999"/>
  <line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height-margin}" stroke="#999"/>
  <polyline points="{' '.join(points)}" fill="none" stroke="#1f77b4" stroke-width="2"/>
  <text x="{margin}" y="{height-10}" font-family="monospace" font-size="11">min={lo:.8f} max={hi:.8f}</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def _write_bar_svg(path: Path, rows: list[dict], field: str, title: str) -> None:
    width = 960
    height = 360
    margin = 55
    values = [(str(row.get("strategy", "unknown")), float(row.get(field, 0.0))) for row in rows]
    if not values:
        path.write_text(f"<svg width='{width}' height='{height}'><text x='20' y='40'>{title}: no data</text></svg>")
        return
    lo = min(0.0, min(v for _, v in values))
    hi = max(0.0, max(v for _, v in values))
    if hi == lo:
        hi = lo + 1.0
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin
    bar_gap = 18
    bar_w = max(20, (plot_w - bar_gap * (len(values) - 1)) / len(values))

    def y(value: float) -> float:
        return margin + (hi - value) * plot_h / (hi - lo)

    zero_y = y(0.0)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{margin}" y="26" font-family="monospace" font-size="16">{title}</text>',
        f'<line x1="{margin}" y1="{zero_y:.2f}" x2="{width-margin}" y2="{zero_y:.2f}" stroke="#999"/>',
    ]
    for i, (name, value) in enumerate(values):
        x = margin + i * (bar_w + bar_gap)
        y_val = y(value)
        top = min(y_val, zero_y)
        h = abs(zero_y - y_val)
        color = "#2ca02c" if value >= 0 else "#d62728"
        label = _short_label(name)
        parts.extend(
            [
                f'<rect x="{x:.2f}" y="{top:.2f}" width="{bar_w:.2f}" height="{h:.2f}" fill="{color}" opacity="0.82"/>',
                f'<text x="{x:.2f}" y="{height-30}" font-family="monospace" font-size="10" transform="rotate(25 {x:.2f},{height-30})">{label}</text>',
                f'<text x="{x:.2f}" y="{top-5:.2f}" font-family="monospace" font-size="10">{value:.4g}</text>',
            ]
        )
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def _write_multi_line_svg(path: Path, series: dict[str, list[dict]], field: str, title: str) -> None:
    width = 960
    height = 380
    margin = 55
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
    values_by_name: dict[str, list[float]] = {}
    for name, records in series.items():
        values = [float(r[field]) for r in records if r.get(field) is not None]
        if len(values) >= 2:
            values_by_name[name] = values
    if not values_by_name:
        path.write_text(f"<svg width='{width}' height='{height}'><text x='20' y='40'>{title}: no data</text></svg>")
        return

    all_values = [v for values in values_by_name.values() for v in values]
    lo = min(all_values)
    hi = max(all_values)
    if hi == lo:
        hi = lo + 1.0
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    def point(values: list[float], i: int, value: float) -> str:
        x = margin + i * plot_w / (len(values) - 1)
        y = height - margin - (value - lo) * plot_h / (hi - lo)
        return f"{x:.2f},{y:.2f}"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{margin}" y="26" font-family="monospace" font-size="16">{title}</text>',
        f'<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="#999"/>',
        f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height-margin}" stroke="#999"/>',
    ]
    for idx, (name, values) in enumerate(values_by_name.items()):
        color = colors[idx % len(colors)]
        points = " ".join(point(values, i, value) for i, value in enumerate(values))
        legend_y = margin + idx * 18
        parts.extend(
            [
                f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>',
                f'<line x1="{width-290}" y1="{legend_y}" x2="{width-265}" y2="{legend_y}" stroke="{color}" stroke-width="3"/>',
                f'<text x="{width-260}" y="{legend_y+4}" font-family="monospace" font-size="11">{name}</text>',
            ]
        )
    parts.append(f'<text x="{margin}" y="{height-10}" font-family="monospace" font-size="11">min={lo:.6g} max={hi:.6g}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def _write_report(path: Path, records: list[dict], fills: list[Fill], metrics: dict, config: dict) -> None:
    strategy = metrics.get("strategy", config.get("strategy", {}).get("name", "unknown"))
    lines = [
        "# HFT Backtest Report",
        "",
        f"Strategy: `{strategy}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in metrics.items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Assumptions",
            "",
            "- Market-data replay: our simulated orders do not change the historical book.",
            "- Maker-style fills at our limit price.",
            "- Trade crossing is the preferred fill signal when trade events are enabled.",
            "- Queue position and feed latency are documented roadmap items, not hidden assumptions.",
            "",
            "## Output Files",
            "",
            "- `metrics.json` / `metrics.csv`: summary metrics.",
            "- `records.csv`: sampled state over time.",
            "- `fills.csv`: simulated fills.",
            "- `figures/equity.svg`: equity curve.",
            "- `figures/inventory.svg`: inventory curve.",
            "",
            f"Records: {len(records)}",
            f"Fills: {len(fills)}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_comparison_report(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("# Strategy Comparison Report\n\nNo runs available.\n", encoding="utf-8")
        return
    sorted_by_pnl = sorted(rows, key=lambda row: float(row.get("final_pnl", 0.0)), reverse=True)
    best = sorted_by_pnl[0]
    lowest_inventory = min(rows, key=lambda row: float(row.get("mean_abs_inventory", 0.0)))
    lowest_drawdown = max(rows, key=lambda row: float(row.get("max_drawdown", 0.0)))
    lines = [
        "# Strategy Comparison Report",
        "",
        "This report compares the available market-making strategies on the same configured market-data sample.",
        "Rows are sorted by final PnL descending. Final PnL is useful for ranking, but drawdown, turnover, fills and inventory must be read together.",
        "",
        "## Summary Table",
        "",
        "| Strategy | Final PnL | Max Drawdown | Turnover | Fills | Mean Abs Inventory | PnL / Turnover |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {strategy} | {pnl:.8f} | {dd:.8f} | {turnover:.4f} | {fills} | {inv:.4f} | {ppt:.8g} |".format(
                strategy=row.get("strategy", "unknown"),
                pnl=float(row.get("final_pnl", 0.0)),
                dd=float(row.get("max_drawdown", 0.0)),
                turnover=float(row.get("turnover", 0.0)),
                fills=int(row.get("num_fills", 0)),
                inv=float(row.get("mean_abs_inventory", 0.0)),
                ppt=float(row.get("pnl_per_turnover", 0.0)),
            )
        )
    lines.extend(
        [
            "",
            "## Method Notes",
            "",
            "| Strategy | Core Idea | Strengths | Weaknesses |",
            "|---|---|---|---|",
        ]
    )
    for row in sorted_by_pnl:
        strategy = str(row.get("strategy", "unknown"))
        note = STRATEGY_NOTES.get(
            strategy,
            {
                "idea": "No method note registered.",
                "strengths": "No method note registered.",
                "weaknesses": "No method note registered.",
            },
        )
        lines.append(
            f"| `{strategy}` | {note['idea']} | {note['strengths']} | {note['weaknesses']} |"
        )
    lines.extend(
        [
            "",
            "## Visual Outputs",
            "",
            "- [Final PnL](figures/final_pnl.svg)",
            "- [Max Drawdown](figures/max_drawdown.svg)",
            "- [Turnover](figures/turnover.svg)",
            "- [Number of Fills](figures/num_fills.svg)",
            "- [Mean Abs Inventory](figures/mean_abs_inventory.svg)",
            "- [Equity Curves](figures/equity_comparison.svg)",
            "- [Inventory Curves](figures/inventory_comparison.svg)",
            "",
            "## Automatic Observations",
            "",
            f"- Best final PnL in this run: `{best.get('strategy')}`.",
            f"- Lowest mean absolute inventory: `{lowest_inventory.get('strategy')}`.",
            f"- Smallest drawdown magnitude: `{lowest_drawdown.get('strategy')}`.",
            "- These are sample-run observations, not proof of robust profitability.",
            "",
            "## Interpretation Notes",
            "",
            "- This tournament intentionally compares one family of strategies: two-sided passive market making on the same L2/trade replay.",
            "- The strategies differ in fair value, inventory/risk adjustment and spread adaptation, not in data sample or fill model.",
            "- A high final PnL with very high turnover or inventory is less attractive than a slightly lower PnL with stable risk.",
            "- Full conclusions should be made on fixed time windows, walk-forward splits and multiple parameter settings.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _short_label(name: str) -> str:
    replacements = {
        "avellaneda_stoikov_microprice": "AS micro",
        "avellaneda_stoikov_mid": "AS mid",
        "as_obi_hybrid": "AS+OBI",
        "as_ewma_vol": "AS vol",
        "fixed_spread": "fixed",
    }
    return replacements.get(name, name[:14])
