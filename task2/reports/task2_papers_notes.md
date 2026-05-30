# Task 2 Paper Notes

These notes summarize the three suggested papers and connect them to the Task 2 liquidation-filter baseline.

## 1. Cross-Impact Of Order Flow Imbalance In Equity Markets

Main idea:

- Order flow imbalance can explain and forecast short-horizon price moves.
- Cross-asset or cross-instrument order flow can add predictive power for future returns.
- The predictive effect is strongest at short horizons and decays quickly.
- Sparse / simple models are useful because many possible cross-impact terms are noisy.

Connection to Task 2:

- Our signal uses cross-source pressure: Binance liquidations plus delayed Bybit liquidations.
- The Bybit +200 ms shift is a practical cross-exchange latency correction.
- The baseline is intentionally short-horizon: 1-second liquidation pressure predicts 30s, 120s and 300s maker markouts.
- The simple threshold rule is consistent with the idea that only strong cross-source flow pressure should be trusted.

Interview/report wording:

```text
I used liquidation pressure as a cross-source order-flow signal. This follows the idea that lagged order-flow variables can contain short-term predictive information, while the signal should remain simple because cross-impact effects decay quickly and can be noisy.
```

## 2. The Market Maker's Dilemma

Main idea:

- Maker trading has a fundamental trade-off: high fill probability often comes with worse post-fill returns.
- A fill is not automatically good; it can mean adverse selection.
- Queue size, queue position, imbalance and short-term price dynamics matter.
- Predicting fill probability alone is not enough; the conditional post-fill return matters.
- Profitable maker strategies should avoid toxic fills or identify reversal/counter-signals.

Connection to Task 2:

- Task 2 does not model queue position directly, but it evaluates post-fill markout PnL.
- The filter is designed to remove trades where the maker side is likely to face adverse post-fill drift.
- The target metric `PnL_kept - PnL_all` is exactly aligned with this paper's message: keep only trades with better conditional post-fill returns.

Interview/report wording:

```text
The baseline is not trying to maximize the number of fills. It filters trades based on expected post-fill quality. This is motivated by the maker trade-off: fills with high probability can be toxic if they are followed by adverse price movement.
```

## 3. The Negative Drift Of A Limit Order Fill

Main idea:

- Limit order fills are not random free spread capture.
- Fills often coincide with adverse mid-price movement.
- Buy limit fills are often followed by downward movement; sell limit fills are often followed by upward movement.
- Simple fill models with random Poisson fills or 100% fill assumptions are too optimistic.
- A realistic backtest should account for adverse selection around fills.

Connection to Task 2:

- The task's maker PnL formula directly measures this post-fill drift through future BBO mid.
- Filtering toxic trades is a way to reduce negative drift.
- Liquidation pressure is used as a stress/adverse-selection proxy.
- The 0.5 bps maker rebate is included, but the strategy still must beat adverse markout, not just collect rebate.

Interview/report wording:

```text
The paper explains why maker fills can have negative drift. In Task 2 I therefore evaluate trades by future mid-price markout and use the filter to avoid situations where recent liquidation pressure suggests adverse selection.
```

## How These Papers Shape The Baseline

The resulting baseline is deliberately simple:

```text
pressure_i = trade_side_i * (signed_binance_liq_1s + signed_bybit_liq_1s_shifted_200ms)
filter_i = 1 if pressure_i <= 100_000 else 0
```

Why this makes sense:

- It uses cross-source order-flow information.
- It respects the Bybit latency convention.
- It focuses on post-fill markout, not just fill probability.
- It tries to avoid negative-drift / adverse-selection trades.
- It is simple enough to generalize to the hidden test.

