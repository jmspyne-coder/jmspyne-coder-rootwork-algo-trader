"""
ORB Parameter Sweep — Tests multiple strategy configurations and ranks results.

Runs a matrix of:
  - Tickers: TQQQ, QQQ, SPY
  - ORB windows: 5, 15, 30 min
  - Stop modes: midline, atr_1.5, atr_2.0
  - Min range filters: 0.3%, 0.5%, 1.0%

Usage:
    python -m src.param_sweep --start 2024-01-01 --end 2026-06-01
"""
import argparse
import itertools
import pandas as pd
import sys
import time
from datetime import datetime, timedelta
from src.orb_signal import generate_signal, simulate_trade, calculate_atr
from src.risk_manager import simulate_risk_controls
from src.alpaca_client import get_data_client, fetch_multi_day_intraday, fetch_daily_bars
from src.backtest import calculate_performance
from config import settings


# ─── Sweep Parameters ────────────────────────────────────────────────
TICKERS = ["TQQQ", "QQQ", "SPY"]
OR_MINUTES = [5, 15, 30]
STOP_CONFIGS = [
    {"mode": "midline", "atr_mult": None},
    {"mode": "atr", "atr_mult": 1.5},
    {"mode": "atr", "atr_mult": 2.0},
]
MIN_RANGE_PCTS = [0.003, 0.005, 0.01]
RR_RATIOS = [2.0]  # keep R:R fixed for now, expand later if needed

INITIAL_CAPITAL = 10000.0


def run_sweep(start: str, end: str) -> pd.DataFrame:
    """Run full parameter sweep and return ranked results."""
    data_client = get_data_client()
    results = []

    # Pre-fetch all data to avoid redundant API calls
    print("=" * 70)
    print("  ORB PARAMETER SWEEP")
    print(f"  {start} → {end}")
    print("=" * 70)

    data_cache = {}
    daily_cache = {}
    daily_start = (datetime.fromisoformat(start) - timedelta(days=30)).strftime("%Y-%m-%d")

    for ticker in TICKERS:
        print(f"\n  Fetching data for {ticker}...")
        try:
            intraday = fetch_multi_day_intraday(ticker, start, end, data_client)
            daily = fetch_daily_bars(ticker, daily_start, end, data_client)
            data_cache[ticker] = intraday
            daily_cache[ticker] = daily
            print(f"    Intraday: {len(intraday)} bars | Daily: {len(daily)} bars")
        except Exception as e:
            print(f"    ERROR fetching {ticker}: {e}")
            continue
        # Brief pause to respect rate limits
        time.sleep(1)

    # Generate all combinations
    combos = list(itertools.product(
        TICKERS, OR_MINUTES, STOP_CONFIGS, MIN_RANGE_PCTS, RR_RATIOS
    ))
    print(f"\n  Running {len(combos)} parameter combinations...\n")

    for i, (ticker, or_min, stop_cfg, min_range, rr) in enumerate(combos):
        if ticker not in data_cache:
            continue

        stop_mode = stop_cfg["mode"]
        atr_mult = stop_cfg["atr_mult"]
        label = f"{ticker} | OR={or_min}m | stop={stop_mode}"
        if atr_mult:
            label += f"({atr_mult}x)"
        label += f" | range>{min_range:.1%} | R:R={rr}"

        try:
            intraday = data_cache[ticker]
            daily = daily_cache[ticker]

            # Override ATR multiplier for this run
            orig_mult = settings.ATR_STOP_MULTIPLIER
            if atr_mult:
                settings.ATR_STOP_MULTIPLIER = atr_mult

            # Group by day and run strategy
            intraday_copy = intraday.copy()
            intraday_copy["date"] = intraday_copy.index.date
            trading_days = sorted(intraday_copy["date"].unique())

            raw_trades = []
            for day in trading_days:
                day_bars = intraday_copy[intraday_copy["date"] == day].copy()
                day_bars = day_bars.drop(columns=["date"])

                daily_up_to = daily[daily.index.date < day]
                atr = calculate_atr(daily_up_to, settings.ATR_PERIOD)

                signal = generate_signal(
                    day_bars,
                    atr=atr,
                    or_minutes=or_min,
                    rr_ratio=rr,
                    stop_mode=stop_mode,
                    min_range_pct=min_range,
                )
                if signal is None:
                    continue

                result = simulate_trade(signal, day_bars)
                result["date"] = str(day)
                raw_trades.append(result)

            # Apply risk controls
            if raw_trades:
                executed = simulate_risk_controls(raw_trades, INITIAL_CAPITAL)
                perf = calculate_performance(executed, INITIAL_CAPITAL, trading_days)
            else:
                perf = {"total_trades": 0}

            # Restore setting
            settings.ATR_STOP_MULTIPLIER = orig_mult

            # Record result
            row = {
                "ticker": ticker,
                "or_minutes": or_min,
                "stop_mode": stop_mode,
                "atr_multiplier": atr_mult or "N/A",
                "min_range_pct": min_range,
                "rr_ratio": rr,
                "total_signals": len(raw_trades),
                "total_trades": perf.get("total_trades", 0),
                "wins": perf.get("wins", 0),
                "losses": perf.get("losses", 0),
                "win_rate": perf.get("win_rate", 0),
                "total_pnl": perf.get("total_pnl", 0),
                "total_return": perf.get("total_return", 0),
                "profit_factor": perf.get("profit_factor", 0),
                "sharpe_ratio": perf.get("sharpe_ratio", 0),
                "max_drawdown": perf.get("max_drawdown", 0),
                "final_equity": perf.get("final_equity", INITIAL_CAPITAL),
                "avg_win": perf.get("avg_win", 0),
                "avg_loss": perf.get("avg_loss", 0),
                "exit_reasons": str(perf.get("exit_reasons", {})),
            }
            results.append(row)

            # Progress indicator
            status = "✓" if perf.get("total_pnl", 0) > 0 else "✗"
            trades = perf.get("total_trades", 0)
            pnl = perf.get("total_pnl", 0)
            sharpe = perf.get("sharpe_ratio", 0)
            print(f"  [{i+1:3d}/{len(combos)}] {status} {label}")
            print(f"           Trades: {trades} | P&L: ${pnl:+,.0f} | Sharpe: {sharpe:.2f}")

        except Exception as e:
            print(f"  [{i+1:3d}/{len(combos)}] ERROR {label}: {e}")
            continue

    # Build results DataFrame
    df = pd.DataFrame(results)
    return df


