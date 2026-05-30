# Market Making Research Notes For Task 2

This note summarizes public research, open-source tools, Kaggle-style competitions and practical industry lessons relevant to Task 2.

## Executive Summary

For this assignment, the best practical path is not a full C++ event-driven backtester yet. The task is a per-trade maker markout filter:

```text
Binance trades + BBO + liquidations -> classify each trade as keep/filter -> evaluate post-fill markout PnL and turnover
```

The strongest public consensus is:

- Market making PnL is dominated by adverse selection and post-fill drift, not just spread capture.
- Fill probability alone is misleading because easy fills are often toxic fills.
- Order-flow imbalance and cross-market signals can predict short-horizon returns, but the edge decays quickly.
- Robustness matters more than an overfit high-complexity model.
- For large parquet data, Polars + NumPy is a strong baseline because Polars is Rust-native under the hood.
- C++/Rust becomes important later for live/event-driven LOB replay, queue simulation, or very low-latency production logic.

## Relevant Academic Directions

### 1. Avellaneda-Stoikov Style Market Making

Classic reference:

- Avellaneda and Stoikov, "High-frequency trading in a limit order book"  
  https://www.researchgate.net/publication/24086205_High_Frequency_Trading_in_a_Limit_Order_Book

Core idea:

- Quote around a reservation price.
- Account for inventory risk.
- Wider/narrower spreads depend on volatility, risk aversion and fill intensity.

Relevance:

- Useful for entrance-exam style backtester and inventory-aware quoting.
- Less directly useful for Task 2 because Task 2 already gives trades and asks for per-trade filtering.

Task 2 takeaway:

```text
Use Avellaneda-Stoikov as background, not as the main implementation.
Task 2 is about conditional trade quality / markout filtering.
```

### 2. Negative Drift And Adverse Selection Around Fills

References:

- The Negative Drift of a Limit Order Fill  
  https://arxiv.org/abs/2407.16527
- The Market Maker's Dilemma: Navigating the Fill Probability vs. Post-Fill Returns Trade-Off  
  https://arxiv.org/abs/2502.18625

Core idea:

- Limit order fills are not random free spread capture.
- A maker fill often happens exactly when price moves against the maker.
- Higher fill probability can mean worse post-fill returns.
- A good maker model should ask: "If I get filled here, what is the expected markout?"

Relevance:

- This is central to Task 2.
- The task's target PnL formula is a direct maker markout measure.
- The goal is to filter toxic maker fills.

Task 2 takeaway:

```text
Optimize PnL_kept vs PnL_all, not fill count.
Avoid toxic fills suggested by recent liquidation / stress pressure.
```

### 3. Order Flow Imbalance And Cross-Impact

References:

- Cross-Impact of Order Flow Imbalance in Equity Markets  
  https://arxiv.org/abs/2112.13213
- Price Impact of Order Book Events, Cont et al.  
  https://academic.oup.com/jfec/article/12/1/47/816163

Core idea:

- Order flow imbalance explains short-term price impact.
- Cross-asset or cross-market flow can improve forecasting.
- Predictability is strongest at short horizons and decays quickly.

Relevance:

- Our Task 2 signal uses cross-source pressure:

```text
Binance liquidations + Bybit liquidations shifted by +200ms
```

Task 2 takeaway:

```text
Use recent cross-source liquidation pressure as a short-horizon predictor.
Keep the rule simple because cross-impact signals are noisy and short-lived.
```

### 4. Queue Position And Fill Models

References:

- Queue-reactive models for limit order books  
  https://arxiv.org/abs/1312.0563
- HftBacktest queue models  
  https://hftbacktest.readthedocs.io/

Core idea:

- Real maker execution depends on queue position, queue depletion and cancellation behavior.
- BBO-only data cannot identify exact queue position.
- L3/order-by-order data is better for realistic fill modeling.

Relevance:

- Task 2 does not ask us to simulate our own orders.
- It assumes trades can be evaluated as maker fills through markout.
- Therefore queue modeling is a future enhancement, not the main deliverable.

Task 2 takeaway:

```text
Do not build a full queue simulator now.
Mention BBO-only/queue-position limitations in report.
```

### 5. ML For Limit Order Books

References:

- DeepLOB  
  https://arxiv.org/abs/1808.03668
- Deep Order Flow Imbalance  
  https://arxiv.org/abs/2112.01219

Core idea:

- Deep learning can extract short-horizon alpha from LOB sequences.
- Good models often use multiple horizons, normalization and temporal validation.
- However, deep models are easy to overfit and expensive to run.

Relevance:

- Task 2 allows a simple ML model, but a strong heuristic baseline is acceptable.
- A next version could use logistic regression / LightGBM over features:

```text
liquidation pressure
BBO spread
top imbalance
recent trade imbalance
recent returns
volatility
symbol
hour
```

Task 2 takeaway:

```text
Start with a robust heuristic baseline.
Then add ML only if we can validate temporally and preserve turnover.
```

## Kaggle-Style Lessons

Relevant public competitions:

- Optiver Trading at the Close  
  https://www.kaggle.com/competitions/optiver-trading-at-the-close
