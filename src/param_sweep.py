"""
ORB v2 Parameter Sweep — A/B tests the confirmation filters against baseline.

Matrix = top-3 v1 configs × 4 filter stacks = 12 runs (down from 81), so the
filter contribution is isolated cleanly and runtime stays reasonable.

Base configs (the strongest from the v1 sweep):
  1. SPY / 5m  / ATR 1.5x / 0.3% range
  2. QQQ / 5m  / ATR 1.5x / 0.3% range
  3. SPY / 30m / midline  / 0.3% range

Filter stacks (cumulative):
  - baseline      : all filters OFF  (reproduces v1 results)
  - vwap          : VWAP only
  - vwap+rvol     : VWAP + RVOL
  - full_stack    : VWAP + RVOL + candle strength

Usage:
    python -m src.param_sweep --start 2024-01-01 --end 2026-06-01
"""
import argparse
import itertools
import pandas as pd
import time
from datetime import datetime, timedelta
from src.orb_signal import generate_signal, simulate_trade, calculate_atr
from src.risk_manager import simulate_risk_controls
from src.alpaca_client import get_data_client, fetch_multi_day_intraday, fetch_daily_bars
from src.backtest import calculate_performance
from config import settings


# ─── Sweep Matrix ─────────────────────────────────────────────────────
BASE_CONFIGS = [
    {"ticker": "SPY", "or_minutes": 5,  "stop_mode": "atr",     "atr_mult": 1.5,  "min_range": 0.003},
    {"ticker": "QQQ", "or_minutes": 5,  "stop_mode": "atr",     "atr_mult": 1.5,  "min_range": 0.003},
    {"ticker": "SPY", "or_minutes": 30, "stop_mode": "midline", "atr_mult": None, "min_range": 0.003},
]

FILTER_STACKS = [
    {"label": "baseline",   "vwap": False, "rvol": False, "candle": False},
    {"label": "vwap",       "vwap": True,  "rvol": False, "candle": False},
    {"label": "vwap+rvol",  "vwap": True,  "rvol": True,  "candle": False},
    {"label": "full_stack", "vwap": True,  "rvol": True,  "candle": True},
]

RR_RATIO = 2.0
INITIAL_CAPITAL = 10000.0


def _group_by_day(intraday: pd.DataFrame):
    """Return list of (day, day_bars) for an intraday frame. Computed once per ticker."""
    frame = intraday.copy()
    frame["date"] = frame.index.date
    days = sorted(frame["date"].unique())
    return [(day, frame[frame["date"] == day].drop(columns=["date"]).copy()) for day in days]


def _run_one(day_groups, daily, base, stack):
    """Run one (base config × filter stack) combination, return a perf dict."""
    stop_mode = base["stop_mode"]
    atr_mult = base["atr_mult"]
    min_range = base["min_range"]
    or_min = base["or_minutes"]

    # Override ATR multiplier for this run (restored in finally — fixes v1 leak bug).
    orig_mult = settings.ATR_STOP_MULTIPLIER
    try:
        if atr_mult is not None:
            settings.ATR_STOP_MULTIPLIER = atr_mult

        raw_trades = []
        for day, day_bars in day_groups:
            daily_up_to = daily[daily.index.date < day]
            atr = calculate_atr(daily_up_to, settings.ATR_PERIOD)

            signal = generate_signal(
                day_bars,
                atr=atr,
                or_minutes=or_min,
                rr_ratio=RR_RATIO,
                stop_mode=stop_mode,
                min_range_pct=min_range,
                # Explicit booleans so baseline == v1 (never falls back to config defaults).
                filter_vwap=stack["vwap"],
                filter_rvol=stack["rvol"],
                filter_candle=stack["candle"],
            )
            if signal is None:
                continue

            result = simulate_trade(signal, day_bars)
            result["date"] = str(day)
            raw_trades.append(result)
    finally:
        settings.ATR_STOP_MULTIPLIER = orig_mult

    if raw_trades:
        executed = simulate_risk_controls(raw_trades, INITIAL_CAPITAL)
        # trading_days count isn't perf-critical here; pass the executed set's days
        perf = calculate_performance(executed, INITIAL_CAPITAL, [t["date"] for t in raw_trades])
    else:
        perf = {"total_trades": 0}
    perf["total_signals"] = len(raw_trades)
    return perf


