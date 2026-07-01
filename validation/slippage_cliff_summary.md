# Slippage Cliff (B1)

Net Sharpe vs assumed round-trip slippage (bps), on the committed 5m ORB trade sets. `round_trip_bps = 2*slippage + spread`; recomputed off the cost-free gross P&L. The kill level is where net Sharpe crosses zero.

| bps | SPY net Sharpe | QQQ net Sharpe |
|---|---|---|
| 0 | 3.06 | 4.27 |
| 3 | 2.65 | 3.81 |
| 5 | 2.37 | 3.51 |
| 7 | 2.10 | 3.21 |
| 10 | 1.69 | 2.75 |
| 15 | 1.01 | 1.99 |
| 20 | 0.33 | 1.22 |
| 25 | -0.34 | 0.46 |
| 30 | -1.01 | -0.31 |
| 35 | -1.68 | -1.08 |
| 40 | -2.34 | -1.85 |

- **SPY kill level:** ~22.5 bps round trip (net Sharpe crosses zero)
- **QQQ kill level:** ~28.0 bps round trip (net Sharpe crosses zero)

Context: an independent ORB clone (TastyTrading, TQQQ/SQQQ) reports its edge going to zero near 15 bps. The reviewer should judge whether the kill level here is reachable for QQQ/SPY market orders at 09:40 ET.
