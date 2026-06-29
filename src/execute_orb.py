"""
ORB Execution — Runs ~9:40 AM ET via GitHub Actions.

Loops over the configured symbols (settings.TICKERS, e.g. SPY + QQQ). For each:
  1. Pull today's intraday bars
  2. Compute opening range + breakout signal (v1 + candle filter)
  3. Size the position (risk % of equity, capital split across symbols)
  4. Submit a bracket order (entry + stop + target) and log it

Account-level risk halts (drawdown / consecutive-loss / daily-loss) are checked
once up front via can_trade. A per-symbol idempotency guard skips a symbol that
already has fills today, so a re-run never double-enters. MAX_TRADES_PER_DAY is
an account-wide daily cap.
"""
import sys
from datetime import datetime, timedelta
import pytz

from src.alpaca_client import (
    get_data_client, get_trading_client,
    fetch_intraday_bars, fetch_daily_bars,
    get_account_equity, submit_bracket_order, get_todays_fills,
)
from src.orb_signal import generate_signal, calculate_atr
from src.risk_manager import (
    load_risk_state, can_trade, calculate_position_size, save_risk_state,
)
from src.trade_logger import log_trade, init_tables
from src.notifications import (
    notify_trade_entry, notify_no_signal, notify_risk_halt,
)
from config import settings


def trade_symbol(ticker, equity, capital_cap, data_client, trading_client, today, now) -> int:
    """Run the ORB flow for one symbol. Returns 1 if an order was placed, else 0."""
    # Idempotency: if this symbol already has fills today, we already traded it.
    try:
        if get_todays_fills(ticker, trading_client):
            print(f"  [{ticker}] already has fills today — skipping (re-run guard).")
            return 0
    except Exception as e:
        print(f"  [{ticker}] fills check failed, proceeding: {e}")

    # Fetch today's intraday bars.
    try:
        intraday = fetch_intraday_bars(ticker, today, data_client=data_client)
    except Exception as e:
        print(f"  [{ticker}] ERROR fetching intraday: {e}")
        return 0
    if intraday.empty:
        notify_no_signal(ticker, str(today), "No intraday data available yet")
        print(f"  [{ticker}] no intraday data.")
        return 0

    # ATR for the stop.
    try:
        start_daily = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        daily = fetch_daily_bars(ticker, start_daily, now.strftime("%Y-%m-%d"), data_client,
                                 feed=settings.ALPACA_DATA_FEED)
        atr = calculate_atr(daily, settings.ATR_PERIOD)
    except Exception:
        atr = None

    # Signal (v1 + candle filter via config defaults).
    signal = generate_signal(intraday, atr=atr)
    if signal is None:
        notify_no_signal(ticker, str(today))
        print(f"  [{ticker}] no ORB signal.")
        return 0

    # Size (risk % of equity, but cap notional at this symbol's share of capital).
    shares = calculate_position_size(equity, signal.entry_price, signal.stop_price,
                                     capital_cap=capital_cap)
    if shares <= 0:
        notify_no_signal(ticker, str(today), "Position size = 0 (stop too wide or capital too low)")
        print(f"  [{ticker}] position size 0 — skipping.")
        return 0

    print(f"  [{ticker}] {signal.direction.upper()} {shares}sh @ ${signal.entry_price:.2f} | "
          f"stop ${signal.stop_price:.2f} | tgt ${signal.target_price:.2f} | "
          f"notional ${shares * signal.entry_price:,.0f}")

    # Dry run: prove the full path without touching the account or the data.
    if settings.DRY_RUN:
        print(f"  [{ticker}] DRY RUN — would {'BUY' if signal.direction == 'long' else 'SELL'} "
              f"{shares} sh; stop ${signal.stop_price:.2f} tgt ${signal.target_price:.2f}. "
              f"No order placed, nothing logged.")
        return 0

    # Submit bracket order.
    try:
        order = submit_bracket_order(
            ticker=ticker,
            side="buy" if signal.direction == "long" else "sell",
            qty=shares,
            take_profit_price=signal.target_price,
            stop_loss_price=signal.stop_price,
            trading_client=trading_client,
        )
        print(f"  [{ticker}] order {order.id} ({order.status})")
        notify_trade_entry(ticker, signal.direction, shares,
                           signal.entry_price, signal.stop_price, signal.target_price)
    except Exception as e:
        print(f"  [{ticker}] ORDER ERROR: {e}")
        return 0

    # Log the entry (best-effort — the order already filled server-side).
    try:
        init_tables()
        log_trade(
            trade_date=str(today), ticker=ticker, direction=signal.direction,
            entry_price=signal.entry_price, stop_price=signal.stop_price,
            target_price=signal.target_price, shares=shares, entry_time=signal.timestamp,
            exit_reason="open", or_high=signal.or_high, or_low=signal.or_low,
            range_pct=signal.range_pct, atr=signal.atr, equity_before=equity,
            vwap_at_entry=signal.vwap_at_entry, rvol_at_entry=signal.rvol_at_entry,
            candle_strength=signal.candle_strength, filters_passed=signal.filters_passed,
            strategy="orb_v2", mode="paper" if settings.ALPACA_PAPER else "live",
        )
        print(f"  [{ticker}] logged to algo_trade_log.")
    except Exception as e:
        print(f"  [{ticker}] trade-log error (non-fatal): {e}")
    return 1


def main():
    et = pytz.timezone("US/Eastern")
    now = datetime.now(et)
    today = now.date()
    tickers = settings.TICKERS
    print(f"[EXECUTE ORB] {now.strftime('%Y-%m-%d %H:%M ET')} | symbols: {', '.join(tickers)}")
    from src.timeguard import ensure_et_window
    ensure_et_window("09:36", "10:14", "EXECUTE ORB")  # intended 09:40 ET

    # Account-level risk pre-check (drawdown / consecutive-loss / daily-loss halts).
    trading_client = get_trading_client()
    equity = get_account_equity(trading_client)
    state = load_risk_state(equity)
    allowed, reason = can_trade(state)
    if not allowed:
        notify_risk_halt(reason)
        print(f"  HALTED: {reason}")
        sys.exit(0)

    data_client = get_data_client()
    capital_cap = equity / max(len(tickers), 1)  # split buying power across symbols
    placed = 0
    for tk in tickers:
        # MAX_TRADES_PER_DAY is an account-wide daily cap.
        if state.trades_today + placed >= settings.MAX_TRADES_PER_DAY:
            print(f"  Account trade cap reached ({settings.MAX_TRADES_PER_DAY}) — stopping.")
            break
        placed += trade_symbol(tk, equity, capital_cap, data_client, trading_client, today, now)

    if placed:
        state.trades_today += placed
        save_risk_state(state)
    print(f"  Done — {placed} order(s) placed across {len(tickers)} symbol(s).")


if __name__ == "__main__":
    main()