def run_sweep(start: str, end: str) -> pd.DataFrame:
    """Run the 3×4 filter sweep and return a results DataFrame."""
    data_client = get_data_client()

    print("=" * 70)
    print("  ORB v2 FILTER SWEEP")
    print(f"  {start} → {end}")
    print(f"  {len(BASE_CONFIGS)} base configs × {len(FILTER_STACKS)} filter stacks "
          f"= {len(BASE_CONFIGS) * len(FILTER_STACKS)} runs")
    print("=" * 70)

    # Pre-fetch + pre-group data once per unique ticker.
    daily_start = (datetime.fromisoformat(start) - timedelta(days=30)).strftime("%Y-%m-%d")
    tickers = sorted({c["ticker"] for c in BASE_CONFIGS})
    day_groups_cache, daily_cache = {}, {}
    for ticker in tickers:
        print(f"\n  Fetching data for {ticker}...")
        try:
            intraday = fetch_multi_day_intraday(ticker, start, end, data_client)
            daily = fetch_daily_bars(ticker, daily_start, end, data_client)
            day_groups_cache[ticker] = _group_by_day(intraday)
            daily_cache[ticker] = daily
            print(f"    Intraday: {len(intraday)} bars | Daily: {len(daily)} bars "
                  f"| Days: {len(day_groups_cache[ticker])}")
        except Exception as e:
            print(f"    ERROR fetching {ticker}: {e}")
        time.sleep(1)  # respect rate limits

    results = []
    combos = list(itertools.product(BASE_CONFIGS, FILTER_STACKS))
    print(f"\n  Running {len(combos)} combinations...\n")

    for i, (base, stack) in enumerate(combos):
        ticker = base["ticker"]
        atr_suffix = f"({base['atr_mult']}x)" if base["atr_mult"] else ""
        label = f"{ticker} | OR={base['or_minutes']}m | stop={base['stop_mode']}{atr_suffix} | {stack['label']}"
        if ticker not in day_groups_cache:
            print(f"  [{i+1:2d}/{len(combos)}] SKIP {label}: no data")
            continue

        try:
            perf = _run_one(day_groups_cache[ticker], daily_cache[ticker], base, stack)
            results.append({
                "ticker": ticker,
                "or_minutes": base["or_minutes"],
                "stop_mode": base["stop_mode"],
                "atr_multiplier": base["atr_mult"] if base["atr_mult"] else "N/A",
                "min_range_pct": base["min_range"],
                "filter_stack": stack["label"],
                "vwap": stack["vwap"],
                "rvol": stack["rvol"],
                "candle": stack["candle"],
                "total_signals": perf.get("total_signals", 0),
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
            })
            status = "✓" if perf.get("total_pnl", 0) > 0 else "✗"
            print(f"  [{i+1:2d}/{len(combos)}] {status} {label}")
            print(f"            Trades: {perf.get('total_trades', 0)} | "
                  f"Win: {perf.get('win_rate', 0):.0%} | "
                  f"P&L: ${perf.get('total_pnl', 0):+,.0f} | "
                  f"Sharpe: {perf.get('sharpe_ratio', 0):.2f}")
        except Exception as e:
            print(f"  [{i+1:2d}/{len(combos)}] ERROR {label}: {e}")

    return pd.DataFrame(results)


def print_results(df: pd.DataFrame):
    """Print results grouped by base config so each filter stack is comparable to its baseline."""
    if df.empty:
        print("\n  No results to display.")
        return

    stack_order = {s["label"]: i for i, s in enumerate(FILTER_STACKS)}

    print("\n" + "=" * 95)
    print("  FILTER A/B — each base config, baseline vs filter stacks")
    print("=" * 95)

    for (ticker, or_min, stop_mode), grp in df.groupby(["ticker", "or_minutes", "stop_mode"]):
        print(f"\n  ▸ {ticker} | OR={or_min}m | stop={stop_mode}")
        print(f"    {'stack':<12} {'trades':>7} {'win%':>6} {'P&L':>10} "
              f"{'sharpe':>7} {'MDD':>7} {'PF':>6}")
        grp = grp.assign(_o=grp["filter_stack"].map(stack_order)).sort_values("_o")
        for _, r in grp.iterrows():
            print(f"    {r['filter_stack']:<12} {r['total_trades']:>7} "
                  f"{r['win_rate']:>6.0%} ${r['total_pnl']:>+9,.0f} "
                  f"{r['sharpe_ratio']:>7.2f} {r['max_drawdown']:>6.1%} {r['profit_factor']:>6.2f}")

    print("\n" + "=" * 95)
    print("  TOP CONFIGS BY SHARPE RATIO")
    print("=" * 95)
    top = df.sort_values("sharpe_ratio", ascending=False).head(10)
    for _, r in top.iterrows():
        marker = "💰" if r["total_pnl"] > 0 else "📉"
        print(f"  {marker} {r['ticker']} OR={r['or_minutes']}m {r['stop_mode']} | {r['filter_stack']:<11} "
              f"| Trades {r['total_trades']:>3} | Win {r['win_rate']:.0%} | "
              f"P&L ${r['total_pnl']:+,.0f} | Sharpe {r['sharpe_ratio']:.2f} | MDD {r['max_drawdown']:.1%}")
    print("=" * 95)


def main():
    parser = argparse.ArgumentParser(description="ORB v2 Filter Sweep")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-06-01")
    args = parser.parse_args()

    df = run_sweep(args.start, args.end)
    print_results(df)

    out_path = f"sweep_results_{args.start}_{args.end}.csv"
    df.to_csv(out_path, index=False)
    print(f"\n  Full results exported to: {out_path}")


if __name__ == "__main__":
    main()
