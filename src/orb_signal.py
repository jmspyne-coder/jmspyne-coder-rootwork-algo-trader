"""
Opening Range Breakout (ORB) Signal Generator.

Pure signal logic — no execution, no side effects.
Takes candle data, returns a signal dict or None.
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from config import settings


@dataclass
class ORBSignal:
    """Represents a trading signal from the ORB strategy."""
    direction: str          # "long" or "short"
    entry_price: float      # breakout price (ORH or ORL)
    stop_price: float       # stop-loss level
    target_price: float     # take-profit level
    or_high: float          # opening range high
    or_low: float           # opening range low
    or_midline: float       # midline of opening range
    range_width: float      # absolute width
    range_pct: float        # width as % of midline
    atr: float | None       # ATR if available
    timestamp: str          # when signal was generated


def calculate_atr(daily_bars: pd.DataFrame, period: int = 14) -> float:
    """Calculate Average True Range from daily OHLC bars."""
    if len(daily_bars) < period + 1:
        return None
    high = daily_bars["high"].values
    low = daily_bars["low"].values
    close = daily_bars["close"].values
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ),
    )
    atr = pd.Series(tr).rolling(window=period).mean().iloc[-1]
    return float(atr)


def compute_opening_range(
    intraday_bars: pd.DataFrame,
    or_minutes: int = None,
) -> dict | None:
    """
    Compute the opening range from intraday 1-min bars.
    Returns dict with or_high, or_low, or_midline, range_width, range_pct.
    """
    or_minutes = or_minutes or settings.OPENING_RANGE_MINUTES

    # Filter to market hours
    market_bars = intraday_bars.between_time("09:30", "15:59")
    if market_bars.empty:
        return None

    # Opening range = first N minutes
    open_time = market_bars.index[0]
    or_end = open_time + pd.Timedelta(minutes=or_minutes)
    or_bars = market_bars[market_bars.index < or_end]

    if len(or_bars) < max(1, or_minutes - 1):
        return None

    or_high = float(or_bars["high"].max())
    or_low = float(or_bars["low"].min())
    or_midline = (or_high + or_low) / 2
    range_width = or_high - or_low
    range_pct = range_width / or_midline if or_midline > 0 else 0

    return {
        "or_high": or_high,
        "or_low": or_low,
        "or_midline": or_midline,
        "range_width": range_width,
        "range_pct": range_pct,
        "or_end": or_end,
    }


def generate_signal(
    intraday_bars: pd.DataFrame,
    atr: float | None = None,
    or_minutes: int = None,
    rr_ratio: float = None,
    stop_mode: str = None,
    min_range_pct: float = None,
) -> ORBSignal | None:
    """
    Core signal generator. Scans post-opening-range bars for breakout.

    Returns an ORBSignal if a breakout occurs, None otherwise.
    Only returns the FIRST breakout of the day (max 1 signal per session).
    """
    or_minutes = or_minutes or settings.OPENING_RANGE_MINUTES
    rr_ratio = rr_ratio or settings.REWARD_RISK_RATIO
    stop_mode = stop_mode or settings.STOP_MODE
    min_range_pct = min_range_pct or settings.MIN_RANGE_PCT

    # Step 1: compute opening range
    orng = compute_opening_range(intraday_bars, or_minutes)
    if orng is None:
        return None

    # Step 2: filter — skip if range is too narrow (false breakout territory)
    if orng["range_pct"] < min_range_pct:
        return None

    # Step 3: scan post-OR bars for first breakout
    market_bars = intraday_bars.between_time("09:30", "15:44")
    post_or = market_bars[market_bars.index >= orng["or_end"]]

    for idx, row in post_or.iterrows():
        # Long breakout
        if row["high"] > orng["or_high"]:
            entry = orng["or_high"]
            if stop_mode == "atr" and atr is not None:
                stop = entry - (atr * settings.ATR_STOP_MULTIPLIER)
            else:
                stop = orng["or_midline"]
            risk = entry - stop
            target = entry + (risk * rr_ratio)
            return ORBSignal(
                direction="long",
                entry_price=entry,
                stop_price=stop,
                target_price=target,
                or_high=orng["or_high"],
                or_low=orng["or_low"],
                or_midline=orng["or_midline"],
                range_width=orng["range_width"],
                range_pct=orng["range_pct"],
                atr=atr,
                timestamp=str(idx),
            )

        # Short breakout
        if row["low"] < orng["or_low"]:
            entry = orng["or_low"]
            if stop_mode == "atr" and atr is not None:
                stop = entry + (atr * settings.ATR_STOP_MULTIPLIER)
            else:
                stop = orng["or_midline"]
            risk = stop - entry
            target = entry - (risk * rr_ratio)
            return ORBSignal(
                direction="short",
                entry_price=entry,
                stop_price=stop,
                target_price=target,
                or_high=orng["or_high"],
                or_low=orng["or_low"],
                or_midline=orng["or_midline"],
                range_width=orng["range_width"],
                range_pct=orng["range_pct"],
                atr=atr,
                timestamp=str(idx),
            )

    return None


def simulate_trade(
    signal: ORBSignal,
    intraday_bars: pd.DataFrame,
) -> dict:
    """
    Simulate a trade outcome for backtesting.
    Walks forward through bars after entry to determine if target or stop hit first.
    Returns trade result dict.
    """
    post_entry = intraday_bars[intraday_bars.index >= pd.Timestamp(signal.timestamp)]

    for idx, row in post_entry.iterrows():
        if signal.direction == "long":
            # Check stop first (conservative — assume worst case)
            if row["low"] <= signal.stop_price:
                pnl = signal.stop_price - signal.entry_price
                return _trade_result(signal, idx, signal.stop_price, pnl, "stop")
            if row["high"] >= signal.target_price:
                pnl = signal.target_price - signal.entry_price
                return _trade_result(signal, idx, signal.target_price, pnl, "target")
        else:  # short
            if row["high"] >= signal.stop_price:
                pnl = signal.entry_price - signal.stop_price
                return _trade_result(signal, idx, signal.stop_price, pnl, "stop")
            if row["low"] <= signal.target_price:
                pnl = signal.entry_price - signal.target_price
                return _trade_result(signal, idx, signal.target_price, pnl, "target")

    # EOD force close at last available price
    if not post_entry.empty:
        last_price = float(post_entry.iloc[-1]["close"])
        if signal.direction == "long":
            pnl = last_price - signal.entry_price
        else:
            pnl = signal.entry_price - last_price
        return _trade_result(signal, post_entry.index[-1], last_price, pnl, "eod_close")

    return _trade_result(signal, signal.timestamp, signal.entry_price, 0, "no_data")


def _trade_result(signal: ORBSignal, exit_time, exit_price, pnl, exit_reason) -> dict:
    return {
        "direction": signal.direction,
        "entry_price": signal.entry_price,
        "stop_price": signal.stop_price,
        "target_price": signal.target_price,
        "exit_price": exit_price,
        "exit_time": str(exit_time),
        "entry_time": signal.timestamp,
        "pnl_per_share": round(pnl, 4),
        "exit_reason": exit_reason,
        "or_high": signal.or_high,
        "or_low": signal.or_low,
        "range_pct": round(signal.range_pct, 6),
        "atr": signal.atr,
    }
