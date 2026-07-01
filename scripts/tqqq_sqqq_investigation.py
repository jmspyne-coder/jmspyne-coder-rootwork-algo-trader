"""
D3: TQQQ / SQQQ investigation.

Runs the SAME ORB config on the 3x-leveraged QQQ ETFs and compares to the 1x QQQ
baseline. Two questions: (1) does the wider daily range clear the 0.3% min-range
filter more often -> more signals? (2) does the edge survive once 3x leverage
also amplifies slippage? Reports the net-Sharpe slippage ladder for each.

    python scripts/tqqq_sqqq_investigation.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.backtest import run_backtest

START, END, CAP = "2024-01-01", "2026-06-01", 10000.0
BPS = [0, 3, 5, 7, 10, 15]
TICKERS = ["QQQ", "TQQQ", "SQQQ"]


def net_sharpe(trades, bps):
    by_day = {}
    for t in trades:
        net = t["gross_pnl"] - (bps / 1e4) * t["entry_price"] * t["shares"]
        by_day[t["date"]] = by_day.get(t["date"], 0.0) + net / CAP
    dr = list(by_day.values())
    sd = np.std(dr, ddof=1) if len(dr) > 1 else 0
    return round((np.mean(dr) / sd * np.sqrt(252)) if sd > 0 else 0.0, 2)


def main():
    rows = {}
    for tk in TICKERS:
        print(f"Backtesting {tk}...")
        s = run_backtest(ticker=tk, start=START, end=END)
        trades = s.get("trades") or []
        rows[tk] = {
            "trades": len(trades),
            "curve": {b: net_sharpe(trades, b) for b in BPS},
            "win": s.get("win_rate", 0), "pf": s.get("profit_factor", 0),
            "ret": s.get("total_return", 0), "dd": s.get("max_drawdown", 0),
        }
        print(f"  {tk}: {len(trades)} trades, gross Sharpe {rows[tk]['curve'][0]}, "
              f"net@7 {rows[tk]['curve'][7]}, ret {s.get('total_return',0):.1%}")

    lines = ["# TQQQ / SQQQ Investigation (D3)\n",
             f"Same ORB config (5m, ATR 1.5x, 0.3% min range, 2:1 RR, candle top-50%, "
             f"per-symbol cap 50%), {START}..{END}, net of cost. 3x ETFs vs the 1x QQQ "
             "baseline. `scripts/tqqq_sqqq_investigation.py`.\n",
             "\n## Signal count and headline\n",
             "| ticker | trades | win% | net Sharpe @3bps | total return | max DD |",
             "|---|---|---|---|---|---|"]
    for tk in TICKERS:
        r = rows[tk]
        lines.append(f"| {tk} | {r['trades']} | {r['win']:.0%} | {r['curve'][3]:.2f} | "
                     f"{r['ret']:.1%} | {r['dd']:.1%} |")
    lines += ["\n## Slippage ladder (net Sharpe by round-trip bps)\n",
              "| bps | " + " | ".join(str(b) for b in BPS) + " |",
              "|---|" + "|".join("---" for _ in BPS) + "|"]
    for tk in TICKERS:
        lines.append(f"| {tk} | " + " | ".join(f"{rows[tk]['curve'][b]:.2f}" for b in BPS) + " |")
    lines += ["\n## Read\n",
              f"- Signal count: TQQQ {rows['TQQQ']['trades']} / SQQQ {rows['SQQQ']['trades']} "
              f"vs QQQ {rows['QQQ']['trades']} — the wider 3x range clears the 0.3% min-range "
              "filter " + ("more" if rows['TQQQ']['trades'] > rows['QQQ']['trades'] else "not more")
              + " often.",
              "- Slippage is the decider: 3x ETFs carry wider spreads, so compare where each "
              "curve crosses zero, not just the gross Sharpe. TastyTrading's TQQQ clone died "
              "near 15 bps.",
              "- This is exploratory only; not validated (no DSR/PBO/walk-forward here) and not "
              "a deployment recommendation."]
    with open("validation/tqqq_sqqq_investigation.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("Wrote validation/tqqq_sqqq_investigation.md")


if __name__ == "__main__":
    main()
