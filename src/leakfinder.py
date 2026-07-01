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
        "SELECT ticker, trade_date, direction, entry_time, entry_price, trade_pnl, "
        "exit_reason, range_pct, atr, gap_pct, candle_strength FROM algo_trade_log "
        "WHERE mode = ? AND trade_pnl IS NOT NULL AND exit_reason <> 'open'",
        [mode],
    ).fetch_df()
    con.close()
    trades = rows.to_dict("records")
    # Prefer the gap logged at entry; fall back to analysis-time computation for
    # any trade missing it (older rows logged before gap_pct existed).
    for t in trades:
        g = t.get("gap_pct")
        t["_gap"] = abs(g) if g is not None else None
    attach_gaps(trades)
    return trades


def attach_gaps(trades):
    """Best-effort: compute each trade's overnight gap (open vs prior close) by
    fetching daily bars per ticker and joining by trade_date, so the leak-finder
    can segment live trades by gap size without logging it on the execution path.
    Silently leaves gaps unset if data/keys are unavailable."""
    if not trades or not any(t.get("ticker") and t.get("trade_date") for t in trades):
        return
    try:
        from datetime import timedelta
        import pandas as pd
        from src.alpaca_client import get_data_client, fetch_daily_bars
        client = get_data_client()
        by_ticker = {}
        for t in trades:
            by_ticker.setdefault(t.get("ticker"), []).append(str(t["trade_date"])[:10])
        gap_of = {}
        for tk, dates in by_ticker.items():
            if not tk:
                continue
            lo = (pd.Timestamp(min(dates)) - timedelta(days=10)).strftime("%Y-%m-%d")
            hi = (pd.Timestamp(max(dates)) + timedelta(days=1)).strftime("%Y-%m-%d")
            daily = fetch_daily_bars(tk, lo, hi, client)
            prev = None
            for ts, row in daily.iterrows():
                d = str(ts.date())
                if prev:
                    gap_of[(tk, d)] = (float(row["open"]) - prev) / prev
                prev = float(row["close"])
        for t in trades:
            if t.get("_gap") is not None:
                continue  # already have the logged gap
            key = (t.get("ticker"), str(t.get("trade_date"))[:10])
            t["_gap"] = abs(gap_of[key]) if key in gap_of else None
    except Exception as e:
        print(f"  [leakfinder] gap attach skipped (non-fatal): {e}")


# ─── analysis ─────────────────────────────────────────────────────────

def _bucket_range(pct):
    if pct is None:
        return "?"
    if pct < 0.004:
        return "a. tight (<0.4%)"
    if pct < 0.006:
        return "b. mid (0.4-0.6%)"
    return "c. wide (>0.6%)"


def _bucket_gap(g):
    if g is None:
        return "n/a (no daily data)"
    if g < 0.003:
        return "a. <0.3%"
    if g < 0.007:
        return "b. 0.3-0.7%"
    return "c. >0.7%"


def _bucket_atr(t):
    """Volatility-regime bucket = ATR as % of entry price. Stands in for a VIX
    bucket: Alpaca's feed does not carry VIX, and daily ATR% is the realized-vol
    regime the trade actually opened into (low/normal/high)."""
    atr, price = t.get("atr"), t.get("entry_price")
    if not atr or not price:
        return "?"
    pct = atr / price
    if pct < 0.010:
        return "a. low vol (<1% ATR)"
    if pct < 0.018:
        return "b. normal (1-1.8%)"
    return "c. high vol (>1.8%)"


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
    if any(t.get("_gap") is not None for t in trades):
        _print_dim("By gap size at open", _agg(trades, lambda t: _bucket_gap(t.get("_gap"))), sort_by_pnl=True)
    if any(t.get("atr") and t.get("entry_price") for t in trades):
        _print_dim("By volatility regime (ATR%, VIX proxy)", _agg(trades, _bucket_atr), sort_by_pnl=True)
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
