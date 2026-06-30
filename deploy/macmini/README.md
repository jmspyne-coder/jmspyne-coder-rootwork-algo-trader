# Mac Mini Deployment — Trading Trigger

This makes a Mac Mini the always-on clock that fires the trading workflow at the
right Eastern-time moments. It replaces the Windows Scheduled Tasks that trigger
the bot today.

## What it does (and deliberately does not do)

The Mac does **not** run the bot. The bot runs in GitHub Actions, where the
Alpaca and MotherDuck secrets live. The Mac only sends a tiny authenticated
`workflow_dispatch` three times per trading day:

| ~Time (ET) | Job | Purpose |
|---|---|---|
| 09:25 | `pre_market` | reset daily risk state |
| 09:40 | `execute_orb` | detect breakout, place the bracket order(s) |
| 15:45 | `end_of_day` | force-close, reconcile, write the daily summary |

Why a trigger and not a native install:

- **Secrets stay in GitHub.** This roaming machine only holds a token that can
  do one thing: start this one workflow.
- **The bot stays updatable.** Improvements ship by `git push`; the next run
  uses the new code automatically. Nobody has to touch this Mac again.
- **Timezone- and DST-proof.** `launchd` runs the dispatcher every ~2 minutes;
  the dispatcher self-gates on real Eastern time. It works wherever the Mac is
  and whoever moves it. No assumption about the Mac's own clock.
- **Bad-timing-proof.** Even if a dispatch landed late, `execute_orb` has its
  own 09:36–09:55 ET freshness guard and will skip rather than chase a stale
  fill. The Mac firing on time is belt; the guard is suspenders.

## One-time setup (do this today, with the Mac in front of you)

### 1. Make a GitHub token

On github.com (signed in as the account that owns the repo):

Settings → Developer settings → Personal access tokens → **Fine-grained tokens**
→ Generate new token.

- **Name:** `rootwork-macmini-trigger`
- **Expiration:** 1 year (set a calendar reminder to rotate)
- **Resource owner:** the repo owner account
- **Repository access:** Only select repositories → **rootwork-algo-trader**
- **Repository permissions → Actions: Read and write** (Metadata: Read is added
  automatically). Nothing else is needed.
- Generate, and copy the token (starts `github_pat_...`). You see it once.

### 2. Run the setup script

Get `setup.sh` (this folder) onto the Mac — easiest is to open the file on
github.com, click **Raw**, Save to Downloads — then in Terminal:

```bash
bash ~/Downloads/setup.sh
```

It asks you to paste the token (hidden input), verifies it against GitHub,
installs the dispatcher, and schedules it. Re-running is safe.

### 3. Make it bulletproof (unattended-proof)

```bash
sudo pmset -a sleep 0 disksleep 0 womp 1     # never sleep; wake on network
```

Then **System Settings → Users & Groups → Automatically log in as** this user,
so the trigger comes back by itself after a power blip or reboot. (`launchd`
user agents only run while the user is logged in.)

**Important — FileVault:** if FileVault disk encryption is on (the macOS
default), the OS **disables auto-login**, so after a reboot the Mac sits at the
unlock screen, nobody is logged in, and the trigger never runs. For an
unattended box either (a) turn FileVault off (System Settings → Privacy &
Security → FileVault), or (b) accept that someone must unlock the Mac after any
reboot. This is the single most likely silent failure once the Mac is remote —
and exactly why the independent GitHub-cron health check exists: if the Mac is
dark, the 9:58 ET watchdog still fires and emails "TRIGGER DID NOT FIRE."

### 4. Verify

During market hours (09:30–16:00 ET):

```bash
bash ~/.local/bin/rootwork_dispatch.sh --now execute_orb
tail -f ~/.local/state/rootwork/dispatch.log     # expect: dispatch execute_orb -> 204
```

Then confirm a new **Trading Schedule** run appears in the repo's Actions tab,
and that it logged to MotherDuck:

```sql
SELECT * FROM algo_trade_log     ORDER BY created_at DESC LIMIT 5;
SELECT * FROM algo_daily_summary ORDER BY summary_date DESC LIMIT 5;
```

## Cutover (so only one machine triggers)

Once the Mac is verified, stop the Windows PC from also firing, or the workflow
runs twice (the bot's idempotency guard prevents double *trades*, but you get
duplicate runs and emails). On the Windows PC, in PowerShell:

```powershell
Disable-ScheduledTask -TaskName RootworkAlgo-premarket
Disable-ScheduledTask -TaskName RootworkAlgo-execute
Disable-ScheduledTask -TaskName RootworkAlgo-eod
```

Re-enable with `Enable-ScheduledTask` if you ever want the PC as backup.

## Day-to-day operations

- **Logs:** `~/.local/state/rootwork/dispatch.log` (one line per dispatch),
  plus `launchd.out` / `launchd.err` in the same folder.
- **Pause the trigger:** `launchctl unload ~/Library/LaunchAgents/com.rootwork.algotrader.plist`
- **Resume:** `launchctl load -w ~/Library/LaunchAgents/com.rootwork.algotrader.plist`
- **Change times / windows:** edit `~/.local/bin/rootwork_dispatch.sh`
  (the `fire ...` lines), then unload + load.
- **Rotate / revoke the token:** replace `~/.config/rootwork/gh_token`, or
  delete the token on github.com if the Mac is ever lost. Revoking it instantly
  kills this machine's ability to start the workflow. Paper-only either way.

## Notes

- Weekends are skipped. Market holidays still dispatch but no-op safely
  server-side (no data → no trade; no positions → nothing to close).
- The GitHub Actions `schedule` crons in the workflow are left in place as a
  weak fallback; they usually no-op via the in-workflow timeguard. The external
  trigger (this Mac) is the reliable path.
- Paper trading only (`ALPACA_PAPER='true'` is set in the workflow). Going to
  real money is a separate, deliberate change — not anything on this Mac.
