"""
Gap-Fill (GAP_FILL v1) signal generator — mean-reversion complement to ORB.

Thesis: overnight gaps on QQQ reflect low-liquidity pre-market/futures moves.
When the full-liquidity cash session opens, price tends to revert toward the
prior close. We FADE the gap: gap-up -> short, gap-down -> long, entering at the
open and targeting a partial fill.

Pure signal logic, no execution, mirrors src/orb_signal.py in shape so the
backtester and risk controls reuse the same plumbing. Mutually exclusive with
ORB by gap size via route_strategy().

STATUS: pending backtest. Parameters are defaults to sweep, not validated.
"""
import pandas as pd
from dataclasses import dataclass

from config import settings


@dataclass
class GapFillSignal:
    direction: str          # "long" (fade gap-down) or "short" (fade gap-up)
    entry_price: float      # market at (or just after) the open
    stop_price: float       # ATR-based, tighter than ORB (1.0x default)
    target_price: float     # R-multiple toward the prior close
    prev_close: float
    today_open: float
    gap_pct: float          # signed (today_open - prev_close) / prev_close
    atr: float
    timestamp: str          # entry bar timestamp


def detect_gap(prev_close: float | None, today_open: float | None) -> float | None:
    """Signed overnight gap as a fraction of prior close. None if unusable."""
    if not prev_close or prev_close <= 0 or today_open is None:
        return None
    return (today_open - prev_close) / prev_close


def min_gap_threshold(atr: float | None, prev_close: float,
                      atr_mult: float, pct_floor: float) -> float:
    """The lower gap bound: max(atr_mult * ATR/prev_close, pct_floor). Falls back
    to the pct floor when ATR is unavailable."""
    atr_component = (atr_mult * atr / prev_close) if (atr and prev_close > 0) else 0.0
    return max(atr_component, pct_floor)


def route_strategy(gap_pct: float | None, min_gap: float, max_gap: float) -> str:
    """Three-zone router (pure). Returns 'skip' | 'gap_fill' | 'orb'.
    'skip' = regime event (gap too big), 'gap_fill' = meaningful gap,
    'orb' = normal day. None gap (no prior close) -> 'orb' (ORB handles its own
    prerequisites)."""
    if gap_pct is None:
        return "orb"
    g = abs(gap_pct)
    if g >= max_gap:
        return "skip"
    if g >= min_gap:
        return "gap_fill"
    return "orb"


def _session(intraday_bars: pd.DataFrame, offset_min: int) -> pd.DataFrame:
    """RTH bars from the (offset-adjusted) open through the force-close cutoff."""
    day = intraday_bars.between_time("09:30", settings.FORCE_CLOSE_TIME)
    if day.empty:
        return day
    entry_time = day.index[0] + pd.Timedelta(minutes=max(offset_min, 0))
    return day[day.index >= entry_time]


