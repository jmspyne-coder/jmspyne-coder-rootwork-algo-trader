"""
Entry-timing comparison (B6): 5-minute ORB vs 15-minute ORB.

Runs the same slippage-cliff methodology as scripts/validation_suite.py on two
committed trade sets per ticker, and reports whether the 15-minute variant
survives to a higher round-trip-bps kill level than the 5-minute variant.

Inputs (identical config except the opening-range window and the live entry
cutoff that follows from it):
  5-minute  : results/trades_{SPY,QQQ}.csv          (OR 09:30-09:35, cutoff 09:41)
  15-minute : backtest_{SPY,QQQ}_2024-01-01_2026-06-01.csv (OR 09:30-09:45, cutoff 09:51)

The 15-minute cutoff mirrors the 5-minute live cadence: a single bot run ~5 min
after the range closes, taking the first breakout within a ~6-minute window.

    python scripts/entry_timing_analysis.py
"""
import csv

import numpy as np

CAP = 10000.0
SLIPPAGE_BPS = [0, 3, 5, 7, 10, 15, 20, 25, 30, 35, 40]
SETS = {
    "5m": {"SPY": "results/trades_SPY.csv", "QQQ": "results/trades_QQQ.csv"},
    "15m": {"SPY": "backtest_SPY_2024-01-01_2026-06-01.csv",
            "QQQ": "backtest_QQQ_2024-01-01_2026-06-01.csv"},
}


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def net_pnls(rows, bps):
    return [float(r["gross_pnl"]) - (bps / 1e4) * float(r["entry_price"]) * float(r["shares"])
            for r in rows]


def curve_stats(pnls, dates, cap=CAP):
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    equity, peak, max_dd = cap, cap, 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0)
    by_day = {}
    for d, p in zip(dates, pnls):
        by_day[d] = by_day.get(d, 0.0) + p
    dr = list(by_day.values())
    sd = np.std(dr, ddof=1) if len(dr) > 1 else 0
    sharpe = (np.mean(dr) / sd * np.sqrt(252)) if sd > 0 else 0.0
    return {
        "trades": len(pnls),
        "win_rate": round(len(wins) / len(pnls), 4) if pnls else 0,
        "sharpe": round(float(sharpe), 3),
        "profit_factor": round(abs(sum(wins) / sum(losses)), 2) if losses and sum(losses) else float("inf"),
        "max_drawdown": round(max_dd, 4),
        "total_return": round((equity - cap) / cap, 4),
    }


def kill_level(sharpe_by_bps):
    """Linear-interpolate the bps where net Sharpe first crosses zero."""
    items = sorted(sharpe_by_bps.items())
    for i in range(1, len(items)):
        (b0, s0), (b1, s1) = items[i - 1], items[i]
        if s0 > 0 >= s1:
            return round(b0 + (b1 - b0) * (s0 / (s0 - s1)), 1)
    return None


def main():
    results = {}
    for tk in ("SPY", "QQQ"):
        results[tk] = {}
        for win in ("5m", "15m"):
            rows = load(SETS[win][tk])
            dates = [r["date"] for r in rows]
            curve = {bps: curve_stats(net_pnls(rows, bps), dates)["sharpe"] for bps in SLIPPAGE_BPS}
            gross = curve_stats(net_pnls(rows, 0.0), dates)
            net3 = curve_stats(net_pnls(rows, 3.0), dates)
            results[tk][win] = {
                "n": len(rows), "gross_sharpe": gross["sharpe"], "net3_sharpe": net3["sharpe"],
                "win_rate": net3["win_rate"], "profit_factor": net3["profit_factor"],
                "total_return": net3["total_return"], "curve": curve,
                "kill": kill_level(curve),
            }

    # Persist the cliff (long format) so the reviewer packet has the raw data.
    with open("validation/entry_timing_cliff.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "window", "bps", "net_sharpe"])
        for tk in ("SPY", "QQQ"):
            for win in ("5m", "15m"):
                for bps in SLIPPAGE_BPS:
                    w.writerow([tk, win, bps, results[tk][win]["curve"][bps]])

    for tk in ("SPY", "QQQ"):
        print(f"\n===== {tk} =====")
        print(f"{'':10} {'trades':>7} {'gross Sh':>9} {'net@3 Sh':>9} {'win%':>6} {'PF':>6} {'kill(bps)':>10}")
        for win in ("5m", "15m"):
            r = results[tk][win]
            k = r["kill"]
            print(f"{win:10} {r['n']:>7} {r['gross_sharpe']:>9.2f} {r['net3_sharpe']:>9.2f} "
                  f"{r['win_rate']*100:>5.0f}% {r['profit_factor']:>6} "
                  f"{('~'+str(k)) if k else 'none':>10}")
        print("  net Sharpe by round-trip bps:")
        print("   bps: " + " ".join(f"{b:>6}" for b in SLIPPAGE_BPS))
        for win in ("5m", "15m"):
            print(f"   {win:>3}: " + " ".join(f"{results[tk][win]['curve'][b]:>6.2f}" for b in SLIPPAGE_BPS))
    return results


if __name__ == "__main__":
    main()
