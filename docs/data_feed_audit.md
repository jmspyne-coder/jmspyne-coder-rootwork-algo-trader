# Data Feed Audit (C3)

**Verification status: BLOCKED on credentials.** The Alpaca keys in `.env` are
currently deauthorized (every account and data call returns 401), so the live
account's data plan cannot be queried right now. This documents what the code
does today and what must be confirmed the moment keys are restored.

## What the code uses

From `config/settings.py` and `src/alpaca_client.py`:

| Path | Feed | Why |
|---|---|---|
| Live intraday (execute_orb) | **IEX** (`ALPACA_DATA_FEED=iex`, default) | Free plans cannot query recent SIP (403 "subscription does not permit recent SIP"). IEX is real-time on the free tier. |
| Backtest intraday + daily | **SIP** (`feed="sip"`) | Historical SIP is allowed when older than ~15 min and is more complete than IEX. |
| Live ATR / prior close | SIP (historical days) | Matches the backtest ATR. |

So today there is a **known feed mismatch**: the backtest opening range is built
from SIP (all US exchanges, ~100% of volume), while the live opening range is
built from IEX (one exchange, ~2-3% of volume). During the first 5 minutes,
when volume is thinnest, the IEX high/low can miss prints that occurred on other
venues, so the live opening range may differ from the backtested one. This is a
real risk to backtest-to-live fidelity, not just a theoretical one.

## Must confirm once keys are live

1. Which plan is the account on — Free (IEX) or Algo Trader Plus (real-time SIP)?
   Check the Alpaca dashboard, or compare `feed="iex"` vs `feed="sip"` on a
   recent bar request (SIP recent returns 403 on the free tier).
2. Confirm the backtest feed (SIP) vs the live feed (IEX) explicitly.
3. Measure the divergence: during the paper period, log the IEX opening range
   and, where possible, compare to the SIP range for the same session.

## Recommendation

Start on **IEX free** and let the paper period quantify the divergence (this is
exactly what the paper-vs-backtest slippage comparison in C4 captures). Upgrade
to **Algo Trader Plus (~$99/mo real-time SIP)** only if the divergence proves
material. Flag the IEX-vs-SIP opening-range risk in the reviewer brief either
way — it is one of the honest gaps (Section 6).

## Related

- Feed divergence on the opening range is listed as a paper-period item in
  `docs/failure_modes.md` ("Stale data / incomplete opening range").
- The reviewer brief Section 6 carries the IEX-vs-SIP gap as an unverified item.
