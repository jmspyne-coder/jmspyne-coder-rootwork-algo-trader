"""
MotherDuck Trade Logger.

Logs all trades and daily summaries to my_db for analysis.
Uses the same MotherDuck infrastructure as the Rootwork intelligence platform.
"""
import duckdb
from datetime import datetime
from config import settings


def get_connection():
    """Connect to MotherDuck."""
    return duckdb.connect(f"md:{settings.MOTHERDUCK_DB}?motherduck_token={settings.MOTHERDUCK_TOKEN}")


def init_tables():
    """Create trade log and daily summary tables if they don't exist."""
    con = get_connection()
    con.execute("""
        CREATE TABLE IF NOT EXISTS algo_trade_log (
            trade_id        VARCHAR DEFAULT uuid()::VARCHAR,
            trade_date      DATE,
            ticker          VARCHAR,
            direction       VARCHAR,       -- 'long' or 'short'
            entry_price     DOUBLE,
            stop_price      DOUBLE,
            target_price    DOUBLE,
            exit_price      DOUBLE,
            shares          INTEGER,
            pnl_per_share   DOUBLE,
            trade_pnl       DOUBLE,
            exit_reason     VARCHAR,       -- 'target', 'stop', 'eod_close'
            entry_time      TIMESTAMP,
            exit_time       TIMESTAMP,
            or_high         DOUBLE,
            or_low          DOUBLE,
            range_pct       DOUBLE,
            atr             DOUBLE,
            equity_before   DOUBLE,
            equity_after    DOUBLE,
            strategy        VARCHAR DEFAULT 'orb_v1',
            mode            VARCHAR DEFAULT 'paper',  -- 'paper' or 'live'
            created_at      TIMESTAMP DEFAULT now()
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS algo_daily_summary (
            summary_date          DATE PRIMARY KEY,
            ticker                VARCHAR,
            trades_taken          INTEGER,
            wins                  INTEGER,
            losses                INTEGER,
            daily_pnl             DOUBLE,
            equity_start          DOUBLE,
            equity_end            DOUBLE,
            max_drawdown_pct      DOUBLE,
            consecutive_losses    INTEGER,
            was_halted            BOOLEAN DEFAULT FALSE,
            halt_reason           VARCHAR,
            strategy              VARCHAR DEFAULT 'orb_v1',
            mode                  VARCHAR DEFAULT 'paper',
            created_at            TIMESTAMP DEFAULT now()
        );
    """)
    con.close()


def log_trade(
    trade_date: str,
    ticker: str,
    direction: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    exit_price: float,
    shares: int,
    pnl_per_share: float,
    trade_pnl: float,
    exit_reason: str,
    entry_time: str,
    exit_time: str,
    or_high: float,
    or_low: float,
    range_pct: float,
    atr: float | None,
    equity_before: float,
    equity_after: float,
    mode: str = "paper",
):
    """Log a single trade to MotherDuck."""
    con = get_connection()
    con.execute("""
        INSERT INTO algo_trade_log (
            trade_date, ticker, direction, entry_price, stop_price,
            target_price, exit_price, shares, pnl_per_share, trade_pnl,
            exit_reason, entry_time, exit_time, or_high, or_low,
            range_pct, atr, equity_before, equity_after, mode
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        trade_date, ticker, direction, entry_price, stop_price,
        target_price, exit_price, shares, pnl_per_share, trade_pnl,
        exit_reason, entry_time, exit_time, or_high, or_low,
        range_pct, atr, equity_before, equity_after, mode,
    ])
    con.close()


def log_daily_summary(
    summary_date: str,
    ticker: str,
    trades_taken: int,
    wins: int,
    losses: int,
    daily_pnl: float,
    equity_start: float,
    equity_end: float,
    max_drawdown_pct: float,
    consecutive_losses: int,
    was_halted: bool = False,
    halt_reason: str | None = None,
    mode: str = "paper",
):
    """Log end-of-day summary to MotherDuck."""
    con = get_connection()
    con.execute("""
        INSERT OR REPLACE INTO algo_daily_summary (
            summary_date, ticker, trades_taken, wins, losses, daily_pnl,
            equity_start, equity_end, max_drawdown_pct, consecutive_losses,
            was_halted, halt_reason, mode
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        summary_date, ticker, trades_taken, wins, losses, daily_pnl,
        equity_start, equity_end, max_drawdown_pct, consecutive_losses,
        was_halted, halt_reason, mode,
    ])
    con.close()


def get_recent_performance(days: int = 30) -> dict:
    """Pull recent performance summary for dashboard/alerts."""
    con = get_connection()
    result = con.execute(f"""
        SELECT
            count(*) as total_days,
            sum(trades_taken) as total_trades,
            sum(wins) as total_wins,
            sum(losses) as total_losses,
            sum(daily_pnl) as total_pnl,
            min(equity_end) as min_equity,
            max(equity_end) as max_equity,
            max(max_drawdown_pct) as worst_drawdown,
            avg(daily_pnl) as avg_daily_pnl
        FROM algo_daily_summary
        WHERE summary_date >= current_date - INTERVAL '{days} days'
    """).fetchone()
    con.close()
    if result:
        return {
            "total_days": result[0],
            "total_trades": result[1],
            "total_wins": result[2],
            "total_losses": result[3],
            "total_pnl": result[4],
            "min_equity": result[5],
            "max_equity": result[6],
            "worst_drawdown": result[7],
            "avg_daily_pnl": result[8],
        }
    return {}
