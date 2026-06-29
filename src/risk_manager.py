"""
Risk Management Module.

Enforces all risk controls before and during trading.
This is the module that keeps you from blowing up.
"""
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from config import settings
from src.costs import round_trip_cost_per_share


@dataclass
class RiskState:
    """Tracks risk state across the trading session."""
    peak_equity: float
    current_equity: float
    daily_starting_equity: float
    daily_pnl: float
    consecutive_losses: int
    trades_today: int
    is_halted: bool
    halt_reason: str | None

    @property
    def current_drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0
        return (self.peak_equity - self.current_equity) / self.peak_equity

    @property
    def daily_loss_pct(self) -> float:
        if self.daily_starting_equity <= 0:
            return 0
        return -self.daily_pnl / self.daily_starting_equity if self.daily_pnl < 0 else 0


STATE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "config", "risk_state.json"
)


def load_risk_state(equity: float | None = None) -> RiskState:
    """Load persisted risk state or initialize fresh."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            return RiskState(**data)

    eq = equity or 10000.0
    return RiskState(
        peak_equity=eq,
        current_equity=eq,
        daily_starting_equity=eq,
        daily_pnl=0.0,
        consecutive_losses=0,
        trades_today=0,
        is_halted=False,
        halt_reason=None,
    )


def save_risk_state(state: RiskState):
    """Persist risk state between runs."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(asdict(state), f, indent=2)


def reset_daily_state(state: RiskState, current_equity: float) -> RiskState:
    """Called at start of each trading day."""
    state.daily_starting_equity = current_equity
    state.current_equity = current_equity
    state.daily_pnl = 0.0
    state.trades_today = 0
    # Update peak if we made new highs
    if current_equity > state.peak_equity:
        state.peak_equity = current_equity
    # Clear daily halt (but not drawdown halt)
    if state.halt_reason in ("daily_loss_limit", "consecutive_losses", "max_trades"):
        state.is_halted = False
        state.halt_reason = None
    return state


# ─── Pre-Trade Checks ────────────────────────────────────────────────

def can_trade(state: RiskState) -> tuple[bool, str]:
    """
    Run all pre-trade risk checks. Returns (allowed, reason).
    Call this BEFORE submitting any order.
    """
    if state.is_halted:
        return False, f"Trading halted: {state.halt_reason}"

    if state.trades_today >= settings.MAX_TRADES_PER_DAY:
        state.is_halted = True
        state.halt_reason = "max_trades"
        save_risk_state(state)
        return False, f"Max trades/day reached ({settings.MAX_TRADES_PER_DAY})"

    if state.daily_loss_pct >= settings.MAX_DAILY_LOSS_PCT:
        state.is_halted = True
        state.halt_reason = "daily_loss_limit"
        save_risk_state(state)
        return False, f"Daily loss limit hit ({state.daily_loss_pct:.1%})"

    if state.consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
        state.is_halted = True
        state.halt_reason = "consecutive_losses"
        save_risk_state(state)
        return False, f"Consecutive loss limit ({settings.MAX_CONSECUTIVE_LOSSES})"

    if state.current_drawdown_pct >= settings.MAX_DRAWDOWN_PCT:
        state.is_halted = True
        state.halt_reason = "max_drawdown"
        save_risk_state(state)
        return False, f"Max drawdown hit ({state.current_drawdown_pct:.1%}) — MANUAL REVIEW REQUIRED"

    return True, "OK"


# ─── Position Sizing ─────────────────────────────────────────────────

def calculate_position_size(
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_pct: float = None,
) -> int:
    """
    ATR-aware position sizing: risk a fixed % of equity per trade.
    Position size = (equity * risk%) / (entry - stop distance)

    Returns number of shares (integer, rounds down).
    """
    risk_pct = risk_pct or settings.RISK_PER_TRADE_PCT
    risk_dollars = equity * risk_pct
    stop_distance = abs(entry_price - stop_price)

    if stop_distance <= 0:
        return 0

    shares = int(risk_dollars / stop_distance)

    # Sanity check: don't exceed buying power
    max_shares_by_capital = int(equity / entry_price)
    shares = min(shares, max_shares_by_capital)

    return max(shares, 0)


# ─── Post-Trade Updates ──────────────────────────────────────────────

def record_trade_result(state: RiskState, pnl: float, equity_after: float) -> RiskState:
    """Update risk state after a trade completes."""
    state.trades_today += 1
    state.daily_pnl += pnl
    state.current_equity = equity_after

    if pnl < 0:
        state.consecutive_losses += 1
    else:
        state.consecutive_losses = 0  # reset on any win

    if equity_after > state.peak_equity:
        state.peak_equity = equity_after

    save_risk_state(state)
    return state


# ─── Backtest Risk Simulation ────────────────────────────────────────

def simulate_risk_controls(
    trades: list[dict],
    initial_capital: float,
) -> list[dict]:
    """
    Apply risk controls to a list of backtest trades.
    Returns only the trades that would have been taken,
    plus equity curve data.
    """
    equity = initial_capital
    peak_equity = initial_capital
    consecutive_losses = 0
    daily_trades = {}
    executed_trades = []

    for trade in trades:
        trade_date = trade.get("entry_time", "")[:10]

        # Max trades per day
        daily_trades[trade_date] = daily_trades.get(trade_date, 0) + 1
        if daily_trades[trade_date] > settings.MAX_TRADES_PER_DAY:
            continue

        # Consecutive loss check
        if consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
            # Skip until next day
            if trade_date == (executed_trades[-1]["entry_time"][:10] if executed_trades else ""):
                continue
            consecutive_losses = 0  # new day, reset

        # Max drawdown check
        drawdown_pct = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        if drawdown_pct >= settings.MAX_DRAWDOWN_PCT:
            break  # full halt

        # Position sizing
        stop_dist = abs(trade["entry_price"] - trade["stop_price"])
        if stop_dist <= 0:
            continue
        shares = int((equity * settings.RISK_PER_TRADE_PCT) / stop_dist)
        if shares <= 0:
            continue

        # Daily loss check
        day_pnl = sum(
            t["trade_pnl"] for t in executed_trades
            if t["entry_time"][:10] == trade_date
        )
        if day_pnl < 0 and abs(day_pnl / equity) >= settings.MAX_DAILY_LOSS_PCT:
            continue

        # Execute. Round-trip costs are netted out of gross P&L. Net is
        # what drives equity, drawdown, and the win/loss classification:
        # a marginal gross win can flip to a net loss once costs are paid.
        gross_pnl = trade["pnl_per_share"] * shares
        cost = round_trip_cost_per_share(trade["entry_price"]) * shares
        net_pnl = gross_pnl - cost
        equity += net_pnl

        if equity > peak_equity:
            peak_equity = equity

        if net_pnl < 0:
            consecutive_losses += 1
        else:
            consecutive_losses = 0

        trade["shares"] = shares
        trade["gross_pnl"] = round(gross_pnl, 2)
        trade["cost"] = round(cost, 2)
        trade["trade_pnl"] = round(net_pnl, 2)
        trade["equity_after"] = round(equity, 2)
        trade["drawdown_pct"] = round(
            (peak_equity - equity) / peak_equity if peak_equity > 0 else 0, 4
        )
        executed_trades.append(trade)

    return executed_trades
