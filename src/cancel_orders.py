"""
Cancel all open orders (manual safety / cleanup).

Used to clear stray or leftover orders — e.g. an after-hours test order that
Alpaca queued for the next open. Manual workflow_dispatch only.
"""
from datetime import datetime
import pytz

from src.alpaca_client import get_trading_client, cancel_all_orders


def main():
    now = datetime.now(pytz.timezone("US/Eastern"))
    print(f"[CANCEL ORDERS] {now.strftime('%Y-%m-%d %H:%M ET')}")
    client = get_trading_client()
    resp = cancel_all_orders(client) or []
    print(f"  Requested cancel on {len(resp)} open order(s).")
    for r in resp:
        print(f"    {getattr(r, 'id', '?')}: HTTP {getattr(r, 'status', '?')}")
    print("  Done.")


if __name__ == "__main__":
    main()
