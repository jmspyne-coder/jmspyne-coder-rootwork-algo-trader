# Rootwork Algo Trader

Automated intraday ORB (Opening Range Breakout) trading system built on Alpaca + GitHub Actions + MotherDuck.

## Architecture

```
GitHub Actions (cron)
  ├── 9:25 ET  → pre_market.py   → fetch ATR, calc position size, write state
  ├── 9:35 ET  → execute_orb.py  → pull 5-min candles, detect breakout, submit bracket order
  └── 3:45 ET  → end_of_day.py   → force-close positions, log P&L, send summary
```

## Setup

### 1. Alpaca Paper Account
- Sign up at https://alpaca.markets
- Create paper trading account
- Generate API keys from dashboard

### 2. MotherDuck
- Uses existing `my_db` database
- Trade log table: `algo_trade_log`
- Daily summary table: `algo_daily_summary`

### 3. GitHub Secrets
```
ALPACA_API_KEY_ID
ALPACA_API_SECRET_KEY
MOTHERDUCK_TOKEN
SLACK_WEBHOOK_URL (optional)
```

### 4. Local Development
```bash
pip install -r requirements.txt
# Backtest mode
python -m src.backtest --ticker TQQQ --start 2024-01-01 --end 2026-06-01
# Paper trade (manual trigger)
python -m src.execute_orb --paper
```

## Strategy: Opening Range Breakout (ORB)

1. Define high/low of first N minutes after open (default: 5 min)
2. If price breaks above ORH → long entry with bracket order
3. If price breaks below ORL → short entry with bracket order
4. Stop: midline of opening range (or ATR-based)
5. Target: 2:1 reward-to-risk ratio
6. Force-close all positions 15 min before market close

## Risk Controls

| Control              | Default     |
|----------------------|-------------|
| Per-trade risk       | 1.5%        |
| Daily loss limit     | 4%          |
| Consecutive losses   | 3 → pause   |
| Max drawdown         | 12% → halt  |
| Max trades/day       | 2           |
| EOD force-close      | 3:45 PM ET  |
