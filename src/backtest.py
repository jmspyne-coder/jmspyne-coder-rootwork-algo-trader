"""
ORB Backtesting Engine.

Runs the full strategy over historical data with risk controls applied.
Can be run locally or via GitHub Actions.

Usage:
    python -m src.backtest --ticker TQQQ --start 2024-01-01 --end 2026-06-01
    python -m src.backtest --ticker TQQQ --start 2024-01-01 --end 2026-06-01 --or-minutes 15
"""
import argparse
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from src.orb_signal import generate_signal, simulate_trade, calculate_atr
from src.risk_manager import simulate_risk_controls
from src.alpaca_client import get_data_client, fetch_multi_day_intraday, fetch_daily_bars
from config import settings


def run_backtest(
    ticker: str,
    start: str,
    end: str,
    initial_capital: float = None,
    or_minutes: int = None,
    rr_ratio: float = None,
    stop_mode: str = None,
    filter_vwap: bool = None,
    filter_rvol: bool = None,
    rvol_threshold: float = None,
    filter_candle: bool = None,
    candle_pct: float = None,
) -> dict:
    """
    Full backtest pipeline:
    1. Fetch intraday + daily data from Alpaca
    2. Run ORB signal generation per day
    3. Simulate trades
    4. Apply risk controls
    5. Return performance summary

    Filter args (filter_vwap/filter_rvol/filter_candle and their params) are
    passed straight through to generate_signal(); None means "use config
    default". Set all three to False to reproduce v1 (baseline) behavior.
    """
    initial_capital = initial_capital or settings.BACKTEST_INITIAL_CAPITAL
    or_minutes = or_minutes or settings.OPENING_RANGE_MINUTES
    rr_ratio = rr_ratio or settings.REWARD_RISK_RATIO
    stop_mode = stop_mode or settings.STOP_MODE

    print(f"Backtesting {ticker} from {start} to {end}")
    print(f"  ORB window: {or_minutes} min | R:R = {rr_ratio} | Stop: {stop_mode}")
    print(f"  Filters: vwap={filter_vwap} rvol={filter_rvol} candle={filter_candle}")
    print(f"  Initial capital: ${initial_capital:,.0f}")
    print(f"  Fetching data from Alpaca...")

    data_client = get_data_client()

    # Fetch daily bars for ATR
    daily_start = (datetime.fromisoformat(start) - timedelta(days=30)).strftime("%Y-%m-%d")
    daily_bars = fetch_daily_bars(ticker, daily_start, end, data_client)
    print(f"  Daily bars: {len(daily_bars)} rows")

    # Fetch intraday bars
    intraday_bars = fetch_multi_day_intraday(ticker, start, end, data_client)
    print(f"  Intraday bars: {len(intraday_bars)} rows")

    if intraday_bars.empty:
        print("  ERROR: No intraday data returned.")
        return {"error": "No data"}

    # Group by trading day
    intraday_bars["date"] = intraday_bars.index.date
    trading_days = sorted(intraday_bars["date"].unique())
    print(f"  Trading days: {len(trading_days)}")

    # Run strategy per day
    raw_trades = []
    for day in trading_days:
        day_bars = intraday_bars[intraday_bars["date"] == day].copy()
        day_bars = day_bars.drop(columns=["date"])

        # Calculate ATR from daily bars up to this day
        daily_up_to = daily_bars[daily_bars.index.date < day]
        atr = calculate_atr(daily_up_to, settings.ATR_PERIOD)

        # Generate signal
        signal = generate_signal(
            day_bars,
            atr=atr,
            or_minutes=or_minutes,
            rr_ratio=rr_ratio,
            stop_mode=stop_mode,
            filter_vwap=filter_vwap,
            filter_rvol=filter_rvol,
            rvol_threshold=rvol_threshold,
            filter_candle=filter_candle,
            candle_pct=candle_pct,
        )
        if signal is None:
            continue

        # Simulate trade outcome
        result = simulate_trade(signal, day_bars)
        result["date"] = str(day)
        raw_trades.append(result)

    print(f"  Raw signals: {len(raw_trades)}")

    if not raw_trades:
        print("  No trades generated.")
        return {"error": "No trades"}

    # Apply risk controls
    executed_trades = simulate_risk_controls(raw_trades, initial_capital)
    print(f"  Executed (post-risk): {len(executed_trades)}")

    # Calculate performance
    summary = calculate_performance(executed_trades, initial_capital, trading_days)
    summary["parameters"] = {
        "ticker": ticker,
        "start": start,
        "end": end,
        "or_minutes": or_minutes,
        "rr_ratio": rr_ratio,
        "stop_mode": stop_mode,
        "initial_capital": initial_capital,
        "filter_vwap": filter_vwap,
        "filter_rvol": filter_rvol,
        "rvol_threshold": rvol_threshold,
        "filter_candle": filter_candle,
        "candle_pct": candle_pct,
    }
    summary["trades"] = executed_trades

    return summary


