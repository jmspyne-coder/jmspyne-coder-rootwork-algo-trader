# Bot Failure Modes (Part E)

Current handling status of each known failure mode. "Go-live blocker" means it
must be resolved before paper trading begins. Statuses reflect the code as of
this commit; anything needing the live account to confirm is noted, since the
Alpaca keys are currently deauthorized.

| Failure Mode | Severity | Current Status | Go-Live Blocker? |
|---|---|---|---|
| Orphaned bracket legs — entry fills but stop/target fails | Critical | **Partially handled.** `execute_orb` now verifies the bracket carries both protective legs right after submit (`verify_bracket_legs`) and alarms loudly if not. EOD flat-verify + reconcile are backstops. Auto-remediation of a confirmed naked fill is deferred to the paper period. | Mitigated |
| Network timeout during order — unknown position state | Critical | **Mitigated.** Deterministic `client_order_id` makes a retry idempotent at the broker (duplicate rejected). Idempotency check fails CLOSED. Reconcile + EOD flat-verify catch a stranded fill. True in-flight-timeout confirmation needs live testing. | Mitigated |
| Position carried overnight — failed EOD close | Critical | **Handled.** `end_of_day` force-closes, waits for settle, then re-verifies flat; if anything remains it force-closes again and alarms to close manually. | Resolved |
| Consecutive loss spiral — no pause mechanism | Medium | **Handled.** 5 consecutive losing days pauses trading for 2 trading days, then auto-resumes (`consec_loss_pause_active`). (The directive's "no pause mechanism" was out of date — one existed at 3 days; it is now 5 + 2-day pause.) | Resolved |
| Duplicate execution — GitHub Actions retries workflow | High | **Handled.** `client_order_id` = `orb-{ticker}-{date}`; broker rejects duplicates. Plus `has_order_today` guard (fails closed) and account-wide trade cap from broker truth. Workflow `concurrency` serializes identical triggers. | Resolved |
| Max account drawdown breach | Critical | **Handled.** 10% peak-to-current drawdown is a sticky halt requiring a manual `resume_trading` (`MAX_DRAWDOWN_PCT`). $200 on $2k. | Resolved |
| Catastrophic single-day loss | Critical | **Handled.** 50% daily floor flattens + sticky-halts (`risk_monitor`, `MAX_DAILY_LOSS_ABS_PCT`); 3% daily stop flattens + halts for the day. | Resolved |
| Stale data — IEX drops / incomplete opening range | High | **Partially handled.** Data-freshness and signal-freshness guards skip stale/late frames; opening range requires the full window. IEX-vs-SIP opening-range divergence is not yet quantified (see `docs/data_feed_audit.md`). | No (flag for paper period) |
| GitHub Actions cold-start miss — runner not up by 9:25 | Medium | **Alerted.** Independent 09:58 ET watchdog (`health_check`) alarms if execute_orb did not run. Deterministic timing would need a VPS/Pi cron (deferred). | No (missed trade, not lost money) |
| API rate limiting — Alpaca throttles at the open | Medium | **Not specifically handled.** Alpaca SDK has internal retry; a hard throttle would surface as an order/fetch error and alert. Watch during paper. | No (missed trade) |
| Account below margin minimum — equity < $2,000 | Medium | Not handled in code; Alpaca enforces margin minimums broker-side. | No |
| Adding to a losing position (DCA) | Critical | **Prevented by design.** One entry per symbol per day (idempotent `client_order_id`), bracket stop kills the position; no code path adds to a position. Verified: no averaging-down logic exists. See D7. | Resolved |

## Go-live blocker summary

All items marked "Resolved" or "Mitigated" above cover the directive's go-live
blockers (orphaned legs, network-timeout/unknown-state, overnight position,
consecutive-loss spiral, duplicate execution). The remaining Medium/High items
(cold-start miss, rate limiting, IEX-vs-SIP divergence) are exactly what the
paper period is for, and none of them lose money — they cost a missed trade or a
data-quality question, both observable in the daily report.

**Caveat:** the money-critical order-path items (orphan legs, network timeout,
EOD flat) are implemented but have NOT been exercised against a live account,
because the API keys are deauthorized. First real validation is a paper
smoke-test once keys are restored (see OPERATIONS.md §3).
