# Rootwork Algo Trader — Claude Code guide

Automated intraday **Opening Range Breakout (ORB)** trading system.
Runs unattended on GitHub Actions cron, trades via Alpaca, logs to MotherDuck.

## Status
- **Paper trading only** right now (`ALPACA_PAPER='true'` in the workflow and `.env`). Do not flip to live without a deliberate review.
- Active config (per `config/settings.py`): SPY / 5-min ORB / ATR 1.5× stop / 0.3% min range / 2:1 R:R.

## Architecture
```
GitHub Actions cron (UTC times in workflow; ET below)
  09:25 ET  pre_market.py   → equity, ATR, reset daily risk state, notify
  09:35 ET  execute_orb.py  → fetch bars, detect breakout, risk checks, submit bracket order
  15:45 ET  end_of_day.py   → force-close, compute P&L, log to MotherDuck, email/Slack summary
```
Each cron time maps to a separate job in `.github/workflows/trading_schedule.yml`, gated by `github.event.schedule`. `workflow_dispatch` lets you run any single script manually (incl. `backtest`, `param_sweep`).

## Layout
- `config/settings.py` — every tunable param; reads from env with defaults. **Change config here, not in strategy code.**
- `src/orb_signal.py` — pure signal logic (no I/O): `compute_opening_range`, `generate_signal`, `simulate_trade`, `calculate_atr`. Test this offline with synthetic bars.
- `src/risk_manager.py` — `RiskState` dataclass + pre-trade checks (`can_trade`), `calculate_position_size`, post-trade updates, and `simulate_risk_controls` (backtest path). State persists to `config/risk_state.json`.
- `src/alpaca_client.py` — all Alpaca I/O (data fetch + order submission). Bracket orders are server-side (TP/SL), so the bot need not stay alive.
- `src/execute_orb.py` / `pre_market.py` / `end_of_day.py` — the three scheduled entrypoints.
- `src/backtest.py` — `python -m src.backtest --ticker SPY --start 2024-01-01 --end 2026-06-01`.
- `src/param_sweep.py` — grid over tickers × OR windows × stop modes × range filters.
- `src/trade_logger.py` / `src/notifications.py` — MotherDuck (`my_db`: `algo_trade_log`, `algo_daily_summary`) + Slack/Gmail.

## Run locally
```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # Windows
cp .env.example .env   # then fill ALPACA_* + MOTHERDUCK_TOKEN
.venv/Scripts/python -m src.backtest --ticker SPY --start 2024-01-01 --end 2026-06-01
```
Data fetches (backtest included) require valid Alpaca API keys. Pure-logic modules (`orb_signal`, `risk_manager`) run with no network.

## Conventions
- All times in code are **US/Eastern**; the workflow cron is **UTC** (e.g. `35 13` = 09:35 ET during EDT — note this does not auto-adjust for DST).
- Secrets come from env only. Never hardcode; never commit `.env` or `config/risk_state.json` (see `.gitignore`).
- MotherDuck DB is the shared `my_db` used by the rest of the Rootwork platform.

## ⚠️ Known caveats (read before relying on risk controls)
1. **Risk state does not persist across GitHub Actions runs.** Each cron job runs on a fresh, ephemeral runner with a fresh checkout, and `risk_state.json` is never committed back. So `peak_equity`, `consecutive_losses`, `daily_pnl`, and `trades_today` reset to defaults on every run. In the deployed bot, the only effective controls are the per-trade bracket stop and the Alpaca-side max-trades-per-day count — the **drawdown, consecutive-loss, and daily-loss halts are inert**. To make them real, persist state durably (recommended: MotherDuck, which is already the system of record) instead of a local JSON file.
2. **Consecutive-loss halt is a permanent deadlock if state ever persists.** `reset_daily_state` clears the *halt flag* but not the `consecutive_losses` *counter*, so after N losses `can_trade` re-halts every day forever (can't win to reset). Fix: on daily reset, either cool down the counter or leave the halt set for explicit manual clear — pick one semantic.
3. **`execute_orb.py` imports `log_trade` but never calls it** — per-trade rows are not written to `algo_trade_log`; only `algo_daily_summary` is populated (by `end_of_day.py`).
4. **DST**: cron is hardcoded UTC. The 13:xx/19:xx values are correct for EDT; they drift by an hour under EST.
