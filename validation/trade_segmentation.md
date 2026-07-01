# Trade Segmentation / Leak Finder (B5)

Net-of-3bps stats sliced by attributes available in the committed trade files. Sharpe within a thin segment is directional only.

## SPY (46 trades)

**By direction**

| direction | trades | win% | Sharpe | PF |
|---|---|---|---|---|
| long | 21 | 71% | 4.98 | 2.7 |
| short | 25 | 52% | 0.54 | 1.09 |

**By day of week**

| day | trades | win% | Sharpe | PF |
|---|---|---|---|---|
| Monday | 13 | 62% | -4.07 | 0.49 |
| Tuesday | 6 | 33% | 3.45 | 2.25 |
| Wednesday | 6 | 33% | 2.50 | 1.57 |
| Thursday | 8 | 75% | 8.21 | 3.39 |
| Friday | 13 | 77% | 12.16 | 6.36 |

**By opening-range width** (range_pct; <0.3% empty by the 0.3% filter)

| width | trades | win% | Sharpe | PF |
|---|---|---|---|---|
| 0.3-0.6% | 43 | 58% | 1.06 | 1.19 |
| 0.6-1.0% | 3 | 100% | 15.25 | inf |

## QQQ (166 trades)

**By direction**

| direction | trades | win% | Sharpe | PF |
|---|---|---|---|---|
| long | 84 | 70% | 5.07 | 2.35 |
| short | 82 | 55% | 3.06 | 1.68 |

**By day of week**

| day | trades | win% | Sharpe | PF |
|---|---|---|---|---|
| Monday | 34 | 59% | 1.47 | 1.27 |
| Tuesday | 33 | 52% | 2.69 | 1.58 |
| Wednesday | 24 | 75% | 4.98 | 2.72 |
| Thursday | 36 | 61% | 3.66 | 1.89 |
| Friday | 39 | 69% | 6.87 | 2.79 |

**By opening-range width** (range_pct; <0.3% empty by the 0.3% filter)

| width | trades | win% | Sharpe | PF |
|---|---|---|---|---|
| 0.3-0.6% | 152 | 62% | 3.86 | 1.93 |
| 0.6-1.0% | 13 | 69% | 3.15 | 1.72 |
| >1.0% | 1 | 100% | 0.00 | inf |

**Not computed here:** gap-size-at-open buckets need the prior close and the day's open, which are not in the committed trade files. This requires a data re-fetch (blocked while the Alpaca keys are deauthorized) or adding prev_close/open to the trade log going forward.
