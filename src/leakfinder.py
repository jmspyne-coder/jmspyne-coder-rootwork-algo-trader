"""
Leak-finder: where does the P&L actually come from, and where does it bleed?

Breaks a set of RESOLVED trades down by direction, exit reason, day of week,
opening-range size, ATR regime, candle strength, and time period, reporting
net P&L / win rate / average per bucket. Net of costs throughout. The goal is
to surface concentration (one regime carrying everything) and leaks (a bucket
that is reliably net-negative and should be filtered out).

Source is pluggable:
  --source backtest   run a backtest and analyze its trades (default; this is
                      the only fully-resolved dataset until the live bot logs)
  --source motherduck analyze algo_trade_log (live). Needs per-trade outcomes,
                      which are not reconciled yet (entries log as 'open'), so
                      today this will report no resolved trades.

Usage:
    python -m src.leakfinder --source backtest --ticker SPY
"""
import argparse

import pandas as pd

from config import settings


# ─── trade sources ────────────────────────────────────────────────────

def from_backtest(ticker, start, end):
    from src.backtest import run_backtest
    summary = run_backtest(ticker=ticker, start=start, end=end)
    if "error" in summary:
        return []
    return summary.get("trades", [])


def from_motherduck(mode):
    from src.trade_logger import get_connection
    con = get_connection()
    rows = con.execute(
        "SELECT direction, entry_time, trade_pnl, exit_reason, range_pct, atr, "
        "candle_strength FROM algo_trade_log "
        "WHERE mode = ? AND trade_pnl IS NOT NULL AND exit_reason <> 'open'",
        [mode],
    ).fetch_df()
    con.close()
    return rows.to_dict("records")


# ─── analysis ─────────────────────────────────────────────────────────

def _bucket_range(pct):
    if pct is None:
        return "?"
    if pct < 0.004:
        return "a. tight (<0.4%)"
    if pct < 0.006:
        return "b. mid (0.4-0.6%)"
    return "c. wide (>0.6%)"


def _bucket_candle(c):
    if c is None:
        return "n/a (filter off)"
    if c < 0.6:
        return "a. 0.50-0.60"
    if c < 0.75:
        return "b. 0.60-0.75"
    return "c. 0.75-1.00"


def _agg(trades, keyfn):
    groups = {}
    for t in trades:
        groups.setdefault(keyfn(t), []).append(t)
    out = []
    for k, ts in groups.items():
        pnl = sum(t["trade_pnl"] for t in ts)
        wins = sum(1 for t in ts if t["trade_pnl"] > 0)
        out.append({"bucket": k, "trades": len(ts), "win_rate": wins / len(ts),
                    "net_pnl": pnl, "avg_pnl": pnl / len(ts)})
    return sorted(out, key=lambda r: str(r["bucket"]))


def _print_dim(title, rows, sort_by_pnl=False):
    if sort_by_pnl:
        rows = sorted(rows, key=lambda r: r["net_pnl"])
    print(f"\n  {title}")
    print(f"    {'bucket':<20}{'trades':>7}{'win%':>8}{'net P&L':>11}{'avg':>9}")
    for r in rows:
        flag = "   <- LEAK" if r["net_pnl"] < 0 else ""
        print(f"    {str(r['bucket']):<20}{r['trades']:>7}{r['win_rate']:>8.0%}"
              f"{r['net_pnl']:>11,.0f}{r['avg_pnl']:>9,.0f}{flag}")


def analyze(trades):
    trades = [t for t in trades if t.get("trade_pnl") is not None]
    if not trades:
        print("  No resolved trades to analyze.")
        return
    for t in trades:
        t["_dow"] = pd.Timestamp(t["entry_time"]).day_name()[:3]
        t["_period"] = pd.Timestamp(t["entry_time"]).strftime("%Y-H") + (
            "1" if pd.Timestamp(t["entry_time"]).month <= 6 else "2")

    total = sum(t["trade_pnl"] for t in trades)
    wins = sum(1 for t in trades if t["trade_pnl"] > 0)
    print(f"\n{'='*60}\n  LEAK-FINDER  ({len(trades)} resolved trades, net of costs)\n{'='*60}")
    print(f"  Total net P&L: ${total:,.0f} | win rate {wins/len(trades):.0%}")

    _print_dim("By direction", _agg(trades, lambda t: t["direction"]))
    _print_dim("By exit reason", _agg(trades, lambda t: t.get("exit_reason", "?")), sort_by_pnl=True)
    _print_dim("By day of week", _agg(trades, lambda t: t["_dow"]), sort_by_pnl=True)
    _print_dim("By opening-range size", _agg(trades, lambda t: _bucket_range(t.get("range_pct"))))
    _print_dim("By candle strength", _agg(trades, lambda t: _bucket_candle(t.get("candle_strength"))))
    _print_dim("By half-year period", _agg(trades, lambda t: t["_period"]))

    leaks = sorted([r for d in [
        _agg(trades, lambda t: t["direction"]),
        _agg(trades, lambda t: t.get("exit_reason", "?")),
        _agg(trades, lambda t: t["_dow"]),
        _agg(trades, lambda t: _bucket_range(t.get("range_pct"))),
    ] for r in d if r["net_pnl"] < 0], key=lambda r: r["net_pnl"])
    print(f"\n  Biggest leaks (net-negative buckets):")
    if not leaks:
        print("    none — every bucket is net-positive.")
    for r in leaks[:5]:
        print(f"    {str(r['bucket']):<20} {r['trades']} trades, ${r['net_pnl']:,.0f}")


def main():
    ap = argparse.ArgumentParser(description="ORB leak-finder")
    ap.add_argument("--source", choices=["backtest", "motherduck"], default="backtest")
    ap.add_argument("--ticker", default=settings.TICKER)
    ap.add_argument("--start", default=settings.BACKTEST_START)
    ap.add_argument("--end", default=settings.BACKTEST_END)
    ap.add_argument("--mode", default="paper")
    args = ap.parse_args()

    if args.source == "backtest":
        trades = from_backtest(args.ticker, args.start, args.end)
    else:
        trades = from_motherduck(args.mode)
    analyze(trades)


if __name__ == "__main__":
    main()
