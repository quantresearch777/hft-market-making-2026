# Technical Documentation

Date: 2026-05-08.

## 1. Project Overview

The goal is to build an explainable Python backtesting engine that replays historical market data and evaluates passive market-making strategies.

The project includes:

- L2 limit order book replay;
- limit order placement and cancellation;
- crossing-based order execution;
- optional partial fills;
- portfolio accounting;
- PnL, inventory and turnover metrics;
- Avellaneda-Stoikov 2008;
- microprice-enhanced Avellaneda-Stoikov;
- simple AS extensions using volatility and order-book imbalance;
- reproducible simulation experiments;
- optional EDA script for checking raw data quality.

The full CMF simulation data is expected at `data/MD/`. A small sample cut from the same data is included in `data/sample/` so the project can be checked without shipping the full raw files.

## 2. Project Layout

```text
configs/                  Strategy and simulation configs
data/MD/                  Full CMF simulation data location
data/sample/              Small cut from the provided CMF simulation data
reports/                  Documentation, EDA and performance reports
scripts/                  Command-line entrypoints
src/cmf_hft_backtester/   Backtester source code
tests/                    Unit tests
```

The `data/MD/` folder can be removed before archiving if the full raw files are too large. The `data/sample/` folder should remain because it is the lightweight sample dataset.

## 3. Backtester Components

The backtester is implemented in `src/cmf_hft_backtester/`.

Main files:

- `order_book.py`: L2 book state, best bid/ask, mid, spread, microprice and imbalance.
- `orders.py`: limit order lifecycle, placement, activation, cancellation and fill state.
- `execution.py`: execution model based on market price crossing order level.
- `portfolio.py`: cash, position, fees/rebates, turnover and mark-to-market equity.
- `simulator.py`: historical replay event loop.
- `metrics.py`: PnL, drawdown, inventory and turnover metrics.
- `strategies/`: market-making strategies, split into one file per strategy plus shared base/factory code.

The strategy sees only current and past market state. The implementation does not use lookahead.

## 4. Execution Model

The assignment assumption is:

```text
Execution occurs when the market price crosses the order level.
```

Implementation:

- buy limit fills when an aggressive sell trade price is less than or equal to our bid;
- sell limit fills when an aggressive buy trade price is greater than or equal to our ask;
- fill price is our own limit price;
- when partial fills are enabled, fill size is capped by the trade quantity.

Book-crossing fallback is also available for datasets without trade prints.

## 5. Accounting And Metrics

On buy:

```text
cash -= price * quantity
position += quantity
turnover += abs(price * quantity)
```

On sell:

```text
cash += price * quantity
position -= quantity
turnover += abs(price * quantity)
```

Equity:

```text
equity = cash + position * mid_price
```

Reported metrics:

- final PnL;
- max drawdown;
- turnover;
- number of fills;
- mean absolute inventory;
- max absolute inventory;
- PnL per turnover;
- final position;
- fees/rebates paid.

## 6. Fees And Rebates Assumption

All submission configs use:

```yaml
market:
  maker_fee_bps: -0.5
```

This is a Binance-style maker rebate assumption of `0.5` basis points, or `0.005%`, on filled notional. It is used as a configurable exchange-fee assumption for the simulation, not as a claim that every venue/account tier has this exact rate.

The sign convention is:

- positive `maker_fee_bps` means a fee paid by the strategy;
- negative `maker_fee_bps` means a rebate received by the strategy.

The accounting formula is implemented in `portfolio.py`:

```text
fee = abs(price * quantity) * maker_fee_bps / 10_000
cash -= fee
fees_paid += fee
```

With `maker_fee_bps = -0.5`, `fee` is negative, so `cash -= fee` increases cash. In reports, negative `fees_paid` means net rebates received.

This is a simplifying venue/rebate assumption used consistently across all compared strategies. It is configurable and should be calibrated for a real venue/account tier in a production setting.

## 7. Strategy Models

### Fixed Spread Baseline

Simple benchmark around mid price:

```text
reservation_price = mid_price - inventory_skew
bid = reservation_price - half_spread
ask = reservation_price + half_spread
```

It is included as a sanity check.

### Avellaneda-Stoikov 2008

The AS model adjusts quotes for inventory risk.

Reservation price:

```text
r = S - q * gamma * sigma^2 * tau
```

Optimal spread:

```text
spread = gamma * sigma^2 * tau + (2 / gamma) * log(1 + gamma / k)
```

Quotes:

```text
bid = r - spread / 2
ask = r + spread / 2
```

Where:

- `S` is fair price;
- `q` is current inventory;
- `gamma` is risk aversion;
- `sigma` is recent volatility;
- `tau` is risk horizon;
- `k` controls order-arrival intensity.

