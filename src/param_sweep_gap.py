"""
Gap-Fill parameter sweep (Section 8 of the spec).

Grid = atr_mult(3) x min_gap_pct(3) x stop_mult(3) x rr(3) x entry_offset(3)
     x direction(3) = 729 configs. Reports the same metrics as the ORB sweep
(win rate, Sharpe, max drawdown, profit factor, trade count), ranked by Sharpe
with a minimum-trade-count floor.

Unlike the ORB sweep, this ALSO persists each config's per-day return series to
validation/gap_sweep_returns.csv so PBO/CSCV can be run later (that was a gap in
the ORB validation — the sweep summary alone cannot feed CSCV). Trial count for
the deflated-Sharpe haircut = number of configs actually evaluated (<=729).

    python -m src.param_sweep_gap --ticker QQQ --start 2024-01-01 --end 2026-06-01

STATUS: pending a live data key (Alpaca deauthorized). Runs as-is once restored.
"""
import argparse
import csv
import itertools
import os
from datetime import datetime, timedelta

import pandas as pd

from config import settings
from src.gap_signal import generate_gap_fill_signal, simulate_gap_fill_trade
from src.orb_signal import calculate_atr
from src.risk_manager import simulate_risk_controls
from src.backtest import calculate_performance
from src.alpaca_client import get_data_client, fetch_multi_day_intraday, fetch_daily_bars

GRID = {
    "atr_mult": [0.3, 0.5, 0.75],
    "min_gap_pct": [0.002, 0.003, 0.004],
    "stop_mult": [0.75, 1.0, 1.5],
    "rr_ratio": [1.5, 2.0, 2.5],
    "entry_offset_min": [0, 1, 2],
    "direction": ["both", "up", "down"],
}
MIN_TRADES = 30          # spec floor for credibility
INITIAL_CAPITAL = 10000.0
CAP_FRAC = 0.5
OUT = "validation"


def _prep(ticker, start, end, client):
    daily_start = (datetime.fromisoformat(start) - timedelta(days=30)).strftime("%Y-%m-%d")
    daily = fetch_daily_bars(ticker, daily_start, end, client)
    intra = fetch_multi_day_intraday(ticker, start, end, client)
    intra = intra.copy()
    intra["date"] = intra.index.date
    groups, atr_by_day, prevclose_by_day = {}, {}, {}
    for d, g in intra.groupby("date"):
        groups[d] = g.drop(columns=["date"])
        prior = daily[daily.index.date < d]
        atr_by_day[d] = calculate_atr(prior, settings.ATR_PERIOD)
        prevclose_by_day[d] = float(prior.iloc[-1]["close"]) if len(prior) else None
    return groups, atr_by_day, prevclose_by_day


def _run_one(groups, atr_by_day, prevclose_by_day, cfg):
    raw = []
    for d, db in groups.items():
        sig = generate_gap_fill_signal(
            db, atr=atr_by_day[d], prev_close=prevclose_by_day[d],
            atr_mult=cfg["atr_mult"], min_gap_pct=cfg["min_gap_pct"],
            stop_mult=cfg["stop_mult"], rr_ratio=cfg["rr_ratio"],
            entry_offset_min=cfg["entry_offset_min"], direction_filter=cfg["direction"],
        )
        if sig is None:
            continue
        r = simulate_gap_fill_trade(sig, db)
        r["date"] = str(d)
        raw.append(r)
    if not raw:
        return {"total_trades": 0}, []
    executed = simulate_risk_controls(raw, INITIAL_CAPITAL, capital_cap_frac=CAP_FRAC)
    perf = calculate_performance(executed, INITIAL_CAPITAL, [t["date"] for t in raw])
    # per-day returns for PBO/CSCV
    by_day = {}
    for t in executed:
        by_day[t["date"]] = by_day.get(t["date"], 0.0) + t["trade_pnl"] / INITIAL_CAPITAL
    return perf, sorted(by_day.items())


def main():
    p = argparse.ArgumentParser(description="Gap-Fill parameter sweep (729 configs)")
    p.add_argument("--ticker", default="QQQ")
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default="2026-06-01")
    a = p.parse_args()
    os.makedirs(OUT, exist_ok=True)

    client = get_data_client()
    print(f"Fetching {a.ticker} {a.start}..{a.end} once...")
    groups, atr_by_day, prevclose_by_day = _prep(a.ticker, a.start, a.end, client)

    keys = list(GRID.keys())
    combos = list(itertools.product(*(GRID[k] for k in keys)))
    print(f"Running {len(combos)} configs...")

    rows, returns_rows = [], []
    for i, combo in enumerate(combos):
        cfg = dict(zip(keys, combo))
        cfg_id = f"g{i:03d}"
        perf, daily = _run_one(groups, atr_by_day, prevclose_by_day, cfg)
        rows.append({"config_id": cfg_id, **cfg,
                     "total_trades": perf.get("total_trades", 0),
                     "win_rate": perf.get("win_rate", 0),
                     "sharpe_ratio": perf.get("sharpe_ratio", 0),
                     "max_drawdown": perf.get("max_drawdown", 0),
                     "profit_factor": perf.get("profit_factor", 0),
                     "total_return": perf.get("total_return", 0)})
        for d, ret in daily:
            returns_rows.append({"config_id": cfg_id, "date": d, "daily_return": ret})
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(combos)}")

    with open(f"{OUT}/gap_sweep_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    with open(f"{OUT}/gap_sweep_returns.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["config_id", "date", "daily_return"])
        w.writeheader(); w.writerows(returns_rows)

    ranked = sorted((r for r in rows if r["total_trades"] >= MIN_TRADES),
                    key=lambda r: r["sharpe_ratio"], reverse=True)
    print(f"\nTop configs (>= {MIN_TRADES} trades), by Sharpe:")
    for r in ranked[:10]:
        print(f"  {r['config_id']} stop{r['stop_mult']} rr{r['rr_ratio']} dir={r['direction']} "
              f"off{r['entry_offset_min']} | trades {r['total_trades']} win {r['win_rate']:.0%} "
              f"Sharpe {r['sharpe_ratio']:.2f} MDD {r['max_drawdown']:.1%}")
    print(f"\nWrote {OUT}/gap_sweep_results.csv and gap_sweep_returns.csv "
          f"({len(combos)} configs = DSR trial count).")


if __name__ == "__main__":
    main()
