from __future__ import annotations

from .orders import Fill


def compute_metrics(records: list[dict], fills: list[Fill]) -> dict:
    if not records:
        return {
            "final_pnl": 0.0,
            "max_drawdown": 0.0,
            "turnover": 0.0,
            "num_fills": 0,
            "mean_abs_inventory": 0.0,
            "max_abs_inventory": 0.0,
            "pnl_per_turnover": 0.0,
        }

    equities = [_safe_float(r.get("equity")) for r in records]
    positions = [_safe_float(r.get("position")) for r in records]
    final_pnl = equities[-1] - equities[0]
    turnover = _safe_float(records[-1].get("turnover"))
    peak = equities[0]
    max_drawdown = 0.0
    for equity in equities:
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    mean_abs_inventory = sum(abs(x) for x in positions) / len(positions)
    max_abs_inventory = max(abs(x) for x in positions)
    return {
        "final_pnl": final_pnl,
        "max_drawdown": max_drawdown,
        "turnover": turnover,
        "num_fills": len(fills),
        "mean_abs_inventory": mean_abs_inventory,
        "max_abs_inventory": max_abs_inventory,
        "pnl_per_turnover": final_pnl / turnover if turnover else 0.0,
        "final_position": positions[-1],
        "final_equity": equities[-1],
        "fees_paid": _safe_float(records[-1].get("fees_paid")),
    }


def _safe_float(value) -> float:
    if value is None:
        return 0.0
    return float(value)