The baseline uses:

```text
S = mid_price
```

### Microprice Enhancement

Microprice uses top-of-book imbalance:

```text
microprice = (best_ask * best_bid_qty + best_bid * best_ask_qty) / (best_bid_qty + best_ask_qty)
```

The enhanced strategy uses:

```text
S = microprice
```

This lets the strategy react to short-term pressure in the displayed book while keeping the AS inventory/risk logic.

### Simple AS Extensions

`as_obi_hybrid` uses multi-level order-book imbalance as a fair-value adjustment.

`as_ewma_vol` becomes more defensive when recent realized volatility increases.

Both are intentionally simple and explainable.

## 8. How To Run

Install dependencies:

```bash
pip install -r requirements.txt
```

Run tests:

```bash
python3 -m unittest discover -s tests
```

Run the included sample dataset:

```bash
python3 scripts/run_backtest.py --config configs/sample.yaml --output-dir outputs/sample_check
```

Run the main CMF-data comparison:

```bash
python3 scripts/run_experiments.py --max-events 100000 --output-dir outputs/experiments
```

Run EDA:

```bash
python3 scripts/run_eda.py --data-dir data/MD --output-dir outputs/eda
```

## 9. Experiment Results

The main comparison uses the same first `100,000` market events for all strategies.

Summary:

| Strategy | Final PnL | Max Drawdown | Turnover | Fills | Mean Abs Inventory | PnL / Turnover |
|---|---:|---:|---:|---:|---:|---:|
| `avellaneda_stoikov_microprice` | `+1.05604632` | `-6.46136665` | `47,685.0473` | `1,627` | `21,461.5782` | `2.2146e-05` |
| `as_obi_hybrid` | `+0.91865362` | `-7.24162391` | `34,107.4944` | `1,154` | `22,106.8293` | `2.6934e-05` |
| `avellaneda_stoikov_mid` | `+0.78733687` | `-6.10987153` | `48,476.6304` | `1,670` | `20,999.0990` | `1.6242e-05` |
| `as_ewma_vol` | `-0.28079305` | `-2.87257005` | `22,313.4571` | `768` | `11,934.7874` | `-1.2584e-05` |
| `fixed_spread` | `-35.54110231` | `-35.87911009` | `290,550.5468` | `9,379` | `27,603.7279` | `-1.2232e-04` |

The detailed performance results are in `reports/performance_results.md`. The report includes a five-strategy comparison on `100,000` CMF events, full-dataset results for the five submission strategies, and a simple-engine full-dataset cross-check for the main microprice strategy.

Interpretation:

- AS microprice has the best final PnL in this sample.
- Microprice improves PnL versus the mid-price AS baseline.
- Fixed spread overtrades and performs much worse.
- `as_ewma_vol` reduces drawdown and average inventory but gives up PnL.

## 10. Assumptions And Limitations

| Area | Assumption Used In Submission |
|---|---|
| Market replay | Historical market-data replay, not a full exchange simulator. |
| Market impact | Simulated orders do not change the historical public book. |
| Order type | Passive limit orders only; IOC/market orders are not modeled. |
| Execution trigger | A buy fills when an aggressive sell crosses our bid; a sell fills when an aggressive buy crosses our ask. |
| Fill price | Filled at our own limit price. |
| Partial fills | Enabled; fill size is capped by the trade amount. |
| Queue position | Not modeled; fills do not account for queue priority ahead of us. |
| Feed latency | Not modeled. The strategy observes replayed events at their historical timestamp. |
| Order latency | Configurable, but set to `order_latency_ns: 0` in all submission configs. |
| Fees/rebates | Binance-style maker rebate assumption: `maker_fee_bps = -0.5`. |
| Calibration | AS parameters are configured, not deeply calibrated from observed fill intensity. |

## 11. Improvement Roadmap

The detailed improvement roadmap is in `reports/improvement_roadmap.md`.

Main next steps:

1. Add queue position models.
2. Calibrate feed and order latency.
3. Run broader parameter sensitivity.
4. Estimate AS parameters from market data.
5. Add walk-forward validation.
6. Add richer L2 fair-value features and PnL attribution.

## 12. Verification

From this folder:

```bash
python3 -m unittest discover -s tests
python3 scripts/run_backtest.py --config configs/sample.yaml --output-dir outputs/sample_check
python3 scripts/run_experiments.py --max-events 100000 --output-dir outputs/experiments
python3 scripts/run_eda.py --data-dir data/MD --output-dir outputs/eda
```

Current local check:

```text
10 unit tests passing
```
