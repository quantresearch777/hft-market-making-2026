# Performance Results

This document contains the reproducible performance results for the entrance assignment.

There are three result sets:

1. A five-strategy comparison on the same first `100,000` CMF market events.
2. A full-dataset comparison for the five submission strategies.
3. A simple-engine full-dataset cross-check for the main strategy, `avellaneda_stoikov_microprice`.

## 1. Strategy Comparison On 100,000 Events

All strategies use the same backtester, same data window, same fill model and same fee/rebate assumption.

Fee/rebate assumption:

```text
maker_fee_bps = -0.5
```

This is a Binance-style maker rebate assumption of `0.5` bps (`0.005%`) on filled notional. Negative `fees_paid` in metrics means rebates received. It is a configurable simulation assumption, not a guarantee of a current venue/account-tier fee schedule.

Other execution assumptions used for these results:

| Area | Assumption |
|---|---|
| Order type | Passive limit orders only. |
| Execution trigger | Market trade crosses our order level. |
| Fill price | Our own limit price. |
| Partial fills | Enabled and capped by trade quantity. |
| Queue position | Not modeled. |
| Feed latency | Not modeled. |
| Order latency | `order_latency_ns: 0` in submission configs. |
| Market impact | Our simulated orders do not alter the historical book. |

| Strategy | Final PnL | Max Drawdown | Turnover | Fills | Mean Abs Inventory | PnL / Turnover |
|---|---:|---:|---:|---:|---:|---:|
| `avellaneda_stoikov_microprice` | `+1.05604632` | `-6.46136665` | `47,685.0473` | `1,627` | `21,461.5782` | `2.2146e-05` |
| `as_obi_hybrid` | `+0.91865362` | `-7.24162391` | `34,107.4944` | `1,154` | `22,106.8293` | `2.6934e-05` |
| `avellaneda_stoikov_mid` | `+0.78733687` | `-6.10987153` | `48,476.6304` | `1,670` | `20,999.0990` | `1.6242e-05` |
| `as_ewma_vol` | `-0.28079305` | `-2.87257005` | `22,313.4571` | `768` | `11,934.7874` | `-1.2584e-05` |
| `fixed_spread` | `-35.54110231` | `-35.87911009` | `290,550.5468` | `9,379` | `27,603.7279` | `-1.2232e-04` |

Interpretation:

- `avellaneda_stoikov_microprice` has the best final PnL in the 100k-event comparison.
- The microprice enhancement improves final PnL versus the mid-price AS baseline on this data window.
- `as_ewma_vol` has lower drawdown and lower average inventory, but gives up PnL.
- `fixed_spread` is useful as a sanity baseline, but performs much worse because it does not adapt to book pressure.

## 2. Full-Dataset Results For All Submission Strategies

The full CMF dataset contains:

| File | Rows Including Header |
|---|---:|
| `data/MD/lob.csv` | `1,036,691` |
| `data/MD/trades.csv` | `21,864,990` |

The full-dataset all-strategy comparison was generated with the fast NumPy replay engine to make the full tournament practical. It uses the same strategy names, market data, crossing-style fill assumption and maker rebate assumption as the submission engine. The simple Python engine was also run on the full dataset for `avellaneda_stoikov_microprice` as a cross-check.

| Rank | Strategy | Final PnL | Max Drawdown | Turnover | Fills | Mean Abs Inventory | PnL / Turnover | Runtime s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `as_ewma_vol` | `-1,110.98043371` | `-1,115.28821561` | `8,771,071.2147` | `391,681` | `17,698.2356` | `-0.0001266642` | `243.16` |
| 2 | `as_obi_hybrid` | `-1,518.50870375` | `-1,528.58262565` | `11,464,348.0889` | `513,696` | `26,059.9996` | `-0.0001324549` | `290.66` |
| 3 | `avellaneda_stoikov_microprice` | `-1,891.31648109` | `-1,900.84407019` | `13,735,049.1662` | `616,447` | `25,681.8764` | `-0.0001377000` | `272.92` |
| 4 | `avellaneda_stoikov_mid` | `-1,898.82560808` | `-1,909.84191891` | `13,816,032.1383` | `620,444` | `25,695.3283` | `-0.0001374364` | `245.09` |
| 5 | `fixed_spread` | `-8,187.81533526` | `-8,188.11180628` | `49,605,961.2928` | `2,153,102` | `27,088.8911` | `-0.0001650571` | `100.27` |

Interpretation:

