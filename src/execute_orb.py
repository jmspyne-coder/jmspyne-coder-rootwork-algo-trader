"""
ORB Execution — Runs at 9:35 AM ET via GitHub Actions.

1. Pull first 5 min of candle data
2. Compute opening range
3. Check for breakout signal
4. Apply risk checks
5. Calculate position size
6. Submit bracket order (entry + stop + target)
"""
import sys
from datetime import datetime, timedelta
import pytz

from src.alpaca_client import (
    get_data_client, get_trading_client,
    fetch_intraday_bars, fetch_daily_bars,
    get_account_equity, submit_bracket_order, get_todays_orders,
)
from src.orb_signal import generate_signal, calculate_atr
from src.risk_manager import (
    load_risk_state, can_trade, calculate_position_size, save_risk_state,
)
from src.trade_logger import log_trade
from src.notifications import (
    notify_trade_entry, notify_no_signal, notify_risk_halt,
)
from config import settings


def main():
    et = pytz.timezone("US/Eastern")
    now = datetime.now(et)
    today = now.date()
    print(f"[EXECUTE ORB] {now.strftime('%Y-%m-%d %H:%M ET')}")

    # 1. Risk pre-check
    trading_client = get_trading_client()
    equity = get_account_equity(trading_client)
    state = load_risk_state(equity)

    allowed, reason = can_trade(state)
    if not allowed:
        notify_risk_halt(reason)
        print(f"  HALTED: {reason}")
        sys.exit(0)

    # Check today's order count
    todays_orders = get_todays_orders(trading_client)
    filled_today = len([o for o in todays_orders if hasattr(o, 'filled_qty') and o.filled_qty])
    if filled_today >= settings.MAX_TRADES_PER_DAY:
        notify_no_signal(settings.TICKER, str(today), "Max trades/day already reached")
        print(f"  Max trades reached ({filled_today})")
        sys.exit(0)

    # 2. Fetch today's intraday bars
    data_client = get_data_client()
    try:
        intraday = fetch_intraday_bars(settings.TICKER, today, data_client=data_client)
        print(f"  Intraday bars: {len(intraday)} rows")
    except Exception as e:
        print(f"  ERROR fetching intraday: {e}")
        sys.exit(1)

    if intraday.empty:
        notify_no_signal(settings.TICKER, str(today), "No intraday data available yet")
        sys.exit(0)

    # 3. Calculate ATR
    start_daily = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    end_daily = now.strftime("%Y-%m-%d")
    try:
        daily = fetch_daily_bars(settings.TICKER, start_daily, end_daily, data_client)
        atr = calculate_atr(daily, settings.ATR_PERIOD)
    except Exception:
        atr = None

    # 4. Generate signal
    signal = generate_signal(intraday, atr=atr)

    if signal is None:
        notify_no_signal(settings.TICKER, str(today))
        print("  No ORB signal detected.")
        sys.exit(0)

    print(f"  Signal: {signal.direction.upper()} @ ${signal.entry_price:.2f}")
    print(f"  Stop: ${signal.stop_price:.2f} | Target: ${signal.target_price:.2f}")
    print(f"  OR range: {signal.range_pct:.2%}")

    # 5. Position sizing
    shares = calculate_position_size(equity, signal.entry_price, signal.stop_price)
    if shares <= 0:
        notify_no_signal(settings.TICKER, str(today), "Position size = 0 (stop too wide or equity too low)")
        print("  Position size = 0, skipping.")
        sys.exit(0)

    print(f"  Position size: {shares} shares (${shares * signal.entry_price:,.0f} notional)")

    # 6. Submit bracket order
    try:
        order = submit_bracket_order(
            ticker=settings.TICKER,
            side="buy" if signal.direction == "long" else "sell",
            qty=shares,
            take_profit_price=signal.target_price,
            stop_loss_price=signal.stop_price,
            trading_client=trading_client,
        )
        print(f"  Order submitted: {order.id}")
        print(f"  Status: {order.status}")

        # Update risk state
        state.trades_today += 1
        save_risk_state(state)

        # Notify
        notify_trade_entry(
            settings.TICKER,
            signal.direction,
            shares,
            signal.entry_price,
            signal.stop_price,
            signal.target_price,
        )

    except Exception as e:
        print(f"  ORDER ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
