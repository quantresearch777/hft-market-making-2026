# Improvement Roadmap

This roadmap lists practical next steps for improving the current backtester, execution model and strategy research pipeline.

The current submission intentionally favors clarity and explainability. The next stage should keep the simple Python version as the reference implementation, then add faster research tooling and more advanced strategies around it.

## 1. Queue Position Modeling

Current state:

- queue position is not modeled;
- fills occur when the market trade crosses our order level;
- partial fills are capped by trade quantity, but there is no estimate of how much visible queue is ahead of our order.

Improvement:

- add several queue assumptions: optimistic, conservative and probabilistic;
- estimate the probability of a fill based on displayed quantity at the level;
- compare how PnL changes as queue assumptions become less favorable.

Why it matters:

- market-making backtests are very sensitive to fill probability;
- ignoring queue position can overestimate fills and rebates.

## 2. Latency Modeling

Current state:

- feed latency is not modeled;
- order latency is configurable but set to `order_latency_ns: 0` in the submission configs.

Improvement:

- test nonzero order latency values;
- add feed latency so strategy decisions are based on delayed book/trade information;
- run latency sensitivity experiments.

Why it matters:

- passive market making is vulnerable to adverse selection;
- even small latency can change whether a quote is filled before or after the market moves.

## 3. Parameter Calibration

Current state:

- `gamma`, `k`, volatility window, quote interval and max inventory are configured manually;
- AS parameters are not deeply estimated from observed fill intensity.

Improvement:

- estimate volatility from fixed time windows;
- estimate order-arrival intensity around different quote distances;
- run grid search or walk-forward calibration for `gamma`, `k`, order size and quote interval.

Why it matters:

- Avellaneda-Stoikov is sensitive to these parameters;
- poorly calibrated parameters can produce too much inventory or too little spread.

## 4. Walk-Forward Validation

Current state:

- the report includes a 100k-event comparison and full-dataset results;
- the same parameters are used across the tested period.

Improvement:

- split data into train/validation/test windows;
- tune parameters on one window and evaluate on later unseen windows;
- compare results across different market regimes.

Why it matters:

- a strategy can look good in a short window but fail on the full dataset;
- walk-forward testing reduces overfitting risk.

## 5. Strategy Research Extensions

Current state:

- implemented strategies are intentionally compact and explainable;
- the strongest full-dataset submission strategy is `as_ewma_vol`;
- all full-dataset results are still negative under the current assumptions.

Improvement:

- extend Avellaneda-Stoikov with stronger fair-value signals;
- test GLFT-style quoting as an additional market-making family;
- compare volatility-aware, inventory-aware and imbalance-aware quote control;
- run strategy tournaments on fixed train/validation/test windows.

Why it matters:

- strategy comparison should be done across related passive market-making methods;
- the goal is not to add random strategies, but to compare explainable variants under the same fill model.

Candidate research directions:

- **Multi-level microprice**: extend level-1 microprice using deeper L2 liquidity.
- **Smoothed OBI**: reduce noise in order-book imbalance with rolling or EWMA smoothing.
- **Adaptive AS**: make `gamma`, spread and order size depend on volatility and inventory regime.
- **GLFT-style market making**: compare AS against GLFT quote-depth logic with calibrated parameters.
- **Inventory-aware quoting**: reduce quote size or stop quoting one side when inventory is already large.
- **Volatility filters**: widen spreads or reduce activity in unstable regimes.
- **Toxic-flow / adverse-selection filters**: pause or widen quotes when fills are likely to be followed by unfavorable price moves.

## 6. GLFT Research Track

Current state:

- GLFT is not part of the main submission implementation;
- it is a useful future comparison because it is another well-known market-making framework.

Improvement:

- implement a compact GLFT strategy in the same strategy interface;
- calibrate quote depths from observed volatility and fill intensity;
- compare GLFT against AS mid, AS microprice, AS OBI and AS EWMA;
- keep the implementation explainable, with parameters documented in config files.

Why it matters:

- GLFT can provide a different way to convert volatility, inventory and fill intensity into bid/ask depths;
- it gives a natural benchmark beyond AS while still staying inside passive market making.

## 7. Toxic Flow And Adverse Selection Research

Current state:

- the current submission reports aggregate PnL, turnover, fills and inventory;
- it does not yet measure whether fills are followed by adverse price moves.

Improvement:

- calculate short-horizon markout after every fill;
- separate spread capture, rebate contribution and inventory mark-to-market loss;
- measure whether buy fills are followed by mid-price declines and sell fills by mid-price increases;
- test VPIN-like volume imbalance features;
- test trade-flow imbalance and aggressive buy/sell pressure;
- widen spreads or pause quoting when toxicity is high;
- compare toxicity filters on train/validation/test windows.

