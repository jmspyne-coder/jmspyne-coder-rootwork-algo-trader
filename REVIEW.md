# Independent Review Brief — Rootwork ORB Bot

Purpose: an experienced systematic trader should sanity-check this before any
real capital is risked. It is paper-only today and has never placed a clean
on-time live trade. The engineering and the statistics are done to a competent
standard; what is missing is lived-market judgment and live data. This brief
tells a reviewer what to scrutinize and where the author (an AI) fell short.

## 0. What is already built (so you don't re-verify plumbing)

- Strategy: 5-minute opening-range breakout (ORB) on SPY + QQQ, ATR(14) x1.5
  stop, candle-strength filter, hold-to-close (15:45 ET force-close). One entry
  per symbol per day, taken only if the first breakout occurs by ~09:41 ET.
- Sizing: risk % of equity capped at a per-symbol notional slice (equity / N
  symbols), i.e. no leverage. The cap binds in practice, so realized per-trade
  risk is small.
- Costs modeled in bps (default ~3 bps round trip, stress-tested at ~7 bps).
- Live safety: fail-closed risk halts (daily-loss, drawdown, consecutive-loss),
  broker-enforced idempotency (deterministic client_order_id), market-calendar
  gate, bar-freshness gate, reconciliation of fills, and an independent 09:58 ET
  watchdog that alarms if the bot did not run. 27 unit tests.
- Validation tooling: `src/validate.py` (bootstrap CIs, permutation test,
  deflated Sharpe), `src/abtest.py` (variant A/B + validation), `src/driftcheck.py`
  (live vs backtest, armed/data-gated), `src/shadow.py` (live variant tandem).

## 0b. Headline validated results (net of costs, 2024-01 to 2026-06)

| symbol | trades | win | net Sharpe | Sharpe 90% CI | perm p | deflated Sharpe |
|---|---|---|---|---|---|---|
| QQQ | 150 | 63% | 3.88 | [1.8, 6.0] | 0.001 | 90% |
| SPY | 43 | 60% | 2.21 | [-2.0, 5.7] | 0.196 | 19% |

Read: QQQ looks like a real edge; SPY does not survive the multiple-testing
haircut and its CI includes negative. An overnight-gap "regime gate" raised QQQ
to Sharpe 4.35 / deflated 93% in-sample.

## 1. What the reviewer needs to be skilled in

1. **Live systematic trading with real capital.** Has run automated strategies
   with real money, watched live diverge from backtest, and felt an edge decay.
   This is the core requirement; the rest is secondary.
2. **Strategy statistics / anti-overfitting.** Sharpe inference on small samples,
   multiple-testing corrections (deflated / probabilistic Sharpe, PBO), bootstrap
   methods including block/stationary bootstrap for serial correlation, and
   sample-size adequacy. Must be able to judge whether the numbers above are
   trustworthy.
3. **Intraday microstructure and execution.** Opening-range/breakout fill
   behavior, market vs limit orders, realistic slippage/spread on SPY/QQQ at the
   open, and IEX vs SIP data-quality differences.
4. **Backtest methodology.** Look-ahead / survivorship / data-leak detection,
   in-sample vs out-of-sample discipline, and whether the backtest faithfully
   represents live execution.
5. **Risk management for automated systems.** Position sizing (fixed-fractional,
   vol targeting, Kelly), drawdown/loss halts, cross-symbol allocation, tail
   risk, and what limits are sane before real money.
6. **The ORB strategy family specifically.** Whether opening-range breakout is a
   known, crowded, or decayed edge, and how it behaves across market regimes.
7. Nice-to-have: **live bot ops / broker APIs (Alpaca a bonus)** — order
   lifecycle, reconciliation, unattended-system failure modes.

Not the right reviewer: a discretionary chart trader, a general software
engineer, or another AI (it would share the author's exact blind spot).

## 2. What the author (AI) was NOT able to do

### Could not verify (data- or time-gated)
- Confirm the edge is real in live trading. Zero on-time real trades exist yet.
- Validate real slippage/fills against the 3 to 7 bps assumption (no live fills).
- Confirm the edge persists forward (only elapsed time reveals decay).
- Quantify IEX (live) vs SIP (backtest) divergence on the opening range itself.

### Statistical shortcuts (not fully rigorous)
- Deflated Sharpe uses an approximated trial-variance and an ESTIMATED trial
  count (18). A rigorous version derives both from the actual set of variants
  tried, and would add PBO / combinatorially-symmetric cross-validation.
- The bootstrap is IID (resamples days independently) and ignores serial
  correlation. A block or stationary bootstrap is the correct tool.
- Small samples (43 SPY / 150 QQQ trades) put the tests near the edge of
  meaningfulness.
- The new regime-gate threshold (1.5%) was taken from a source idea, not swept
  or validated, so its benefit could be luck.
- The new variants (regime gate, close-confirmed breakout) were judged on
  full-sample stats + the deflated haircut, NOT a rolling walk-forward like the
  original v1 params.

### Domain judgment the author cannot supply (the scar-tissue gap)
- Whether ORB is a decayed/crowded edge in this era.
- Whether the QQQ result is a structural edge or an artifact of the 2024-2025
  regime.
- Whether market orders actually fill near the signal level on fast breakouts.
- What constitutes "enough" evidence to risk capital.

### Built to a standard, but not independently audited
- The signal math in `src/orb_signal.py` is unit-tested but not eyeballed by a
  domain expert.
- Live behavior is verified as green/logged on GitHub Actions, but real fills,
  real slippage, and edge persistence are unproven.

### Deferred armor (known, not yet built)
- Limit-style entry to cap slippage (still a market order).
- Absolute notional/share sanity cap, a global kill-switch / error-streak
  breaker, and orphan-position detection.
- Per-symbol filter config (needed to enable the regime gate for QQQ only).
- Live leak-finder and a performance dashboard (data-gated / parked).

## 3. Questions worth their hour, and where to look

1. Is the QQQ edge real enough to risk money, or do you want more history? (see
   `src/validate.py`, `src/backtest.py`)
2. Would you redo the deflated-Sharpe trial accounting or the IID bootstrap?
   (`src/validate.py`)
3. Is the market-order entry + bps slippage assumption realistic for QQQ ORB
   fills? (`src/orb_signal.py`, `src/alpaca_client.py`, `src/costs.py`)
4. Are the risk halts and sizing sane for go-live? (`src/risk_manager.py`,
   `config/settings.py`)
5. What would you need to see before risking capital?
