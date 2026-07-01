# Serial Correlation and Block Bootstrap (B2)

Lag-1 autocorrelation of the net-3bps daily P&L, and 95% Sharpe CIs from an IID bootstrap vs a moving-block bootstrap (block = 5 trading days, Kunsch 1989), 10,000 resamples each.

| ticker | lag-1 autocorr | IID 95% CI | block(5) 95% CI |
|---|---|---|---|
| SPY | 0.100 | [-2.05, 7.17] | [-1.57, 6.61] |
| QQQ | 0.062 | [1.51, 6.11] | [1.58, 6.01] |

Read: observed autocorrelation is low, so the block bootstrap does not materially widen the CI here (the usual 'IID is too narrow' warning applies in principle but is empirically small on this data). Literature: at phi~0.2-0.3 the IID CI understates by ~30-50%, up to ~2x at phi~0.6; we are well below that.
