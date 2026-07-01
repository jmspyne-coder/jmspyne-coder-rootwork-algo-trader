"""
Gap-Fill backtester (mirrors src/backtest.py).

Reuses the exact data fetch, risk controls (simulate_risk_controls) and
performance summary (calculate_performance) as ORB, so gap-fill and ORB results
are directly comparable and net-of-cost. Gap-fill takes at most one trade per
day (a gap day), so ORB and gap-fill are mutually exclusive per the router.

    python -m src.backtest_gap --ticker QQQ --start 2024-01-01 --end 2026-06-01

STATUS: pending a live data key. The Alpaca keys are deauthorized, so this
cannot fetch data yet; the code path is complete and unit-tested on the signal
side. Run this the moment keys are restored to produce the validation numbers.
"""
import argparse
from datetime import datetime, timedelta

import pandas as pd

from config import settings
from src.gap_signal import generate_gap_fill_signal, simulate_gap_fill_trade
from src.orb_signal import calculate_atr
from src.risk_manager import simulate_risk_controls
from src.backtest import calculate_performance, print_summary
from src.alpaca_client import get_data_client, fetch_multi_day_intraday, fetch_daily_bars


def run_backtest(
    ticker: str, start: str, end: str,
    initial_capital: float = None,
    atr_mult: float = None, min_gap_pct: float = None, max_gap_pct: float = None,
    stop_mult: float = None, rr_ratio: float = None,
    entry_offset_min: int = None, direction_filter: str = None,
    capital_cap_frac: float = None,
) -> dict:
    initial_capital = initial_capital or settings.BACKTEST_INITIAL_CAPITAL
    capital_cap_frac = (capital_cap_frac if capital_cap_frac is not None
                        else settings.BACKTEST_CAPITAL_CAP_FRAC)

    print(f"Gap-fill backtest {ticker} {start}..{end}")
    print(f"  stop {stop_mult or settings.GAP_FILL_ATR_STOP_MULT}xATR | "
          f"RR {rr_ratio or settings.GAP_FILL_RR_RATIO} | dir {direction_filter or settings.GAP_FILL_DIRECTION}")
    client = get_data_client()

    daily_start = (datetime.fromisoformat(start) - timedelta(days=30)).strftime("%Y-%m-%d")
    daily = fetch_daily_bars(ticker, daily_start, end, client)
    intra = fetch_multi_day_intraday(ticker, start, end, client)
    if intra.empty:
        return {"error": "No data"}
    intra = intra.copy()
    intra["date"] = intra.index.date
    days = sorted(intra["date"].unique())

    raw = []
    for d in days:
        db = intra[intra["date"] == d].drop(columns=["date"])
        prior = daily[daily.index.date < d]
        atr = calculate_atr(prior, settings.ATR_PERIOD)
        prev_close = float(prior.iloc[-1]["close"]) if len(prior) else None
        sig = generate_gap_fill_signal(
            db, atr=atr, prev_close=prev_close,
            atr_mult=atr_mult, min_gap_pct=min_gap_pct, max_gap_pct=max_gap_pct,
            stop_mult=stop_mult, rr_ratio=rr_ratio,
            entry_offset_min=entry_offset_min, direction_filter=direction_filter,
        )
        if sig is None:
            continue
        r = simulate_gap_fill_trade(sig, db)
        r["date"] = str(d)
        raw.append(r)

    print(f"  gap-fill signals: {len(raw)}")
    if not raw:
        return {"error": "No trades"}

    executed = simulate_risk_controls(raw, initial_capital, capital_cap_frac=capital_cap_frac)
    summary = calculate_performance(executed, initial_capital, days)
    summary["parameters"] = {
        "ticker": ticker, "start": start, "end": end, "strategy": "gap_fill",
        "stop_mult": stop_mult, "rr_ratio": rr_ratio, "direction": direction_filter,
        "atr_mult": atr_mult, "min_gap_pct": min_gap_pct, "max_gap_pct": max_gap_pct,
        "entry_offset_min": entry_offset_min, "capital_cap_frac": capital_cap_frac,
    }
    summary["trades"] = executed
    return summary


def main():
    p = argparse.ArgumentParser(description="Gap-Fill Backtester")
    p.add_argument("--ticker", default="QQQ")
    p.add_argument("--start", default=settings.BACKTEST_START)
    p.add_argument("--end", default=settings.BACKTEST_END)
    p.add_argument("--capital", type=float, default=settings.BACKTEST_INITIAL_CAPITAL)
    p.add_argument("--atr-mult", type=float, default=None)
    p.add_argument("--min-gap-pct", type=float, default=None)
    p.add_argument("--max-gap-pct", type=float, default=None)
    p.add_argument("--stop-mult", type=float, default=None)
    p.add_argument("--rr-ratio", type=float, default=None)
    p.add_argument("--entry-offset-min", type=int, default=None)
    p.add_argument("--direction", default=None, choices=["both", "up", "down"])
    p.add_argument("--cap-frac", type=float, default=None)
    a = p.parse_args()

    summary = run_backtest(
        ticker=a.ticker, start=a.start, end=a.end, initial_capital=a.capital,
        atr_mult=a.atr_mult, min_gap_pct=a.min_gap_pct, max_gap_pct=a.max_gap_pct,
        stop_mult=a.stop_mult, rr_ratio=a.rr_ratio,
        entry_offset_min=a.entry_offset_min, direction_filter=a.direction,
        capital_cap_frac=a.cap_frac,
    )
    print_summary(summary)
    if summary.get("trades"):
        df = pd.DataFrame(summary["trades"])
        out = f"backtest_gap_{a.ticker}_{a.start}_{a.end}.csv"
        df.to_csv(out, index=False)
        print(f"\n  Trades exported to: {out}")


if __name__ == "__main__":
    main()