- Optiver Realized Volatility Prediction  
  https://www.kaggle.com/competitions/optiver-realized-volatility-prediction
- Jane Street Real-Time Market Data Forecasting  
  https://www.kaggle.com/competitions/jane-street-real-time-market-data-forecasting

Common lessons:

- Temporal validation is critical.
- Feature leakage is easy in market data.
- Ensembles and gradient boosting work well in tabular market tasks.
- The evaluation metric matters more than generic classification accuracy.
- Robustness by date/regime matters more than one high leaderboard score.

Task 2 takeaway:

```text
Do not evaluate by accuracy.
Evaluate directly by Score, PnL_kept, PnL_filtered and turnover per day.
Use train/validation by time.
```

## Open-Source Tools Worth Knowing

### HftBacktest

Link:

- https://github.com/nkaz001/hftbacktest
- https://hftbacktest.readthedocs.io/

Why relevant:

- Python framework with Rust acceleration.
- Designed for high-frequency market making/backtesting.
- Includes queue-position and latency modeling.

Use now?

- Not necessary for Task 2.
- Useful later if the course moves toward realistic maker order simulation.

### NautilusTrader

Link:

- https://github.com/nautechsystems/nautilus_trader
- https://nautilustrader.io/docs/

Why relevant:

- Large production-grade Python/Rust trading/backtesting framework.
- Multi-asset, event-driven architecture.

Use now?

- Too heavy for Task 2.
- Good reference for future architecture if the project becomes a full trading system.

### ABIDES

Link:

- https://github.com/abides-sim/abides

Why relevant:

- Agent-based discrete-event market simulator.
- Useful for research with synthetic agents and order books.

Use now?

- Not needed for Task 2.
- More relevant for market simulation research than this per-trade signal task.

### Hummingbot

Link:

- https://github.com/hummingbot/hummingbot
- https://hummingbot.org/

Why relevant:

- Open-source crypto market-making framework.
- Good for practical exchange connectors and simple maker strategies.

Use now?

- Not needed for offline markout scoring.
- Useful context for crypto market-making workflows.

## Industry Reality

Leading public names in electronic market making include:

- Citadel Securities
- Jane Street
- Optiver
- IMC
- Jump Trading
- DRW / Cumberland
- XTX Markets

Publicly visible best practices:

- Extremely strong data engineering.
- Low-latency systems where needed.
- Heavy emphasis on risk, inventory, adverse selection and execution quality.
- Careful research validation by time/regime/instrument.
- Production code often uses C++/Rust/Java for low-latency components, but research often starts in Python.

What is not public:

- Actual proprietary alpha models.
- Detailed queue/latency/fill models.
- Exchange-specific production logic.
- Real risk limits and hedging logic.

Task 2 takeaway:

```text
The public best practice is: research in Python/Polars, validate by markout, keep the signal robust, and only move performance-critical pieces to Rust/C++ when the bottleneck is proven.
```

## Recommended Strategy For Our Task 2

### Current baseline

Use a side-aware liquidation pressure rule:

```text
pressure_i = trade_side_i * (signed_binance_liq_1s + signed_bybit_liq_1s_shifted_200ms)
filter_i = 1 if pressure_i <= threshold else 0
```

Why:

- Simple.
- Uses the key unique dataset feature: liquidation events.
- Respects the Bybit delay.
- Optimizes maker markout quality.
- Already showed strong train/validation metrics in Task 1 calibration.

### Evaluation

Use a lightweight markout evaluator:

```text
for each Binance trade:
  future_mid = BBO mid at t + horizon
  maker_pnl_bps = -side * (future_mid - trade_price) / trade_price * 10000 + rebate
  classify keep/filter
  compute PnL_all, PnL_kept, PnL_filtered, Score, turnover/day
```

### Compute stack

Use:

```text
Polars for parquet scanning and chunk loading
NumPy for searchsorted / rolling sums / markout arrays
server for full run
```

Avoid for now:

```text
full event replay
C++/Rust rewrite
queue simulator
deep learning model
complex portfolio engine
```

### Next improvement path

After baseline metrics are reproduced:

1. Add features:
   - liquidation pressure windows: 200ms, 1s, 5s, 30s
   - Binance-only vs Bybit-only pressure
   - BBO spread and top imbalance
   - recent trade imbalance
   - recent returns and volatility

2. Train simple ML:
   - logistic regression
   - LightGBM / CatBoost if available
   - objective based on bad markout classification or weighted PnL

3. Calibrate thresholds by horizon:
   - horizon-specific filter thresholds
   - preserve `>= 500k USD/day` turnover
   - avoid overfitting validation

4. Robustness checks:
   - per-symbol metrics
   - per-day metrics
   - worst-day turnover
   - public extra months outside official train/validation

## Final Decision

For Task 2, the best professional answer is:

```text
I implemented a lightweight markout backtester/evaluator in Python using Polars and NumPy.
The baseline classifier uses side-aware cross-exchange liquidation pressure with the required Bybit +200ms delay.
The model is evaluated directly on maker PnL improvement and turnover, not classification accuracy.
This is enough for Task 2 and leaves a clear path to ML or faster Rust/C++ components if later tasks require full event replay or queue simulation.
```