def print_results(df: pd.DataFrame):
    """Print ranked results — top 10 by Sharpe ratio."""
    if df.empty:
        print("\n  No results to display.")
        return

    # Filter to configs that actually traded
    traded = df[df["total_trades"] >= 5].copy()

    if traded.empty:
        print("\n  No configurations produced 5+ trades.")
        print("  Showing all results sorted by total_pnl:\n")
        traded = df.copy()

    traded = traded.sort_values("sharpe_ratio", ascending=False)

    print("\n" + "=" * 90)
    print("  TOP CONFIGURATIONS BY SHARPE RATIO (min 5 trades)")
    print("=" * 90)

    cols = [
        "ticker", "or_minutes", "stop_mode", "atr_multiplier",
        "min_range_pct", "total_trades", "win_rate", "total_pnl",
        "sharpe_ratio", "max_drawdown", "profit_factor",
    ]

    top = traded.head(15)
    for _, row in top.iterrows():
        pnl_marker = "💰" if row["total_pnl"] > 0 else "📉"
        print(f"\n  {pnl_marker} {row['ticker']} | ORB={row['or_minutes']}m | "
              f"Stop={row['stop_mode']}({row['atr_multiplier']}) | "
              f"MinRange={row['min_range_pct']:.1%}")
        print(f"     Trades: {row['total_trades']} | Win: {row['win_rate']:.0%} | "
              f"P&L: ${row['total_pnl']:+,.0f} | Sharpe: {row['sharpe_ratio']:.2f} | "
              f"MDD: {row['max_drawdown']:.1%} | PF: {row['profit_factor']:.2f}")

    print("\n" + "=" * 90)

    # Summary stats
    profitable = traded[traded["total_pnl"] > 0]
    print(f"\n  Profitable configs: {len(profitable)} / {len(traded)} "
          f"({len(profitable)/len(traded)*100:.0f}%)" if len(traded) > 0 else "")

    if not profitable.empty:
        best = profitable.iloc[0]
        print(f"\n  BEST CONFIG:")
        print(f"    Ticker:      {best['ticker']}")
        print(f"    ORB window:  {best['or_minutes']} min")
        print(f"    Stop mode:   {best['stop_mode']} ({best['atr_multiplier']})")
        print(f"    Min range:   {best['min_range_pct']:.1%}")
        print(f"    Trades:      {best['total_trades']}")
        print(f"    Win rate:    {best['win_rate']:.0%}")
        print(f"    P&L:         ${best['total_pnl']:+,.2f}")
        print(f"    Sharpe:      {best['sharpe_ratio']:.2f}")
        print(f"    Max DD:      {best['max_drawdown']:.1%}")
        print(f"    PF:          {best['profit_factor']:.2f}")


def main():
    parser = argparse.ArgumentParser(description="ORB Parameter Sweep")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-06-01")
    args = parser.parse_args()

    df = run_sweep(args.start, args.end)
    print_results(df)

    # Export full results
    out_path = f"sweep_results_{args.start}_{args.end}.csv"
    df.to_csv(out_path, index=False)
    print(f"\n  Full results exported to: {out_path}")


if __name__ == "__main__":
    main()