def calculate_performance(trades: list, initial_capital: float, trading_days: list) -> dict:
    """Calculate summary statistics from trade results."""
    if not trades:
        return {"error": "No trades to analyze"}

    pnls = [t["trade_pnl"] for t in trades]
    equities = [t["equity_after"] for t in trades]
    final_equity = equities[-1] if equities else initial_capital

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    scratches = [p for p in pnls if p == 0]

    total_return = (final_equity - initial_capital) / initial_capital
    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")
    max_drawdown = max(t.get("drawdown_pct", 0) for t in trades)

    # Sharpe approximation (daily returns)
    daily_pnl = {}
    for t in trades:
        d = t.get("date", t.get("entry_time", "")[:10])
        daily_pnl[d] = daily_pnl.get(d, 0) + t["trade_pnl"]
    daily_returns = list(daily_pnl.values())
    if len(daily_returns) > 1 and np.std(daily_returns) > 0:
        sharpe = (np.mean(daily_returns) / np.std(daily_returns)) * np.sqrt(252)
    else:
        sharpe = 0

    # Exit reason breakdown
    exit_reasons = {}
    for t in trades:
        reason = t.get("exit_reason", "unknown")
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

    return {
        "total_trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(scratches),
        "win_rate": round(win_rate, 4),
        "total_pnl": round(sum(pnls), 2),
        "total_return": round(total_return, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(max_drawdown, 4),
        "final_equity": round(final_equity, 2),
        "initial_capital": initial_capital,
        "trading_days": len(trading_days),
        "exit_reasons": exit_reasons,
    }


def print_summary(summary: dict):
    """Pretty-print backtest results."""
    if "error" in summary:
        print(f"\n  Error: {summary['error']}")
        return

    p = summary.get("parameters", {})
    print(f"\n{'='*60}")
    print(f"  BACKTEST RESULTS: {p.get('ticker', '?')}")
    print(f"  {p.get('start', '?')} → {p.get('end', '?')}")
    print(f"{'='*60}")
    print(f"  Total trades:     {summary['total_trades']}")
    print(f"  Win/Loss/Scratch: {summary['wins']}/{summary['losses']}/{summary['scratches']}")
    print(f"  Win rate:         {summary['win_rate']:.1%}")
    print(f"  Profit factor:    {summary['profit_factor']:.2f}")
    print(f"  Sharpe ratio:     {summary['sharpe_ratio']:.2f}")
    print(f"  Total P&L:        ${summary['total_pnl']:,.2f}")
    print(f"  Total return:     {summary['total_return']:.1%}")
    print(f"  Max drawdown:     {summary['max_drawdown']:.1%}")
    print(f"  Final equity:     ${summary['final_equity']:,.2f}")
    print(f"  Avg win:          ${summary['avg_win']:,.2f}")
    print(f"  Avg loss:         ${summary['avg_loss']:,.2f}")
    print(f"  Exit reasons:     {summary['exit_reasons']}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="ORB Strategy Backtester")
    parser.add_argument("--ticker", default=settings.TICKER)
    parser.add_argument("--start", default=settings.BACKTEST_START)
    parser.add_argument("--end", default=settings.BACKTEST_END)
    parser.add_argument("--capital", type=float, default=settings.BACKTEST_INITIAL_CAPITAL)
    parser.add_argument("--or-minutes", type=int, default=settings.OPENING_RANGE_MINUTES)
    parser.add_argument("--rr-ratio", type=float, default=settings.REWARD_RISK_RATIO)
    parser.add_argument("--stop-mode", default=settings.STOP_MODE)
    # Filter toggles: --vwap/--no-vwap etc. Omit to use config defaults.
    parser.add_argument("--vwap", action=argparse.BooleanOptionalAction, default=None,
                        help="enable/disable VWAP filter (default: config)")
    parser.add_argument("--rvol", action=argparse.BooleanOptionalAction, default=None,
                        help="enable/disable RVOL filter (default: config)")
    parser.add_argument("--candle", action=argparse.BooleanOptionalAction, default=None,
                        help="enable/disable candle-strength filter (default: config)")
    parser.add_argument("--rvol-threshold", type=float, default=None)
    parser.add_argument("--candle-pct", type=float, default=None)
    args = parser.parse_args()

    summary = run_backtest(
        ticker=args.ticker,
        start=args.start,
        end=args.end,
        initial_capital=args.capital,
        or_minutes=args.or_minutes,
        rr_ratio=args.rr_ratio,
        stop_mode=args.stop_mode,
        filter_vwap=args.vwap,
        filter_rvol=args.rvol,
        rvol_threshold=args.rvol_threshold,
        filter_candle=args.candle,
        candle_pct=args.candle_pct,
    )
    print_summary(summary)

    # Export trades to CSV
    if summary.get("trades"):
        df = pd.DataFrame(summary["trades"])
        out_path = f"backtest_{args.ticker}_{args.start}_{args.end}.csv"
        df.to_csv(out_path, index=False)
        print(f"\n  Trades exported to: {out_path}")


if __name__ == "__main__":
    main()
