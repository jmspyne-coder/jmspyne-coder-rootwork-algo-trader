# Limit-Style Entry — Design (D4)

**Status: design only, not implemented** (per the roadmap). This documents the
variant, its tradeoff, how to test it, and the decision rule — so the reviewer
can opine and we can implement quickly if the paper period justifies it.

## Why consider it

Live entry today is a **market order** on the breakout, fired ~09:40 ET — into
the widest-spread part of the day, on directional momentum flow that invites
adverse selection (Invesco literally recommends avoiding QQQ's first 30 min).
The backtest assumes 3-7 bps round trip; the slippage cliff kills the edge at
~22 bps (SPY) / ~28 bps (QQQ). Market orders spend that cushion; a limit entry
caps how much of it any single fill can consume.

## The design

On the first qualifying breakout, instead of a market entry, submit a **bracket
order with a LIMIT entry** (Alpaca supports limit-entry brackets; unlike
fractional orders, the stop/target legs are preserved):

- Long: limit at `or_high + buffer`; Short: limit at `or_low - buffer`.
- `buffer` = a small band (start 1-2 bps of price) that trades fill-probability
  against slippage cap: buffer 0 = never pay up but miss fast moves; wider buffer
  = higher fill rate, more slippage allowed (converges to a market order).
- Time-in-force: DAY, but cancel the entry if unfilled by the entry-window end
  (~09:46) so a stale limit can't fill late off-thesis. Stop/target unchanged.

## The tradeoff (the whole point)

- **Upside:** slippage per fill is bounded by `buffer`, extending the cliff
  cushion — the assumption stops being a guess.
- **Downside:** **non-fill risk.** On a fast, real breakout price gaps through
  the limit and you never get in — and fast breakouts may be exactly the
  profitable ones. So a limit entry can systematically skip the best trades
  while still taking the marginal ones. That selection effect, not the average
  slippage saving, is what decides whether it helps.

## How to test (before implementing)

1. **Backtest approximation:** mark a limit entry FILLED only if, after the
   breakout bar, price trades back to/through `limit` within the entry window;
   otherwise the day is a no-trade. Re-run the slippage cliff and Sharpe on the
   filled subset and compare to the market-order baseline.
2. **Paper A/B:** run limit-entry as a shadow variant alongside the live market
   entry (the shadow harness already exists) and compare realized fill rate,
   realized slippage, and hit rate over the paper period.
3. Report: fill rate, realized-slippage delta vs market, and net-Sharpe delta.

## Decision rule

Let the paper period measure real market-order slippage first. If realized
slippage sits far below the ~22-28 bps kill level, limit entry is unnecessary
complexity. If it creeps toward the cliff, implement the limit variant and keep
it only if the A/B shows it preserves Sharpe (i.e., the non-fill selection does
not eat more than the slippage it saves).

## Reviewer question

For QQQ opening-range breakouts, is capped-slippage limit entry worth the
non-fill risk, or does market-order-into-liquidity remain the right call given
the ~28 bps cushion?
