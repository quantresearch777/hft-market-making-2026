# Assignment Requirements Checklist

This file maps the entrance assignment requirements to this submission package.

## Objective

| Requirement | Status | Where |
|---|---|---|
| Historical replay backtester | Done | `src/cmf_hft_backtester/simulator.py` |
| Strategy performance evaluation | Done | `src/cmf_hft_backtester/metrics.py`, `reports/performance_results.md` |
| Python implementation | Done | `src/cmf_hft_backtester/`, `scripts/` |

## Minimum Requirements

| Requirement | Status | Where |
|---|---|---|
| Limit order book simulation | Done | `src/cmf_hft_backtester/order_book.py` |
| Limit order placement | Done | `src/cmf_hft_backtester/orders.py` |
| Limit order cancellation | Done | `src/cmf_hft_backtester/orders.py` |
| Order execution modeling | Done | `src/cmf_hft_backtester/execution.py` |
| Partial fills optional | Done | `src/cmf_hft_backtester/execution.py`, `simulation.partial_fills` |

## Basic Metrics

| Metric | Status | Where |
|---|---|---|
| PnL | Done | `src/cmf_hft_backtester/portfolio.py`, `src/cmf_hft_backtester/metrics.py` |
| Inventory | Done | `src/cmf_hft_backtester/portfolio.py` |
| Turnover | Done | `src/cmf_hft_backtester/portfolio.py`, `src/cmf_hft_backtester/metrics.py` |

## Strategy Implementation

| Requirement | Status | Where |
|---|---|---|
| Avellaneda-Stoikov 2008 | Done | `src/cmf_hft_backtester/strategies/avellaneda_stoikov_mid.py` |
| Microprice enhancement | Done | `src/cmf_hft_backtester/strategies/as_microprice.py` |
| AS-style practical extensions | Done | `as_obi_hybrid`, `as_ewma_vol` |
| Simulation experiments | Done | `scripts/run_experiments.py`, `reports/performance_results.md` |

## Execution Assumption

Assignment:

```text
Execution occurs when the market price crosses the order level.
```

Implemented in `src/cmf_hft_backtester/execution.py`:

- buy limit fills when an aggressive sell crosses our bid;
- sell limit fills when an aggressive buy crosses our ask;
- fill price is our limit price;
- optional partial fills are capped by trade quantity.

## Deliverables

| Deliverable | Status | Where |
|---|---|---|
| Integrated backtest engine | Done | `src/cmf_hft_backtester/simulator.py` |
| Sample dataset | Done | `data/sample/lob.csv`, `data/sample/trades.csv` |
| Configs | Done | `configs/*.yaml` |
| Performance report | Done | `reports/performance_results.md` |
| Technical documentation | Done | `README.md`, `reports/technical_documentation.md` |
| Strategy source code | Done | `src/cmf_hft_backtester/strategies/` |
| Model description | Done | `reports/technical_documentation.md` |
| Performance results | Done | `reports/performance_results.md` |
| Improvement roadmap | Done | `reports/improvement_roadmap.md` |

## Reproducibility

```bash
python3 -m unittest discover -s tests
python3 scripts/run_backtest.py --config configs/sample.yaml --output-dir outputs/sample_check
python3 scripts/run_experiments.py --max-events 100000 --output-dir outputs/experiments
```
