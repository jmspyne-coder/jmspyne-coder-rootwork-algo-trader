"""
Notification Module.

Sends trade alerts and daily summaries via Slack webhook.
Falls back to stdout if no webhook configured.
"""
import json
import requests
from config import settings


def send_notification(message: str, emoji: str = ":chart_with_upwards_trend:"):
    """Send a Slack notification. Falls back to print if no webhook."""
    print(f"[NOTIFY] {message}")

    if not settings.SLACK_WEBHOOK_URL:
        return

    payload = {
        "text": f"{emoji} *Rootwork Algo Trader*\n{message}",
    }
    try:
        resp = requests.post(
            settings.SLACK_WEBHOOK_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"  Slack error: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"  Slack exception: {e}")


def notify_trade_entry(ticker, direction, shares, entry, stop, target):
    msg = (
        f"*TRADE ENTRY* | `{ticker}` {direction.upper()}\n"
        f"Shares: {shares} | Entry: ${entry:.2f}\n"
        f"Stop: ${stop:.2f} | Target: ${target:.2f}"
    )
    emoji = ":rocket:" if direction == "long" else ":bear:"
    send_notification(msg, emoji)


def notify_trade_exit(ticker, direction, pnl, exit_reason, equity):
    result = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "SCRATCH"
    emoji = ":white_check_mark:" if pnl > 0 else ":x:" if pnl < 0 else ":heavy_minus_sign:"
    msg = (
        f"*TRADE EXIT* | `{ticker}` {direction.upper()} → {result}\n"
        f"P&L: ${pnl:+,.2f} | Reason: {exit_reason}\n"
        f"Equity: ${equity:,.2f}"
    )
    send_notification(msg, emoji)


def notify_daily_summary(date, trades, wins, losses, pnl, equity, drawdown):
    emoji = ":moneybag:" if pnl > 0 else ":rotating_light:" if pnl < -100 else ":page_facing_up:"
    msg = (
        f"*DAILY SUMMARY* | {date}\n"
        f"Trades: {trades} | W/L: {wins}/{losses}\n"
        f"Daily P&L: ${pnl:+,.2f} | Equity: ${equity:,.2f}\n"
        f"Drawdown: {drawdown:.1%}"
    )
    send_notification(msg, emoji)


def notify_risk_halt(reason):
    msg = f"*TRADING HALTED* :octagonal_sign:\nReason: {reason}"
    send_notification(msg, ":rotating_light:")


def notify_no_signal(ticker, date, reason="No breakout detected"):
    msg = f"*NO TRADE* | `{ticker}` | {date}\n{reason}"
    send_notification(msg, ":zzz:")
