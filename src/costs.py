"""
Transaction cost model for the backtest.

A trade is two fills: an entry and an exit. Each fill pays slippage plus
half the bid/ask spread (you buy at the ask, sell at the bid), expressed
in basis points of price, plus a flat per-share commission.

Costs are modeled per share and as a fraction of price (bps) rather than
in cents, so they scale correctly across price levels (SPY near $500 vs
TQQQ near $70). The same function is reused by the live drift check later
so backtest and live speak the same cost language.

Conservative simplification: slippage is applied to both legs uniformly,
including limit-style target exits that in practice fill at or better
than the limit. That slightly over-penalizes winners, which is the safe
direction when the question is "does the edge survive costs."

With BACKTEST_COSTS_ENABLED false (or every cost param 0) the round-trip
cost is exactly 0.0, so net equals gross and v1 results reproduce.
"""
from config import settings


def per_leg_cost_per_share(price: float) -> float:
    """Cost of a single fill (one leg) for one share, in dollars."""
    if not settings.BACKTEST_COSTS_ENABLED:
        return 0.0
    slippage = settings.BACKTEST_SLIPPAGE_BPS / 10_000.0 * price
    half_spread = (settings.BACKTEST_SPREAD_BPS / 2.0) / 10_000.0 * price
    return slippage + half_spread + settings.BACKTEST_COMMISSION_PER_SHARE


def round_trip_cost_per_share(price: float) -> float:
    """Total cost of entering and exiting one share, in dollars.

    Priced off the entry level for both legs. Intraday moves are small
    relative to the bps involved, so using entry price for the exit leg
    is a negligible approximation and keeps the cost deterministic.
    """
    return 2.0 * per_leg_cost_per_share(price)