- On the full dataset, all five submission strategies are negative under the current simplified fill, latency and queue assumptions.
- `as_ewma_vol` ranks best on full-dataset PnL and also has the lowest average inventory among the five.
- `as_obi_hybrid` is second and improves meaningfully over the plain AS variants.
- `avellaneda_stoikov_microprice` is slightly better than `avellaneda_stoikov_mid`, but the difference is small on the full dataset.
- `fixed_spread` performs worst because it overtrades and does not adapt to order-book pressure.

## 3. Full-Dataset Cross-Check For Main Strategy

The simple Python engine was run on the full dataset for the main strategy:

| Metric | Value |
|---|---:|
| Strategy | `avellaneda_stoikov_microprice` |
| Processed events | `22,901,679` |
| Final PnL | `-1,891.31648109` |
| Max drawdown | `-1,900.84407019` |
| Turnover | `13,735,049.1662` |
| Number of fills | `616,447` |
| Mean abs inventory | `25,681.8764` |
| Max abs inventory | `50,000.0` |
| PnL / turnover | `-0.0001377000` |
| Final position | `24,572.0` |
| Fees/rebates paid | `-686.75245831` |
| Runtime | `1,155.62 seconds` |

Interpretation:

- The simple-engine full result matches the fast full result for `avellaneda_stoikov_microprice` on the reported metrics.
- The strategy is positive on the first 100k-event comparison window but negative on the full dataset.
- This means the 100k result should not be presented as robust profitability.
- The full runs show why the improvement roadmap matters: queue position, latency, parameter calibration and walk-forward testing are necessary before making stronger profitability claims.
- The main value of the submission is the explainable backtester and strategy implementation, not over-claiming live trading performance.

## 4. Strategy Descriptions, Pros And Cons

| Strategy | Description | Pros | Cons | Result Insight |
|---|---|---|---|---|
| `fixed_spread` | Simple passive market maker around mid price with fixed half-spread and basic inventory skew. | Very easy to explain; good sanity baseline for fills, accounting and turnover. | Does not adapt to volatility or order-book pressure; trades too much in adverse conditions. | Worst full-dataset result: `-8,187.8153` PnL with the highest turnover among the five submission strategies. |
| `avellaneda_stoikov_mid` | Avellaneda-Stoikov 2008 baseline using mid price as fair value. Quotes are shifted by inventory risk and spread is controlled by risk/arrival parameters. | Standard academic baseline; clear inventory control; directly satisfies the required AS implementation. | Fair value ignores book imbalance; performance depends heavily on `gamma`, `k`, volatility estimate and horizon. | Full-dataset PnL: `-1,898.8256`; much better than fixed spread, but slightly worse than microprice AS. |
| `avellaneda_stoikov_microprice` | Avellaneda-Stoikov with microprice as fair value instead of mid price. Microprice uses best bid/ask sizes to detect short-term pressure. | Required enhancement; keeps AS risk logic while reacting to top-of-book imbalance; best PnL on the 100k comparison. | Level-1 microprice can be noisy; still does not model queue position or latency; full-dataset PnL remains negative. | Full-dataset PnL: `-1,891.3165`; slightly improves over AS mid and was cross-checked with the simple Python engine. |
| `as_obi_hybrid` | AS risk engine with multi-level order-book-imbalance fair-value adjustment. It extends microprice from level 1 to several L2 levels with decay. | Uses more available L2 information; explainable alpha; better full-dataset PnL than AS mid and microprice. | More parameters; deeper book liquidity may be stale or less predictive; alpha can conflict with inventory skew if too strong. | Full-dataset PnL: `-1,518.5087`; second-best full-dataset result. |
| `as_ewma_vol` | AS variant that becomes more defensive when recent realized volatility rises. It widens risk/spread during noisier regimes. | Best full-dataset PnL; lowest mean absolute inventory; lower drawdown than the plain AS variants. | Can miss profitable fills when it becomes too defensive; needs careful volatility calibration. | Best full-dataset result: `-1,110.9804`; strongest candidate for the improvement roadmap. |

## 5. Main Takeaways

- The 100k-event window is useful for a controlled side-by-side comparison, but it is not enough to claim robust profitability.
- The full dataset is harder: all five submission strategies are negative under the current simplified execution assumptions.
- Avellaneda-Stoikov logic clearly improves over the fixed-spread baseline.
- Adding order-book information helps: `avellaneda_stoikov_microprice` improves over `avellaneda_stoikov_mid`, and `as_obi_hybrid` improves further on the full dataset.
- Defensive volatility adaptation helps most on the full dataset: `as_ewma_vol` has the best PnL and lowest average inventory.
- The next improvements should focus on queue position, latency, parameter calibration and walk-forward validation.
