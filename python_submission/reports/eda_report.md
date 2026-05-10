# CMF Market Data EDA Report

## Data Coverage

- LOB sample rows: 200000
- Trades sample rows: 1000000
- LOB time: 2024-08-01T00:00:02.038431+00:00 to 2024-08-02T03:46:47.962570+00:00
- Trades time: 2024-08-01T00:00:00.014926+00:00 to 2024-08-01T13:13:57.097205+00:00

## LOB Quality

- Missing cells: 0
- Nonpositive prices: 0
- Negative quantities: 0
- Crossed book rows: 0
- Locked book rows: 0
- Nonmonotonic timestamps: 0
- Duplicate timestamps: 0
- Inferred tick size: 1e-07

## Trade Quality

- Side counts: `{'sell': 494630, 'buy': 505370}`
- Missing rows: 0
- Nonpositive prices: 0
- Nonpositive quantities: 0
- Nonmonotonic timestamps: 0
- Duplicate timestamps: 134653

## Key Statistics

### LOB mid

| Metric | Value |
|---|---:|
| `count` | 200000 |
| `min` | 0.0097331 |
| `max` | 0.011144049999999999 |
| `mean` | 0.010473525734999784 |
| `std` | 0.0003186874650521185 |
| `p01` | 0.00985595 |
| `p05` | 0.00996725 |
| `p50` | 0.01051305 |
| `p95` | 0.011049449999999999 |
| `p99` | 0.01110005 |

### LOB spread

| Metric | Value |
|---|---:|
| `count` | 200000 |
| `min` | 9.999999999940612e-08 |
| `max` | 1.3000000000000858e-05 |
| `mean` | 1.1457299999999942e-07 |
| `std` | 1.44373238133526e-07 |
| `p01` | 9.999999999940612e-08 |
| `p05` | 9.999999999940612e-08 |
| `p50` | 9.999999999940612e-08 |
| `p95` | 1.0000000000114084e-07 |
| `p99` | 5.000000000005e-07 |

### LOB spread bps

| Metric | Value |
|---|---:|
| `count` | 200000 |
| `min` | 0.08973398360662493 |
| `max` | 13.148445954830901 |
| `mean` | 0.10981048706307894 |
| `std` | 0.14205453575781996 |
| `p01` | 0.09009049590416249 |
| `p05` | 0.09051125281096825 |
| `p50` | 0.09514159447741682 |
| `p95` | 0.10088628602211035 |
| `p99` | 0.5099153030686704 |

### Top-level imbalance

| Metric | Value |
|---|---:|
| `count` | 200000 |
| `min` | -0.9999943765648965 |
| `max` | 0.9999973983841364 |
| `mean` | 0.0029260605728507016 |
| `std` | 0.6887798525238689 |
| `p01` | -0.9976996805111821 |
| `p05` | -0.9848916648680553 |
| `p50` | 0.003773850367932091 |
| `p95` | 0.9846508700280007 |
| `p99` | 0.9976167628379147 |

### Trade price

| Metric | Value |
|---|---:|
| `count` | 1000000 |
| `min` | 0.010378 |
| `max` | 0.0111441 |
| `mean` | 0.010679429710100247 |
| `std` | 0.00021239433869580326 |
| `p01` | 0.0109123 |
| `p05` | 0.0109335 |
| `p50` | 0.0110208 |
| `p95` | 0.0111021 |
| `p99` | 0.0111231 |

### Trade amount

| Metric | Value |
|---|---:|
| `count` | 1000000 |
| `min` | 1.0 |
| `max` | 40150437.0 |
| `mean` | 41384.07350400016 |
| `std` | 155879.08526927442 |
| `p01` | 379.0 |
| `p05` | 456.0 |
| `p50` | 9040.0 |
| `p95` | 127082.0 |
| `p99` | 419305.0 |

### Trade notional

| Metric | Value |
|---|---:|
| `count` | 1000000 |
| `min` | 0.0104002 |
| `max` | 422290.2512349 |
| `mean` | 441.28657353177374 |
| `std` | 1656.8531613146283 |
| `p01` | 4.1587125 |
| `p05` | 5.0195112 |
| `p50` | 99.9531428 |
| `p95` | 1400.3765308 |
| `p99` | 4614.5178988 |


## Recommendations

- Timestamps are monotonic in the sampled rows; streaming merge by timestamp is acceptable.
- Duplicate trade timestamps are present; preserve file order as a stable tie-breaker.
- Use chunked/sample runs during development because trades.csv is large.
- For final comparisons, prefer fixed time windows over fixed row counts because LOB and trades have different event frequencies.
- Start with top 1-5 LOB levels; deeper levels can be used later for richer imbalance features.
- Use trade-side crossing as the primary fill signal and document the no-queue-position assumption.
