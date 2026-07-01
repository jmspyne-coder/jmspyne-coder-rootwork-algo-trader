# TQQQ / SQQQ Investigation (D3)

Same ORB config (5m, ATR 1.5x, 0.3% min range, 2:1 RR, candle top-50%, per-symbol cap 50%), 2024-01-01..2026-06-01, net of cost. 3x ETFs vs the 1x QQQ baseline. `scripts/tqqq_sqqq_investigation.py`.


## Signal count and headline

| ticker | trades | win% | net Sharpe @3bps | total return | max DD |
|---|---|---|---|---|---|
| QQQ | 150 | 63% | 3.42 | 23.7% | 3.2% |
| TQQQ | 37 | 35% | -4.17 | -8.9% | 11.2% |
| SQQQ | 34 | 38% | -3.66 | -7.6% | 11.2% |

## Slippage ladder (net Sharpe by round-trip bps)

| bps | 0 | 3 | 5 | 7 | 10 | 15 |
|---|---|---|---|---|---|---|
| QQQ | 3.76 | 3.42 | 3.19 | 2.97 | 2.63 | 2.06 |
| TQQQ | -3.92 | -4.17 | -4.34 | -4.51 | -4.77 | -5.19 |
| SQQQ | -3.42 | -3.66 | -3.82 | -3.97 | -4.21 | -4.60 |

## Read — verdict: the ORB edge does NOT transfer to the 3x ETFs

- **No edge, even gross.** TQQQ gross Sharpe -3.92, SQQQ -3.42 — both LOSE money before any slippage is charged (QQQ is +3.76 on the same config). Slippage is not the decider here; there is simply no edge to erode. This flips the usual "3x amplifies the edge and the slippage" intuition: on this ORB config the 3x ETFs have negative expectancy outright.
- **Fewer signals, not more.** TQQQ 37 / SQQQ 34 vs QQQ 150. The hypothesis that the wider 3x daily range would clear the 0.3% min-range filter more often and yield more trades is rejected — likely because the much larger ATR widens the stop and reshapes which breakouts qualify, and the candle filter behaves differently on the leveraged series.
- **Conclusion:** do NOT trade TQQQ/SQQQ with this strategy. The edge is specific to 1x QQQ (and, more weakly, SPY). This is a decisive negative result — worth having on record so the 3x route is closed, not revisited on a hunch.
- Exploratory only (no DSR/PBO/walk-forward run), but none is needed: a negative gross Sharpe ends the inquiry.
