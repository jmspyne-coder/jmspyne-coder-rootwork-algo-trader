# Entry Timing Comparison: 5m vs 15m ORB (B6)

**Status: NOT YET COMPUTED — blocked on market-data access.**

## Why it is blocked

Comparing a 15-minute opening range (entry ~09:45) against the current 5-minute
ORB (entry ~09:40) requires re-running the signal engine over the raw 1-minute
intraday bars with `or_minutes=15`. The committed trade files
(`results/trades_{SPY,QQQ}.csv`) are the *5-minute* executed sets only; they do
not contain the intraday bars needed to recompute a different opening range.

Re-fetching those bars needs the Alpaca data API, and the API keys in `.env` are
currently deauthorized (every data and account call returns 401). So this cannot
be produced right now without fabricating numbers, which we will not do.

## The hypothesis (unchanged, worth testing once keys are live)

The 5-minute ORB has the higher gross Sharpe but likely the steeper slippage
cliff (dies at a lower bps). The 15-minute ORB may show a lower gross Sharpe but
a flatter cliff. If the 15-minute variant survives where the 5-minute dies, it
could be the better *live* strategy despite the worse backtest. For reference,
the 5-minute kill levels we did compute are SPY ~22.5 bps and QQQ ~28 bps
(`slippage_cliff.csv`), so the 15-minute variant only wins if its own kill level
is higher than those.

Note the wider literature leans the other way: Options Cafe found 5-minute ORB
nearly doubled 15-minute returns with half the drawdown. This test checks
whether that holds once slippage is charged, on our exact instruments.

## Exact reproduction once keys are restored

The backtester already supports the window as a flag, so no new code is needed:

```
# 15-minute ORB backtests (exports backtest_{TICKER}_...csv)
python -m src.backtest --ticker QQQ --or-minutes 15 --start 2024-01-01 --end 2026-06-01
python -m src.backtest --ticker SPY --or-minutes 15 --start 2024-01-01 --end 2026-06-01

# then copy the exports into results/ and rerun the slippage cliff on both windows
python scripts/validation_suite.py
```

Fill this file with the 5m-vs-15m table (gross Sharpe, net Sharpe at each bps,
and each variant's kill level) from those runs.
