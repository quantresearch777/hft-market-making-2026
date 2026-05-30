# Task 2 Strategy Handoff

This is a GitHub-preview-friendly summary notebook. It contains the final decision, baseline comparison, rejected variants, and links to the reproducible code and full research log.

## Final Strategy

| horizon | final rule | reason |
|---:|---|---|
| 30s | BTC `return5s > 50 bps`, ETH `return5s > 100 bps` | short-term maker reversal signal; ETH needs stricter selection |
| 120s | `liq2s_d200 > 2m` AND `return5s > 20 bps` | liquidation pressure plus a soft return guard improved 120s robustness |
| 300s | `liq2s_d200 > 2m` | plain 2s liquidation pressure was more robust than combo guards on public-extra |

## How The Score Is Read

```text
pnl_all  = markout PnL if we keep every trade, i.e. no-filter baseline
pnl_kept = markout PnL on trades selected by the strategy
score    = pnl_kept - pnl_all
```

For the no-filter baseline, `kept trades = all trades`, so `pnl_kept = pnl_all` and the improvement score is zero by construction. This does not mean no-filter PnL is zero; it means no-filter has zero improvement over itself.

## Baseline vs Balanced Final Strategy

Public 6-month stride=10 screen:

| horizon | no-filter pnl_all | balanced pnl_kept | improvement score |
|---:|---:|---:|---:|
| 30s | -0.0754 | 35.1172 | +35.1926 |
| 120s | -0.0200 | 27.6819 | +27.7020 |
| 300s | 0.0354 | 18.6545 | +18.6190 |

Exact first-week check, full trade stream:

| horizon | no-filter pnl_all | balanced pnl_kept | improvement score | kept turnover/day |
|---:|---:|---:|---:|---:|
| 30s | 0.0378 | 76.5131 | +76.4753 | $65.3M |
| 120s | 0.0636 | 42.9284 | +42.8648 | $31.4M |
| 300s | 0.0583 | 18.3293 | +18.2710 | $71.1M |

## Strategy Variants

| variant | description | public 6m 30s | public 6m 120s | public 6m 300s | public-extra note | decision |
|---|---|---:|---:|---:|---|---|
| No filter | keep all trades | 0 by construction | 0 by construction | 0 by construction | reference only | not a strategy |
| Conservative | 30s return filter, 120s/300s 1s liquidation baseline | 20.6530 | 6.9457 | 7.7372 | stable but weaker | replaced |
| Intermediate | BTC/ETH 30s + plain `liq2` for 120s/300s | 35.1926 | 18.4605 | 18.6190 | improves all horizons | improved further |
| Balanced / final | BTC/ETH 30s + `liq2 AND return20` for 120s + plain `liq2` for 300s | 35.1926 | 27.7020 | 18.6190 | best risk/reward found | selected |
| Aggressive | use `return5s > 50 bps` for 120s/300s too | 35.1926 | 30.0280 | 32.0859 | fails public-extra on 120s/300s | rejected |
| Bybit-heavy | strong Bybit-only liquidation pressure | 35.1926 | 19.3317 | 18.6068 | public-extra 120s/300s was negative | rejected |

The aggressive variant had the best overall 120s/300s score, but it failed public-extra:

```text
120s = -9.8268
300s = -19.8047
```

Therefore I selected the balanced version: slightly lower overall score than aggressive, but much better public-extra behavior.

## Reproducibility Links

- Final strategy: `../src/task2_solution.py`
- Full experiment log: `../reports/task2_experiment_log.md`
- Final candidate memo: `../reports/task2_candidate_improvement_round3.md`
- Tests: `../tests/test_task2_solution.py`
- Result tables: `../reports/tables/`

Validation status:

```text
local tests: 8/8 passed
server tests: 8/8 passed
```