def generate_gap_fill_signal(
    intraday_bars: pd.DataFrame,
    atr: float | None,
    prev_close: float | None,
    atr_mult: float = None,
    min_gap_pct: float = None,
    max_gap_pct: float = None,
    stop_mult: float = None,
    rr_ratio: float = None,
    entry_offset_min: int = None,
    direction_filter: str = None,
) -> GapFillSignal | None:
    """Return a GapFillSignal if today's gap is in the gap-fill zone and passes
    the direction filter, else None. None args fall back to config defaults."""
    atr_mult = settings.GAP_FILL_MIN_GAP_ATR_MULT if atr_mult is None else atr_mult
    min_gap_pct = settings.GAP_FILL_MIN_GAP_PCT if min_gap_pct is None else min_gap_pct
    max_gap_pct = settings.GAP_FILL_MAX_GAP_PCT if max_gap_pct is None else max_gap_pct
    stop_mult = settings.GAP_FILL_ATR_STOP_MULT if stop_mult is None else stop_mult
    rr_ratio = settings.GAP_FILL_RR_RATIO if rr_ratio is None else rr_ratio
    entry_offset_min = settings.GAP_FILL_ENTRY_OFFSET_MIN if entry_offset_min is None else entry_offset_min
    direction_filter = (direction_filter or settings.GAP_FILL_DIRECTION or "both").lower()

    # ATR is required (the whole trade is sized off an ATR stop).
    if atr is None or prev_close is None or prev_close <= 0:
        return None

    session = _session(intraday_bars, entry_offset_min)
    if session.empty:
        return None
    entry_bar = session.iloc[0]
    entry_ts = session.index[0]
    today_open = float(entry_bar["open"])

    gap_pct = detect_gap(prev_close, today_open)
    if gap_pct is None:
        return None
    g = abs(gap_pct)
    min_gap = min_gap_threshold(atr, prev_close, atr_mult, min_gap_pct)
    if g < min_gap or g > max_gap_pct:
        return None  # not a gap-fill day (normal day -> ORB, or regime event -> skip)

    # Fade the gap.
    direction = "short" if gap_pct > 0 else "long"
    if direction_filter == "up" and direction != "short":
        return None   # up-only = only fade gap-ups (short)
    if direction_filter == "down" and direction != "long":
        return None   # down-only = only fade gap-downs (long)

    entry = today_open
    risk = atr * stop_mult
    if risk <= 0:
        return None
    if direction == "long":
        stop = entry - risk
        target = entry + risk * rr_ratio
    else:
        stop = entry + risk
        target = entry - risk * rr_ratio

    return GapFillSignal(
        direction=direction, entry_price=entry, stop_price=stop, target_price=target,
        prev_close=prev_close, today_open=today_open, gap_pct=gap_pct, atr=atr,
        timestamp=str(entry_ts),
    )


def simulate_gap_fill_trade(signal: GapFillSignal, intraday_bars: pd.DataFrame) -> dict:
    """Walk forward from entry to the force-close, returning target/stop/EOD like
    src/orb_signal.simulate_trade. Stop is checked before target (conservative)."""
    day = intraday_bars.between_time("09:30", settings.FORCE_CLOSE_TIME)
    post_entry = day[day.index >= pd.Timestamp(signal.timestamp)]

    for idx, row in post_entry.iterrows():
        if signal.direction == "long":
            if row["low"] <= signal.stop_price:
                return _result(signal, idx, signal.stop_price, signal.stop_price - signal.entry_price, "stop")
            if row["high"] >= signal.target_price:
                return _result(signal, idx, signal.target_price, signal.target_price - signal.entry_price, "target")
        else:
            if row["high"] >= signal.stop_price:
                return _result(signal, idx, signal.stop_price, signal.entry_price - signal.stop_price, "stop")
            if row["low"] <= signal.target_price:
                return _result(signal, idx, signal.target_price, signal.entry_price - signal.target_price, "target")

    if not post_entry.empty:
        last = float(post_entry.iloc[-1]["close"])
        pnl = (last - signal.entry_price) if signal.direction == "long" else (signal.entry_price - last)
        return _result(signal, post_entry.index[-1], last, pnl, "eod_close")
    return _result(signal, signal.timestamp, signal.entry_price, 0.0, "no_data")


def _result(signal: GapFillSignal, exit_time, exit_price, pnl, reason) -> dict:
    return {
        "strategy": "gap_fill",
        "direction": signal.direction,
        "entry_price": signal.entry_price,
        "stop_price": signal.stop_price,
        "target_price": signal.target_price,
        "exit_price": exit_price,
        "exit_time": str(exit_time),
        "entry_time": signal.timestamp,
        "pnl_per_share": round(pnl, 4),
        "exit_reason": reason,
        "prev_close": signal.prev_close,
        "today_open": signal.today_open,
        "gap_pct": round(signal.gap_pct, 6),
        "atr": signal.atr,
    }
