"""
P&L calendar (D2): a daily green/red view with running monthly totals and a
discipline score, built from the live tables. Scaffolded to light up on the
first paper fill — with zero trades it prints an empty-but-valid calendar.

Pure builders (build_calendar, discipline_score) are unit-tested with synthetic
rows; the MotherDuck fetch is a thin wrapper so it runs in CI where the DB is
reachable (the local DuckDB MotherDuck extension is broken on this box).

    python -m src.pnl_calendar            # print the calendar for paper
"""
import argparse
from datetime import date

from config import settings

# Exit reasons the automated system produces. Anything else in the log implies a
# manual override / off-rule action, which lowers the discipline score.
SYSTEM_EXITS = {"stop", "target", "eod_close", "eod_force_close"}


def build_calendar(rows: list[dict]) -> dict:
    """rows: [{'summary_date': 'YYYY-MM-DD', 'daily_pnl': float}] (any order).
    Returns {month 'YYYY-MM': {days:[{date,pnl,cum}], total, green, red,
    best, worst}} with a per-month running cumulative."""
    by_month: dict[str, list[dict]] = {}
    for r in rows:
        d = str(r["summary_date"])[:10]
        by_month.setdefault(d[:7], []).append({"date": d, "pnl": float(r["daily_pnl"] or 0.0)})
    out = {}
    for month, days in sorted(by_month.items()):
        days.sort(key=lambda x: x["date"])
        cum = 0.0
        for x in days:
            cum += x["pnl"]
            x["cum"] = round(cum, 2)
        pnls = [x["pnl"] for x in days]
        out[month] = {
            "days": days,
            "total": round(sum(pnls), 2),
            "green": sum(1 for p in pnls if p > 0),
            "red": sum(1 for p in pnls if p < 0),
            "best": round(max(pnls), 2) if pnls else 0.0,
            "worst": round(min(pnls), 2) if pnls else 0.0,
        }
    return out


def discipline_score(trades: list[dict]) -> dict:
    """Fraction of resolved trades that exited via a system rule (stop/target/EOD)
    on the expected strategy — i.e. no manual override / off-rule action. The bot
    has no manual-entry path, so this should stay ~1.0; a dip flags anomalies."""
    resolved = [t for t in trades if (t.get("exit_reason") or "open") != "open"]
    if not resolved:
        return {"resolved": 0, "disciplined": 0, "score": None}
    ok = sum(1 for t in resolved
             if (t.get("exit_reason") in SYSTEM_EXITS
                 and (t.get("strategy") or "orb_v2") in ("orb_v2", "orb_v1")))
    return {"resolved": len(resolved), "disciplined": ok, "score": round(ok / len(resolved), 4)}


def render(cal: dict, disc: dict) -> str:
    lines = ["# P&L Calendar\n"]
    if not cal:
        lines.append("_No trading days recorded yet. This populates on the first "
                     "end-of-day summary._\n")
    running = 0.0
    for month, m in cal.items():
        lines.append(f"\n## {month}  (net ${m['total']:+,.2f} · {m['green']}G/{m['red']}R · "
                     f"best ${m['best']:+,.2f} / worst ${m['worst']:+,.2f})\n")
        lines.append("| date | day P&L | month cum |")
        lines.append("|---|---|---|")
        for x in m["days"]:
            mark = "▲" if x["pnl"] > 0 else "▼" if x["pnl"] < 0 else "—"
            lines.append(f"| {x['date']} | {mark} ${x['pnl']:+,.2f} | ${x['cum']:+,.2f} |")
        running += m["total"]
    if cal:
        lines.append(f"\n**Running total across all months: ${running:+,.2f}**")
    s = disc.get("score")
    lines.append(f"\n**Discipline:** " + (
        f"{s:.0%} ({disc['disciplined']}/{disc['resolved']} trades exited by rule)"
        if s is not None else "no resolved trades yet"))
    return "\n".join(lines) + "\n"


def _fetch(mode: str):
    from src.trade_logger import get_connection
    con = get_connection()
    summ = con.execute(
        "SELECT summary_date, SUM(daily_pnl) AS daily_pnl FROM algo_daily_summary "
        "WHERE mode = ? GROUP BY summary_date ORDER BY summary_date", [mode],
    ).fetch_df().to_dict("records")
    trades = con.execute(
        "SELECT exit_reason, strategy FROM algo_trade_log "
        "WHERE mode = ? AND COALESCE(strategy,'') <> 'smoke_test'", [mode],
    ).fetch_df().to_dict("records")
    con.close()
    return summ, trades


def main():
    ap = argparse.ArgumentParser(description="P&L calendar")
    ap.add_argument("--mode", default="paper")
    a = ap.parse_args()
    summ, trades = _fetch(a.mode)
    print(render(build_calendar(summ), discipline_score(trades)))


if __name__ == "__main__":
    main()
