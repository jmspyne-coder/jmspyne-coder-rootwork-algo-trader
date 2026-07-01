"""
Paper-trading tracker (C4).

During the paper period we need the one number the reviewer cares about most:
realized slippage. Every reconciled trade has an intended entry (the opening-
range level the signal fired on: or_high for a long, or_low for a short) and an
actual fill (entry_price after reconciliation). The gap, in bps, is the live
slippage the 3-7 bps backtest assumption is being tested against.

This module has a pure, unit-tested core (realized_slippage_bps, daily_sharpe)
and a best-effort MotherDuck aggregation (get_paper_dashboard) that feeds the
daily email dashboard: Day N of 60, cumulative paper P&L, average realized
slippage, paper Sharpe, and trade count.

    python -m src.paper_stats            # print the current dashboard
"""
import math
from datetime import date

from config import settings


def realized_slippage_bps(direction: str, intended: float, actual: float) -> float | None:
    """Signed slippage COST in bps of the intended level. Positive = worse fill
    than intended (paid up on a long, sold lower on a short); negative = price
    improvement. None if inputs are unusable."""
    if not intended or intended <= 0 or actual is None:
        return None
    if direction == "long":
        return (actual - intended) / intended * 1e4
    if direction == "short":
        return (intended - actual) / intended * 1e4
    return None


def daily_sharpe(daily_pnls: list[float]) -> float:
    """Annualized Sharpe from a list of per-day P&L (already aggregated)."""
    n = len(daily_pnls)
    if n < 2:
        return 0.0
    mean = sum(daily_pnls) / n
    var = sum((x - mean) ** 2 for x in daily_pnls) / (n - 1)
    sd = math.sqrt(var)
    return (mean / sd * math.sqrt(252)) if sd > 0 else 0.0


def summarize(trades: list[dict]) -> dict:
    """Pure summary over reconciled trade rows. Each row needs: direction,
    or_high, or_low, entry_price (actual fill), trade_pnl, trade_date."""
    slips, by_day = [], {}
    for t in trades:
        intended = t["or_high"] if t["direction"] == "long" else t["or_low"]
        s = realized_slippage_bps(t["direction"], intended, t.get("entry_price"))
        if s is not None:
            slips.append(s)
        d = str(t.get("trade_date"))
        by_day[d] = by_day.get(d, 0.0) + float(t.get("trade_pnl") or 0.0)
    daily = list(by_day.values())
    return {
        "trades": len(trades),
        "days_traded": len(by_day),
        "cum_pnl": round(sum(daily), 2),
        "avg_slippage_bps": round(sum(slips) / len(slips), 2) if slips else None,
        "worst_slippage_bps": round(max(slips), 2) if slips else None,
        "paper_sharpe": round(daily_sharpe(daily), 2),
    }


def _elapsed_trading_days(start_iso: str, mode: str) -> int:
    """Distinct dates execute_orb has run since the paper start (from the run
    log heartbeat) — the honest 'Day N', counting days the bot actually ran."""
    try:
        from src.trade_logger import get_connection
        con = get_connection()
        row = con.execute(
            "SELECT COUNT(DISTINCT run_date) FROM algo_run_log "
            "WHERE step = 'execute_orb' AND mode = ? AND run_date >= ?",
            [mode, start_iso],
        ).fetchone()
        con.close()
        return int(row[0]) if row and row[0] else 0
    except Exception:
        return 0


def get_paper_dashboard(mode: str = "paper") -> dict | None:
    """Best-effort dashboard bundle for the daily email. Returns None on any
    failure so it can never break the EOD path."""
    start = settings.PAPER_TRADING_START
    target = settings.PAPER_TRADING_DAYS
    if not start:
        return None
    try:
        from src.trade_logger import get_connection
        con = get_connection()
        rows = con.execute(
            "SELECT direction, or_high, or_low, entry_price, trade_pnl, trade_date "
            "FROM algo_trade_log WHERE mode = ? AND trade_date >= ? "
            "AND exit_reason <> 'open' AND COALESCE(strategy,'') <> 'smoke_test'",
            [mode, start],
        ).fetchall()
        con.close()
    except Exception:
        return None
    trades = [{"direction": r[0], "or_high": r[1], "or_low": r[2],
               "entry_price": r[3], "trade_pnl": r[4], "trade_date": r[5]} for r in rows]
    s = summarize(trades)
    s["day_n"] = _elapsed_trading_days(start, mode)
    s["target_days"] = target
    s["backtest_sharpe_ref"] = settings.PAPER_BACKTEST_SHARPE_REF
    return s


def main():
    d = get_paper_dashboard()
    if not d:
        print("No paper dashboard (set ALGO_PAPER_START and ensure MotherDuck is reachable).")
        return
    print(f"Paper trading — Day {d['day_n']} of {d['target_days']}")
    print(f"  Trades: {d['trades']} over {d['days_traded']} day(s)")
    print(f"  Cumulative P&L: ${d['cum_pnl']:+,.2f}")
    print(f"  Avg realized slippage: {d['avg_slippage_bps']} bps "
          f"(worst {d['worst_slippage_bps']})")
    print(f"  Paper Sharpe: {d['paper_sharpe']} vs backtest ref {d['backtest_sharpe_ref']}")


if __name__ == "__main__":
    main()
