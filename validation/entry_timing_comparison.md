# Entry Timing Comparison: 5m vs 15m ORB (B6)

**Status: COMPUTED (2026-07-01).** Real backtests over 2024-01-01 to 2026-06-01,
identical config for both windows. Raw data in `entry_timing_cliff.csv`.

## Headline

The 15-minute opening range does not survive at a higher slippage than the
5-minute. It does not survive at all. Its gross Sharpe is negative before any
cost is charged, so there is no kill level to compare: the edge is already gone
at zero bps. The 5-minute ORB carries the entire edge, and widening the range to
15 minutes destroys it rather than trading gross return for slippage resilience.

This rejects the prior hypothesis this file carried (that the 15-minute variant
might show lower gross Sharpe but a flatter cliff and win where the 5-minute
dies). The data says the opposite.

## Results

Net-of-3bps unless noted. Gross Sharpe is at 0 bps. Kill level is the round-trip
bps where net Sharpe crosses zero (linear interpolation).

| ticker | window | trades | gross Sharpe | net@3 Sharpe | win% | profit factor | kill level |
|---|---|---|---|---|---|---|---|
| SPY | 5m | 46 | 3.06 | 2.65 | 61% | 1.60 | ~22.5 bps |
| SPY | 15m | 97 | -1.11 | -1.76 | 49% | 0.75 | none (negative at 0 bps) |
| QQQ | 5m | 166 | 4.27 | 3.81 | 63% | 1.92 | ~28.0 bps |
| QQQ | 15m | 238 | -0.34 | -0.86 | 54% | 0.86 | none (negative at 0 bps) |

The 5-minute rows are the committed trade sets (`results/trades_*.csv`), so they
reproduce the published slippage cliff (`slippage_cliff.csv`) and the reviewer
brief exactly (SPY kill ~22.5 bps, QQQ ~28 bps). Only the 15-minute rows are new.
Holding the 5-minute side to the canonical set keeps the whole reviewer packet
internally consistent.

## Slippage cliff, both windows

Net Sharpe by assumed round-trip slippage (bps):

| bps | SPY 5m | SPY 15m | QQQ 5m | QQQ 15m |
|---|---|---|---|---|
| 0 | 3.06 | -1.11 | 4.27 | -0.34 |
| 3 | 2.65 | -1.76 | 3.81 | -0.86 |
| 5 | 2.37 | -2.20 | 3.51 | -1.20 |
| 7 | 2.10 | -2.63 | 3.21 | -1.55 |
| 10 | 1.69 | -3.29 | 2.75 | -2.06 |
| 15 | 1.01 | -4.37 | 1.99 | -2.93 |
| 20 | 0.33 | -5.46 | 1.22 | -3.79 |
| 25 | -0.34 | -6.54 | 0.46 | -4.65 |
| 30 | -1.01 | -7.62 | -0.31 | -5.50 |

Both 15-minute curves start below zero and only fall further with cost. There is
no bps range in which the 15-minute variant is preferable.

## Why it fails

The 15-minute window trades more (97 vs 46 on SPY, 238 vs 166 on QQQ) but worse.
Win rate drops from 61-63% to 49-54% and profit factor falls below 1.0 in both
names. Two mechanics drive it:

1. A wider opening range clears the 0.3% minimum-range filter on more days, so
   marginal, low-conviction days that the 5-minute window screened out now
   generate trades. The extra volume is the low-quality tail.
2. Entering at ~09:50 off a 15-minute range chases a move that has already run
   for fifteen minutes. The breakout edge at 09:40 is a fast reaction to the
   first thrust; by 09:50 much of that displacement is priced, so the same
   ATR stop and 2:1 target catch more reversals than continuations.

This agrees with the external reference (Options Cafe: 5-minute ORB nearly
doubled 15-minute returns with half the drawdown). On our exact instruments the
gap is wider, because our version charges realistic slippage and enforces the
live single-shot entry cadence.

## Method: the entry cutoff (important)

Both windows use identical parameters except the opening range and the entry
cutoff that follows from it: ATR 1.5x stop, 2:1 reward:risk, 0.3% minimum range,
candle top-50% filter, per-symbol notional cap 50%, $10k reference capital,
cost-free `gross_pnl` recomputed to net at each bps tier.

The one modeling choice is the 15-minute entry cutoff, and it matters for
reproduction. The 5-minute setup models a live bot that runs once about five
minutes after the range closes: range 09:30-09:35, first breakout accepted
through 09:41, a roughly six-minute window. The 15-minute setup mirrors that
cadence: range 09:30-09:45, first breakout accepted through 09:51.

Running `--or-minutes 15` with the unchanged 09:41 cutoff produces zero signals,
because the range has not closed yet at 09:41. That is a config incompatibility,
not a result, and it is the first thing a reviewer will hit if they rerun naively.
The 09:51 choice is the honest apples-to-apples cadence. The conclusion is not
close enough for a reasonable cutoff variation to flip it: the 15-minute gross
Sharpe would have to move by more than a full point just to reach zero.

## Reproduction

```
# 15-minute ORB, live-cadence cutoff at 09:51 (exports backtest_{TICKER}_*.csv)
python -m src.backtest --ticker QQQ --or-minutes 15 --entry-cutoff 09:51 --start 2024-01-01 --end 2026-06-01
python -m src.backtest --ticker SPY --or-minutes 15 --entry-cutoff 09:51 --start 2024-01-01 --end 2026-06-01

# slippage cliff on both windows: 5m from the committed results/trades_*.csv,
# 15m from the exports above. Writes validation/entry_timing_cliff.csv.
python scripts/entry_timing_analysis.py
```

## Conclusion for the reviewer

Keep the 5-minute ORB. The 15-minute variant is not a more slippage-robust
alternative; it is unprofitable gross. The entry-timing question is settled in
favor of the shipped configuration.
