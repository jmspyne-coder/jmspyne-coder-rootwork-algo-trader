"""
Withdrawal discipline (D6) — recommend sweeping profit to a non-trading account
so gains are not perpetually re-risked ("let it ride" failure mode).

RECOMMEND-ONLY and OFF by default. This never moves money: it computes the
recommended sweep and emails it for a manual transfer. Automating money-out is
deliberately not done — a bug that wires funds is far worse than a missed sweep.
Enable (ALGO_WITHDRAWAL_ENABLED=true) only once the account is live and
profitable; run it on a cadence (e.g. month-end) via workflow_dispatch.

    python -m src.withdrawal            # print/notify the recommendation

Pure core (should_sweep) is unit-tested.
"""
from config import settings


def should_sweep(equity: float, base_capital: float,
                 excess_pct: float, sweep_frac: float) -> dict:
    """Given current equity and the base capital, decide whether a sweep is due.
    A sweep triggers when equity > base * (1 + excess_pct); the recommended
    amount is sweep_frac of the excess over base. Pure."""
    if base_capital <= 0:
        return {"trigger": False, "excess": 0.0, "sweep": 0.0, "threshold": 0.0}
    threshold = base_capital * (1 + excess_pct)
    excess = max(equity - base_capital, 0.0)
    trigger = equity > threshold
    return {
        "trigger": trigger,
        "threshold": round(threshold, 2),
        "excess": round(excess, 2),
        "sweep": round(excess * sweep_frac, 2) if trigger else 0.0,
    }


def main():
    from src.alpaca_client import get_effective_equity
    from src.notifications import send_email, send_notification
    equity = get_effective_equity()
    r = should_sweep(equity, settings.WITHDRAWAL_BASE_CAPITAL,
                     settings.WITHDRAWAL_EXCESS_PCT, settings.WITHDRAWAL_SWEEP_FRAC)
    print(f"[WITHDRAWAL] equity ${equity:,.2f} vs base ${settings.WITHDRAWAL_BASE_CAPITAL:,.2f} "
          f"| threshold ${r['threshold']:,.2f} | trigger={r['trigger']} | "
          f"recommended sweep ${r['sweep']:,.2f}")
    if not settings.WITHDRAWAL_ENABLED:
        print("  Withdrawal discipline is OFF (recommend-only tool; enable when live+profitable).")
        return
    if not r["trigger"]:
        print("  Below threshold — no sweep recommended.")
        return
    msg = (f"*WITHDRAWAL RECOMMENDED* :moneybag:\nEquity ${equity:,.2f} is above "
           f"${r['threshold']:,.2f}. Consider moving ${r['sweep']:,.2f} "
           f"(50% of the ${r['excess']:,.2f} excess) to a non-trading account. Manual transfer.")
    send_notification(msg, ":moneybag:")
    send_email(
        f"💰 Sweep recommended: ${r['sweep']:,.2f}",
        f"""<div style="font-family:sans-serif;padding:20px;background:#1a1a1a;color:#e5e5e5;border-radius:8px;">
        <h2 style="color:#22c55e;">Withdrawal discipline</h2>
        <p>Effective equity <strong>${equity:,.2f}</strong> is above the
        ${r['threshold']:,.2f} threshold ({settings.WITHDRAWAL_EXCESS_PCT:.0%} over the
        ${settings.WITHDRAWAL_BASE_CAPITAL:,.0f} base).</p>
        <p><strong>Recommended sweep: ${r['sweep']:,.2f}</strong> (50% of the
        ${r['excess']:,.2f} excess). Move it manually to a non-trading account — the
        system does not transfer funds automatically.</p>
        </div>""",
    )


if __name__ == "__main__":
    main()
