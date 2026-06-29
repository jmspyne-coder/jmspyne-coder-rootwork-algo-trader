"""
Exit-policy study.

The leak-finder showed the 2:1 bracket almost never fires (43/46 exits are the
3:45pm force-close), so the strategy is effectively "enter on breakout, hold to
the close." This asks whether a smarter exit beats that blind EOD close, holding
ENTRIES fixed (v1 + candle) and only varying how trades exit.

Policies (same stop distance, so position sizing is identical across them):
  bracket_2to1   current: ATR stop + 2:1 limit target, else EOD close
  stop_eod       just the stop, otherwise ride to the close (let winners run)
  trailing_atr   trailing stop at ATR*mult from the running peak, else EOD
  time_1200      exit at the first bar >= 12:00 ET (stop still active before), else EOD
  target_1to1    ATR stop + 1:1 target (tighter), else EOD

All net of costs, full history + holdout. Small samples: read direction, not
decimals. Analysis only — no live change without sign-off.

Usage:
    python -m src.exitstudy --tickers SPY,QQQ --holdout 2025-06-01
"""
import argparse
import copy
from datetime import timedelta

import pandas as pd

from config import settings
from src.orb_signal import generate_signal
from src.risk_manager import simulate_risk_controls
from src.alpaca_client import get_data_client, fetch_multi_day_intraday, fetch_daily_bars
from src.backtest import calculate_performance
from src.walkforward import precompute, in_range, DEFAULT_V1

LIVE_CONFIG = {**DEFAULT_V1, "candle": True, "candle_pct": 0.5}
START, END = "2024-01-01", "2026-06-01"
POLICIES = ["bracket_2to1", "stop_eod", "trailing_atr", "time_1200", "target_1to1"]
CUTOFF = "15:44"   # force-close bar (matches FORCE_CLOSE_TIME 15:45)
TIME_EXIT = "12:00"


def simulate_exit(sig, day_bars, policy):
    """Walk post-entry bars and return (exit_price, pnl_per_share) for a policy."""
    bars = day_bars.between_time("09:30", CUTOFF)
    post = bars[bars.index >= pd.Timestamp(sig.timestamp)]
    if post.empty:
        return sig.entry_price, 0.0

    long = sig.direction == "long"
    entry, stop = sig.entry_price, sig.stop_price
    risk = abs(entry - stop)
    target2 = sig.target_price
    target1 = entry + risk if long else entry - risk
    atr_dist = (sig.atr * settings.ATR_STOP_MULTIPLIER) if sig.atr else risk
    peak = entry

    def out(price):
        return price, (price - entry if long else entry - price)

    for ts, row in post.iterrows():
        hi, lo, close = row["high"], row["low"], row["close"]
        # stop is honored in every policy
        if (long and lo <= stop) or (not long and hi >= stop):
            return out(stop)
        if policy == "bracket_2to1":
            if (long and hi >= target2) or (not long and lo <= target2):
                return out(target2)
        elif policy == "target_1to1":
            if (long and hi >= target1) or (not long and lo <= target1):
                return out(target1)
        elif policy == "trailing_atr":
            peak = max(peak, hi) if long else min(peak, lo)
            trail = (peak - atr_dist) if long else (peak + atr_dist)
            if (long and lo <= trail) or (not long and hi >= trail):
                return out(trail)
        elif policy == "time_1200":
            if ts.strftime("%H:%M") >= TIME_EXIT:
                return out(close)
        # stop_eod: nothing extra, fall through to EOD
    return out(float(post.iloc[-1]["close"]))


def build_for_policy(day_groups, atr_by_day, policy):
    trades = []
    for d, db in day_groups.items():
        sig = generate_signal(db, atr=atr_by_day[d],
                              filter_vwap=LIVE_CONFIG.get("vwap", False),
                              filter_rvol=LIVE_CONFIG.get("rvol", False),
                              filter_candle=LIVE_CONFIG.get("candle", False),
                              candle_pct=LIVE_CONFIG.get("candle_pct"))
        if sig is None:
            continue
        exit_price, pnl_ps = simulate_exit(sig, db, policy)
        trades.append({
            "direction": sig.direction, "entry_price": sig.entry_price,
            "stop_price": sig.stop_price, "pnl_per_share": round(pnl_ps, 4),
            "entry_time": sig.timestamp, "date": str(d),
        })
    return trades


def evaluate(trades, split=None, holdout=False):
    if split:
        trades = in_range(trades, split, "9999") if holdout else in_range(trades, "0000", split)
    if not trades:
        return None
    ex = simulate_risk_controls(copy.deepcopy(trades), settings.BACKTEST_INITIAL_CAPITAL)
    days = sorted({t["date"] for t in trades})
    s = calculate_performance(ex, settings.BACKTEST_INITIAL_CAPITAL, days)
    return None if "error" in s else s


def _row(label, s):
    if s is None:
        return f"  {label:<16}{'(no trades)':>12}"
    return (f"  {label:<16}{s['total_trades']:>7}{s['win_rate']:>8.0%}"
            f"{s['sharpe_ratio']:>9.2f}{s['total_return']:>9.1%}{s['max_drawdown']:>8.1%}")


def main():
    ap = argparse.ArgumentParser(description="ORB exit-policy study")
    ap.add_argument("--tickers", default="SPY,QQQ")
    ap.add_argument("--holdout", default="2025-06-01")
    args = ap.parse_args()
    client = get_data_client()

    for tk in [t.strip() for t in args.tickers.split(",")]:
        daily_start = (pd.Timestamp(START) - timedelta(days=40)).strftime("%Y-%m-%d")
        daily = fetch_daily_bars(tk, daily_start, END, client)
        intra = fetch_multi_day_intraday(tk, START, END, client)
        dg, atr = precompute(intra, daily)

        print(f"\n{'='*60}\n  EXIT STUDY — {tk}  (v1+candle entries, net of costs)\n{'='*60}")
        print(f"  {'policy':<16}{'trades':>7}{'win%':>8}{'Sharpe':>9}{'return':>9}{'maxDD':>8}")
        for pol in POLICIES:
            trades = build_for_policy(dg, atr, pol)
            print(_row(pol + " [full]", evaluate(trades)))
        print(f"  {'-- holdout (>= ' + args.holdout + ') --':<48}")
        for pol in POLICIES:
            trades = build_for_policy(dg, atr, pol)
            print(_row(pol + " [hold]", evaluate(trades, split=args.holdout, holdout=True)))


if __name__ == "__main__":
    main()
