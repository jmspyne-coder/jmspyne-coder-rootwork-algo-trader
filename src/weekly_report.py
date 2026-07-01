"""
Weekly report (D1/D2 delivery): emails the P&L calendar, the leak-finder
breakdown, and the paper-trading dashboard in one message. Runs Friday after the
close (GitHub cron) or on demand (workflow_dispatch script=weekly_report).

This is what makes the leak-finder and calendar "update weekly" per the roadmap,
instead of only printing to the Actions log on a manual run. With zero trades it
sends an honest empty report rather than nothing.

    python -m src.weekly_report
"""
import io
from contextlib import redirect_stdout
from datetime import datetime

import pytz

from config import settings


def _leak_text(mode: str) -> str:
    """Capture the leak-finder's printed breakdown as text for the email."""
    try:
        from src.leakfinder import from_motherduck, analyze
        buf = io.StringIO()
        with redirect_stdout(buf):
            analyze(from_motherduck(mode))
        return buf.getvalue().strip() or "No resolved trades yet."
    except Exception as e:
        return f"Leak finder unavailable: {e}"


def _calendar_text(mode: str) -> str:
    try:
        from src.pnl_calendar import build_calendar, discipline_score, render
        from src.trade_logger import get_connection
        con = get_connection()
        summ = con.execute(
            "SELECT summary_date, SUM(daily_pnl) AS daily_pnl FROM algo_daily_summary "
            "WHERE mode = ? GROUP BY summary_date ORDER BY summary_date", [mode],
        ).fetch_df().to_dict("records")
        trades = con.execute(
            "SELECT exit_reason, strategy FROM algo_trade_log WHERE mode = ? "
            "AND COALESCE(strategy,'') <> 'smoke_test'", [mode],
        ).fetch_df().to_dict("records")
        con.close()
        return render(build_calendar(summ), discipline_score(trades)).strip()
    except Exception as e:
        return f"Calendar unavailable: {e}"


def _paper_text(mode: str) -> str:
    try:
        from src.paper_stats import get_paper_dashboard
        d = get_paper_dashboard(mode)
        if not d:
            return "Paper dashboard not configured (set ALGO_PAPER_START)."
        return (f"Day {d['day_n']}/{d['target_days']} | trades {d['trades']} | "
                f"cum P&L ${d['cum_pnl']:+,.2f} | avg slippage {d.get('avg_slippage_bps')} bps | "
                f"paper Sharpe {d['paper_sharpe']} vs backtest {d['backtest_sharpe_ref']}")
    except Exception as e:
        return f"Paper dashboard unavailable: {e}"


def main():
    mode = "paper" if settings.ALPACA_PAPER else "live"
    now = datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
    paper, cal, leak = _paper_text(mode), _calendar_text(mode), _leak_text(mode)
    print(f"[WEEKLY REPORT] {now} ({mode})")
    print(paper)

    from src.notifications import send_email, send_notification
    body = f"""<div style="font-family:sans-serif;padding:20px;background:#0f0f0f;color:#e5e5e5;border-radius:10px;max-width:680px;">
    <h2 style="color:#fff;">Weekly Report — {now} ({mode})</h2>
    <p style="color:#a0a0a0;">Paper: {paper}</p>
    <h3 style="color:#a0a0a0;">P&L Calendar</h3>
    <pre style="background:#1a1a1a;padding:12px;border-radius:8px;white-space:pre-wrap;font-size:12px;">{cal}</pre>
    <h3 style="color:#a0a0a0;">Leak Finder</h3>
    <pre style="background:#1a1a1a;padding:12px;border-radius:8px;white-space:pre-wrap;font-size:12px;">{leak}</pre>
    <p style="color:#666;font-size:11px;">Rootwork Algo Trader weekly digest</p>
    </div>"""
    send_email(f"Weekly Report {now} ({mode})", body)
    send_notification(f"*WEEKLY REPORT* {now}\n{paper}", ":calendar:")
    print("  Weekly report sent.")


if __name__ == "__main__":
    main()
