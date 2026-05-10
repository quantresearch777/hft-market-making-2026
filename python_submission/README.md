# CMF HFT Backtester

Standalone Python project for the CMF HFT School entrance assignment.

The project implements a compact historical-replay backtester for passive market making:

- limit order book replay;
- limit order placement and cancellation;
- execution when market trades cross our limit order level;
- optional partial fills;
- PnL, inventory and turnover metrics;
- Avellaneda-Stoikov 2008;
- microprice-enhanced Avellaneda-Stoikov;
- simple volatility and order-book-imbalance extensions;
- reproducible experiment runner.

## Files

```text
configs/                  Strategy and simulation configs
data/MD/                  Full CMF dataset location, can be removed before archiving
data/sample/              Small sample cut from the provided CMF simulation data
reports/                  Reports and requirements checklist
scripts/                  Reproducible CLI commands
src/cmf_hft_backtester/   Python source code
src/cmf_hft_backtester/strategies/
                          Strategy implementations split by file
tests/                    Unit tests
README.md                 Technical overview
```

## Quick Start

From this folder:

```bash
pip install -r requirements.txt
python3 -m unittest discover -s tests
python3 scripts/run_backtest.py --config configs/sample.yaml --output-dir outputs/sample_check
python3 scripts/run_experiments.py --max-events 100000 --output-dir outputs/experiments
```

The full CMF data is expected at:

```text
data/MD/lob.csv
data/MD/trades.csv
```

The `data/MD/` folder can be removed before creating the final submission archive if it is too large. The included `data/sample/lob.csv` and `data/sample/trades.csv` files are a small cut from the provided simulation data, so the project can still be run without the full dataset.

Optional data quality check:

```bash
python3 scripts/run_eda.py --data-dir data/MD --output-dir outputs/eda
```

## Backtester Mechanics

Event loop:

1. Read the next LOB or trade event.
2. Update the L2 order book on book events.
3. Activate pending orders after configured order latency.
4. Match active orders when market price crosses their limit level.
5. Apply fills to the order manager and portfolio.
6. Refresh strategy quotes on the configured quote interval.
7. Record cash, inventory, equity, fills and turnover.

The strategy only sees current and past market data. There is no lookahead.

## Execution Rule

The assignment states:

```text
Execution occurs when the market price crosses the order level.
```

Implementation:

- buy limit fills when an aggressive sell trade price is less than or equal to our bid;
- sell limit fills when an aggressive buy trade price is greater than or equal to our ask;
- fill price is our own limit price;
- partial fills are enabled with `simulation.partial_fills: true`.

## Fees And Rebates

All configs use:

```yaml
maker_fee_bps: -0.5
```

This is a Binance-style maker rebate assumption of `0.5` bps on filled notional. Negative `fees_paid` in outputs means rebates received. It is configurable and should be calibrated for a real venue/account tier before production use.

## Strategies

- `fixed_spread`: simple sanity baseline.
- `avellaneda_stoikov_mid`: Avellaneda-Stoikov 2008 using mid price as fair value.
- `avellaneda_stoikov_microprice`: AS strategy using microprice as fair value.
- `as_obi_hybrid`: AS strategy with multi-level order-book imbalance adjustment.
- `as_ewma_vol`: AS strategy with volatility-aware defensive quoting.

## Main Documents

- `reports/technical_documentation.md`: implementation details, run commands and assumptions.
- `reports/performance_results.md`: strategy comparison and full-dataset result.
- `reports/requirements_checklist.md`: direct mapping to the exam requirements.
- `reports/eda_report.md`: data quality summary.
- `reports/improvement_roadmap.md`: planned improvements and next research steps.
