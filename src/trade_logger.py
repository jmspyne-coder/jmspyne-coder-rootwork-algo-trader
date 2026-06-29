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
            vwap_at_entry   DOUBLE,        -- v2 confirmation-filter telemetry
            rvol_at_entry   DOUBLE,
            candle_strength DOUBLE,
            filters_passed  VARCHAR,       -- comma-separated enabled filters that passed
            strategy        VARCHAR DEFAULT 'orb_v2',
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
    # Bring a pre-existing v1 algo_trade_log up to the v2 schema (idempotent).
    migrate_tables()


def migrate_tables():
    """
    Idempotently add the v2 columns to an already-existing algo_trade_log and
    flip the strategy default to 'orb_v2'. Safe to call repeatedly — uses
    ADD COLUMN IF NOT EXISTS. This is what the ALTER-in-MotherDuck step runs.
    """
    con = get_connection()
    con.execute("ALTER TABLE algo_trade_log ADD COLUMN IF NOT EXISTS vwap_at_entry DOUBLE;")
    con.execute("ALTER TABLE algo_trade_log ADD COLUMN IF NOT EXISTS rvol_at_entry DOUBLE;")
    con.execute("ALTER TABLE algo_trade_log ADD COLUMN IF NOT EXISTS candle_strength DOUBLE;")
    con.execute("ALTER TABLE algo_trade_log ADD COLUMN IF NOT EXISTS filters_passed VARCHAR;")
    con.execute("ALTER TABLE algo_trade_log ALTER COLUMN strategy SET DEFAULT 'orb_v2';")
    con.close()


def log_trade(
    trade_date: str,
    ticker: str,
    direction: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    shares: int,
    entry_time: str,
    exit_price: float | None = None,
    pnl_per_share: float | None = None,
    trade_pnl: float | None = None,
    exit_reason: str = "open",
    exit_time: str | None = None,
    or_high: float | None = None,
    or_low: float | None = None,
    range_pct: float | None = None,
    atr: float | None = None,
    equity_before: float | None = None,
    equity_after: float | None = None,
    vwap_at_entry: float | None = None,
    rvol_at_entry: float | None = None,
    candle_strength: float | None = None,
    filters_passed: str | None = None,
    strategy: str = "orb_v2",
    mode: str = "paper",
):
    """
    Log a single trade to MotherDuck.

    Designed to be called at ENTRY time (live path): exit_* fields default to
    None / 'open' since the bracket order resolves server-side later. The
    v2 confirmation-filter telemetry (vwap/rvol/candle_strength/filters_passed)
    is recorded for post-hoc analysis.
    """
    con = get_connection()
    con.execute("""
        INSERT INTO algo_trade_log (
            trade_date, ticker, direction, entry_price, stop_price,
            target_price, exit_price, shares, pnl_per_share, trade_pnl,
            exit_reason, entry_time, exit_time, or_high, or_low,
            range_pct, atr, equity_before, equity_after,
            vwap_at_entry, rvol_at_entry, candle_strength, filters_passed,
            strategy, mode
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        trade_date, ticker, direction, entry_price, stop_price,
        target_price, exit_price, shares, pnl_per_share, trade_pnl,
        exit_reason, entry_time, exit_time, or_high, or_low,
        range_pct, atr, equity_before, equity_after,
        vwap_at_entry, rvol_at_entry, candle_strength, filters_passed,
        strategy, mode,
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
