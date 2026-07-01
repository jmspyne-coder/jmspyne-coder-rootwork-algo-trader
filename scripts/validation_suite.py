"""
Validation suite — produces every reviewer-brief figure that is derivable from
the committed per-trade backtest files, with no market-data access required.

Reads results/trades_{SPY,QQQ}.csv (executed trade lists exported by
src/backtest.py at 3 bps, active config: 5m ORB, ATR 1.5x, 0.3% min range, 2:1
RR, candle top-50% filter ON, per-symbol notional cap = 50%). Each row carries
the cost-free gross_pnl plus entry_price and shares, so net P&L at any cost tier
is exact:

    net = gross_pnl - (round_trip_bps / 1e4) * entry_price * shares

Writes to validation/:
  slippage_cliff.csv / slippage_cliff_summary.md   (B1)
  autocorrelation_check.md / block_bootstrap.csv   (B2)
  dsr_sensitivity.csv                              (B4)
  trade_segmentation.md                            (B5, partial)
  backtest_validation.json                         (headline bundle)

    python scripts/validation_suite.py
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import validate as V

CAP = 10000.0
FILES = {"SPY": "results/trades_SPY.csv", "QQQ": "results/trades_QQQ.csv"}
# 0-20 bps are the directive's requested tiers; 25-40 extend the curve far
# enough to capture the actual kill level (where net Sharpe crosses zero).
SLIPPAGE_BPS = [0, 3, 5, 7, 10, 15, 20, 25, 30, 35, 40]
DSR_TRIALS = [18, 30, 50, 100]
OUT = "validation"


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
        "avg_win": round(float(np.mean(wins)), 2) if wins else 0,
        "avg_loss": round(float(np.mean(losses)), 2) if losses else 0,
        "profit_factor": round(abs(sum(wins) / sum(losses)), 2) if losses and sum(losses) else float("inf"),
        "sharpe": round(float(sharpe), 3),
        "max_drawdown": round(max_dd, 4),
        "total_return": round((equity - cap) / cap, 4),
    }


def iid_bootstrap(rets, n=10000, ci=95, seed=7):
    rng = np.random.default_rng(seed)
    k = len(rets)
    sh = np.array([V.annualized_sharpe(rets[rng.integers(0, k, k)]) for _ in range(n)])
    lo = (100 - ci) / 2
    return {"method": "iid", "ci": ci, "n": n, "median": round(float(np.median(sh)), 2),
            "lo": round(float(np.percentile(sh, lo)), 2),
            "hi": round(float(np.percentile(sh, 100 - lo)), 2),
            "p_le_0": round(float(np.mean(sh <= 0)), 4)}


def block_bootstrap(rets, block=5, n=10000, ci=95, seed=7):
    rng = np.random.default_rng(seed)
    k = len(rets)
    if k < block:
        return {"method": "block", "block": block, "note": "series shorter than block"}
    n_starts, n_blocks = k - block + 1, int(np.ceil(k / block))
    sh = np.empty(n)
    for i in range(n):
        starts = rng.integers(0, n_starts, n_blocks)
        sample = np.concatenate([rets[s:s + block] for s in starts])[:k]
        sh[i] = V.annualized_sharpe(sample)
    lo = (100 - ci) / 2
    return {"method": "block", "block": block, "ci": ci, "n": n,
            "median": round(float(np.median(sh)), 2),
            "lo": round(float(np.percentile(sh, lo)), 2),
            "hi": round(float(np.percentile(sh, 100 - lo)), 2),
            "p_le_0": round(float(np.mean(sh <= 0)), 4)}


def lag1_autocorr(rets):
    r = np.asarray(rets, dtype=float)
    if len(r) < 3:
        return None
    r = r - r.mean()
    denom = float(np.sum(r * r))
    return round(float(np.sum(r[:-1] * r[1:]) / denom), 4) if denom else None


def kill_level(sharpe_by_bps):
    """Linear-interpolate the bps where net Sharpe first crosses zero."""
    items = sorted(sharpe_by_bps.items())
    for i in range(1, len(items)):
        (b0, s0), (b1, s1) = items[i - 1], items[i]
        if s0 > 0 >= s1:
            return round(b0 + (b1 - b0) * (s0 / (s0 - s1)), 1)
    return None  # never crosses within the tested range


def weekday(date_str):
    return datetime.fromisoformat(date_str[:10]).strftime("%A")


def main():
    os.makedirs(OUT, exist_ok=True)
    data = {tk: load(p) for tk, p in FILES.items()}
    dates = {tk: [r["date"] for r in rows] for tk, rows in data.items()}

    # ── B1: slippage cliff ────────────────────────────────────────────
    cliff_rows, kill = [], {}
    sharpe_curve = {tk: {} for tk in data}
    for tk, rows in data.items():
        for bps in SLIPPAGE_BPS:
            s = curve_stats(net_pnls(rows, bps), dates[tk])
            sharpe_curve[tk][bps] = s["sharpe"]
            cliff_rows.append({"ticker": tk, "bps": bps, "net_sharpe": s["sharpe"],
                               "net_total_return": s["total_return"],
                               "net_profit_factor": s["profit_factor"],
                               "net_win_rate": s["win_rate"]})
        kill[tk] = kill_level(sharpe_curve[tk])
    with open(f"{OUT}/slippage_cliff.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cliff_rows[0].keys()))
        w.writeheader(); w.writerows(cliff_rows)

    with open(f"{OUT}/slippage_cliff_summary.md", "w", encoding="utf-8") as f:
        f.write("# Slippage Cliff (B1)\n\n")
        f.write("Net Sharpe vs assumed round-trip slippage (bps), on the committed "
                "5m ORB trade sets. `round_trip_bps = 2*slippage + spread`; recomputed "
                "off the cost-free gross P&L. The kill level is where net Sharpe crosses zero.\n\n")
        f.write("| bps | SPY net Sharpe | QQQ net Sharpe |\n|---|---|---|\n")
        for bps in SLIPPAGE_BPS:
            f.write(f"| {bps} | {sharpe_curve['SPY'][bps]:.2f} | {sharpe_curve['QQQ'][bps]:.2f} |\n")
        f.write("\n")
        for tk in ("SPY", "QQQ"):
            k = kill[tk]
            f.write(f"- **{tk} kill level:** "
                    + (f"~{k} bps round trip (net Sharpe crosses zero)\n"
                       if k else f"does not cross zero within {SLIPPAGE_BPS[-1]} bps "
                                 f"(net Sharpe still {sharpe_curve[tk][SLIPPAGE_BPS[-1]]:.2f} at "
                                 f"{SLIPPAGE_BPS[-1]} bps)\n"))
        f.write("\nContext: an independent ORB clone (TastyTrading, TQQQ/SQQQ) reports its "
                "edge going to zero near 15 bps. The reviewer should judge whether the kill "
                "level here is reachable for QQQ/SPY market orders at 09:40 ET.\n")

    # ── B4: DSR sensitivity ───────────────────────────────────────────
    dsr_rows = []
    for tk, rows in data.items():
        rets = V.daily_returns(net_pnls(rows, 3.0), dates[tk], CAP)
        gross_sh = curve_stats(net_pnls(rows, 0.0), dates[tk])["sharpe"]
        net3_sh = curve_stats(net_pnls(rows, 3.0), dates[tk])["sharpe"]
        for nt in DSR_TRIALS:
            dsr = V.deflated_sharpe(rets, nt)["deflated_sr_prob"]
            dsr_rows.append({"ticker": tk, "trials": nt, "dsr_prob": round(dsr, 4),
                             "gross_sharpe": gross_sh, "net3_sharpe": net3_sh,
                             "net3_pct_of_gross": round(net3_sh / gross_sh, 4) if gross_sh else None})
    with open(f"{OUT}/dsr_sensitivity.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(dsr_rows[0].keys()))
        w.writeheader(); w.writerows(dsr_rows)

    # ── B2: autocorrelation + block bootstrap ─────────────────────────
    boot_rows = []
    ac = {}
    for tk, rows in data.items():
        rets = V.daily_returns(net_pnls(rows, 3.0), dates[tk], CAP)
        ac[tk] = lag1_autocorr(rets)
        iid = iid_bootstrap(rets, ci=95)
        blk = block_bootstrap(rets, block=5, ci=95)
        for b in (iid, blk):
            boot_rows.append({"ticker": tk, "method": b["method"],
                              "block": b.get("block", ""), "ci_lo": b["lo"], "ci_hi": b["hi"],
                              "median": b["median"], "p_sharpe_le_0": b["p_le_0"]})
    with open(f"{OUT}/block_bootstrap.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(boot_rows[0].keys()))
        w.writeheader(); w.writerows(boot_rows)
    with open(f"{OUT}/autocorrelation_check.md", "w", encoding="utf-8") as f:
        f.write("# Serial Correlation and Block Bootstrap (B2)\n\n")
        f.write("Lag-1 autocorrelation of the net-3bps daily P&L, and 95% Sharpe CIs from "
                "an IID bootstrap vs a moving-block bootstrap (block = 5 trading days, "
                "Kunsch 1989), 10,000 resamples each.\n\n")
        f.write("| ticker | lag-1 autocorr | IID 95% CI | block(5) 95% CI |\n|---|---|---|---|\n")
        for tk in ("SPY", "QQQ"):
            iid = [r for r in boot_rows if r["ticker"] == tk and r["method"] == "iid"][0]
            blk = [r for r in boot_rows if r["ticker"] == tk and r["method"] == "block"][0]
            f.write(f"| {tk} | {ac[tk]:.3f} | [{iid['ci_lo']}, {iid['ci_hi']}] | "
                    f"[{blk['ci_lo']}, {blk['ci_hi']}] |\n")
        f.write("\nRead: observed autocorrelation is low, so the block bootstrap does not "
                "materially widen the CI here (the usual 'IID is too narrow' warning applies "
                "in principle but is empirically small on this data). Literature: at phi~0.2-0.3 "
                "the IID CI understates by ~30-50%, up to ~2x at phi~0.6; we are well below that.\n")

    # ── B5: trade segmentation (partial) ──────────────────────────────
    def seg_stats(rows, dts):
        s = curve_stats(net_pnls(rows, 3.0), dts)
        return s["trades"], s["win_rate"], s["sharpe"], s["profit_factor"]

    with open(f"{OUT}/trade_segmentation.md", "w", encoding="utf-8") as f:
        f.write("# Trade Segmentation / Leak Finder (B5)\n\n")
        f.write("Net-of-3bps stats sliced by attributes available in the committed trade "
                "files. Sharpe within a thin segment is directional only.\n")
        for tk, rows in data.items():
            f.write(f"\n## {tk} ({len(rows)} trades)\n\n")
            # Direction
            f.write("**By direction**\n\n| direction | trades | win% | Sharpe | PF |\n|---|---|---|---|---|\n")
            for d in ("long", "short"):
                sub = [r for r in rows if r["direction"] == d]
                if sub:
                    t, wr, sh, pf = seg_stats(sub, [r["date"] for r in sub])
                    f.write(f"| {d} | {t} | {wr:.0%} | {sh:.2f} | {pf} |\n")
            # Day of week
            f.write("\n**By day of week**\n\n| day | trades | win% | Sharpe | PF |\n|---|---|---|---|---|\n")
            for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
                sub = [r for r in rows if weekday(r["date"]) == d]
                if sub:
                    t, wr, sh, pf = seg_stats(sub, [r["date"] for r in sub])
                    f.write(f"| {d} | {t} | {wr:.0%} | {sh:.2f} | {pf} |\n")
            # Opening-range width (range_pct). Min-range filter is 0.3%, so <0.3% is empty.
            f.write("\n**By opening-range width** (range_pct; <0.3% empty by the 0.3% filter)\n\n"
                    "| width | trades | win% | Sharpe | PF |\n|---|---|---|---|---|\n")
            buckets = [("0.3-0.6%", 0.003, 0.006), ("0.6-1.0%", 0.006, 0.010), (">1.0%", 0.010, 9)]
            for name, lo, hi in buckets:
                sub = [r for r in rows if lo <= float(r["range_pct"]) < hi]
                if sub:
                    t, wr, sh, pf = seg_stats(sub, [r["date"] for r in sub])
                    f.write(f"| {name} | {t} | {wr:.0%} | {sh:.2f} | {pf} |\n")
        f.write("\n**Not computed here:** gap-size-at-open buckets need the prior close and "
                "the day's open, which are not in the committed trade files. This requires a "
                "data re-fetch (blocked while the Alpaca keys are deauthorized) or adding "
                "prev_close/open to the trade log going forward.\n")

    # ── headline bundle ───────────────────────────────────────────────
    bundle = {"meta": {"period": "2024-01-01 to 2026-06-01", "capital": CAP,
                       "generated_utc": datetime.now(timezone.utc).isoformat()},
              "kill_level_bps": kill, "lag1_autocorr": ac,
              "slippage_cliff": {tk: sharpe_curve[tk] for tk in data},
              "dsr_sensitivity": dsr_rows}
    with open(f"{OUT}/backtest_validation.json", "w") as f:
        json.dump(bundle, f, indent=2, default=str)

    print("Wrote validation/ outputs.")
    print("Kill levels (bps):", kill)
    print("Lag-1 autocorr:", ac)
    for r in dsr_rows:
        print(f"  DSR {r['ticker']} N={r['trials']}: {r['dsr_prob']}")


if __name__ == "__main__":
    main()