Why it matters:

- market makers often lose money not because they fail to earn spread, but because they are filled by informed or toxic flow;
- toxicity metrics help decide when not to provide liquidity.

## 8. ML And Regime Detection Research

Current state:

- the submission does not use ML;
- strategy logic is deterministic and explainable.

Improvement:

- add ML only as a research layer, not as a replacement for the baseline strategy;
- use classical ML first: logistic regression, random forest, gradient boosting;
- predict short-horizon adverse selection, volatility regime or fill quality;
- use ML outputs as filters: widen quotes, reduce size or stop quoting in risky regimes.

Possible features:

- spread, microprice, imbalance and multi-level imbalance;
- short-term mid-price returns;
- trade imbalance;
- VPIN-like volume imbalance;
- fill markout and adverse-selection labels;
- realized volatility;
- recent fill outcomes;
- inventory and distance from inventory limit.

Why it matters:

- market making often fails because of adverse selection;
- ML can help detect when not to quote, but it must be validated with walk-forward splits to avoid overfitting.

## 9. Risk Controls

Current state:

- inventory cap is implemented;
- inventory affects AS reservation price;
- there is no regime-dependent stop or quote shutdown.

Improvement:

- add dynamic inventory limits;
- reduce quote size when inventory is large;
- stop quoting one side when the strategy is already too exposed;
- add drawdown-aware risk limits for research experiments.

Why it matters:

- full-dataset results show that inventory and adverse selection remain important risks;
- risk controls may improve drawdown even when raw PnL does not improve immediately.

## 10. Fast Research Engine

Current state:

- the submission engine is intentionally simple and explainable;
- a separate fast research path can be used to evaluate ideas more quickly without changing the reference implementation.

Research directions:

- full-dataset strategy tournaments;
- fee/rebate sensitivity tests;
- latency sensitivity tests;
- queue-assumption sensitivity tests;
- inventory-stop and one-sided quoting experiments;
- toxicity/VPIN filters;
- ML filters;
- PnL attribution and fill markout studies.

How to present it:

- keep the simple Python engine as the submission/reference engine;
- use the fast engine only for research sweeps and future improvements;
- port only the best explainable ideas back into the simple implementation.

Why it matters:

- fast research makes it possible to test many parameter and regime assumptions;
- keeping it separate avoids making the submission code too complex for an interview.

## 11. Backtester Performance Improvements

Current state:

- the submission backtester is plain Python and optimized for readability;
- the simple engine is good for interview explanation, but slower for full-dataset sweeps.

Improvement:

- keep the simple Python engine as the correctness reference;
- add a fast research engine for large sweeps;
- use vectorized NumPy arrays for event processing where possible;
- use Polars for fast CSV/parquet loading, filtering and EDA;
- store preprocessed data as parquet instead of repeatedly reading large CSV files;
- use Numba for hot loops if the code remains Python-based;
- reduce per-event object allocation in the replay loop;
- cache parsed timestamps and normalized L2 arrays.

Why it matters:

- full-dataset strategy tournaments are expensive in pure Python;
- faster iteration makes calibration, sensitivity tests and walk-forward validation practical.

## 12. Rust Production Backtester Track

Current state:

- Python is best for a readable entrance-project implementation;
- the current code is suitable for explanation and interview discussion.

Future production direction:

- rewrite the core replay engine in Rust;
- keep Python for research notebooks, configs and reporting;
- expose Rust core to Python through bindings if needed.

Rust advantages:

- near C++ performance for event-by-event simulation;
- memory safety without a garbage collector;
- strong type system for orders, fills, book events and state transitions;
- safer concurrency for parallel parameter sweeps;
- easier to maintain than large C++ systems in many cases;
- good fit for deterministic low-latency simulation logic.

Python advantages:

- fastest to develop and explain;
- best for data exploration, reporting and prototyping;
- easier for interview discussion.

C++ advantages:

- very high performance;
- common in production HFT systems;
- mature low-level ecosystem.

Recommended architecture:

- Python reference backtester for clarity;
- fast NumPy/Polars/Numba research engine for experiments;
- Rust core if the project becomes a production-grade simulator.

## 13. Reporting Improvements

Current state:

- reports include PnL, turnover, fills, inventory and drawdown;
- EDA report summarizes basic data quality.

Improvement:

- add daily/session PnL breakdown;
- add PnL attribution by spread capture, inventory markout and rebates;
- add fill markout and adverse-selection reports;
- add latency and queue sensitivity tables;
- add more plots for inventory, equity and drawdown.

Why it matters:

- aggregate PnL is not enough to understand why a market-making strategy wins or loses;
- attribution makes the strategy easier to explain in an interview and easier to improve.
