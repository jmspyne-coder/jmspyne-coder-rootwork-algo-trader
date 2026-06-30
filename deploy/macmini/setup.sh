#!/bin/bash
# ============================================================================
# Rootwork Algo Trader — Mac Mini trigger setup (one-shot)
#
# Turns this Mac into the always-on clock that fires the trading workflow at the
# right Eastern-time moments. It does NOT run the bot — the bot runs in GitHub
# Actions with the Alpaca/MotherDuck secrets. This machine only sends a
# workflow_dispatch (a tiny authenticated POST) three times a trading day:
#
#     ~09:25 ET  pre_market     ~09:40 ET  execute_orb     ~15:45 ET  end_of_day
#
# It is timezone- and DST-proof: launchd runs the dispatcher every ~2 min and
# the dispatcher self-gates on actual Eastern time, so it works wherever the Mac
# physically lives and whoever moves it.
#
# Run it once, in Terminal:    bash setup.sh
# (Re-running is safe — it reloads cleanly and keeps an existing token.)
# ============================================================================
set -euo pipefail

OWNER="${ROOTWORK_OWNER:-jmspyne-coder}"
REPO="${ROOTWORK_REPO:-rootwork-algo-trader}"
WF="${ROOTWORK_WF:-trading_schedule.yml}"

CFG="$HOME/.config/rootwork"
BIN="$HOME/.local/bin"
STATE="$HOME/.local/state/rootwork"
LAUNCH="$HOME/Library/LaunchAgents"
PLIST="$LAUNCH/com.rootwork.algotrader.plist"
DISPATCH="$BIN/rootwork_dispatch.sh"

echo "== Rootwork Algo Trader — Mac Mini trigger setup =="
echo "   Repo:     $OWNER/$REPO"
echo "   Workflow: $WF"
echo
mkdir -p "$CFG" "$BIN" "$STATE" "$LAUNCH"

# ---- 1) GitHub token -------------------------------------------------------
# A fine-grained PAT scoped ONLY to this repo, Actions: Read and write.
if [ -n "${ROOTWORK_TOKEN:-}" ]; then
  printf '%s' "$ROOTWORK_TOKEN" > "$CFG/gh_token"
  echo "Token taken from ROOTWORK_TOKEN env var."
elif [ -f "$CFG/gh_token" ] && [ -s "$CFG/gh_token" ]; then
  echo "Existing token found at $CFG/gh_token — keeping it."
else
  printf "Paste the GitHub fine-grained token (input hidden), then press Enter:\n> "
  read -rs TOKEN; echo
  [ -n "$TOKEN" ] || { echo "No token entered. Aborting."; exit 1; }
  printf '%s' "$TOKEN" > "$CFG/gh_token"
fi
chmod 600 "$CFG/gh_token"

# ---- 2) config the dispatcher reads ---------------------------------------
cat > "$CFG/config" <<EOF
OWNER="$OWNER"
REPO="$REPO"
WF="$WF"
EOF
chmod 600 "$CFG/config"

# ---- 3) validate the token can see the workflow ---------------------------
echo "Checking the token against GitHub..."
code="$(curl -sS -m 30 -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $(cat "$CFG/gh_token")" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/$OWNER/$REPO/actions/workflows/$WF")" || code="000"
if [ "$code" != "200" ]; then
  echo
  echo "!! Token check FAILED (HTTP $code)."
  echo "   It must be a FINE-GRAINED token scoped to $OWNER/$REPO with:"
  echo "     Repository permissions -> Actions: Read and write"
  echo "     (Metadata: Read is added automatically)"
  echo "   Fix the token, then re-run this script. Nothing has been scheduled yet."
  exit 1
fi
echo "Token OK."

# ---- 4) the dispatcher -----------------------------------------------------
cat > "$DISPATCH" <<'DISPATCH_EOF'
#!/bin/bash
# Rootwork Algo Trader — ET-gated GitHub Actions dispatcher.
# Run every ~2 min by launchd. Self-gates on real Eastern time + a per-day
# lockfile so each job dispatches exactly once, regardless of this Mac's own
# timezone or DST. Manual test:  rootwork_dispatch.sh --now execute_orb
set -uo pipefail

CFG="$HOME/.config/rootwork"
STATE="$HOME/.local/state/rootwork"
mkdir -p "$STATE"
# shellcheck disable=SC1091
. "$CFG/config"                      # sets OWNER REPO WF
TOKEN="$(cat "$CFG/gh_token")"
LOG="$STATE/dispatch.log"

# Cap the log so it can't grow unbounded on an unattended machine.
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" 2>/dev/null || echo 0)" -gt 5000 ]; then
  tail -n 1000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
fi

dispatch () {
  local script="$1" resp
  resp="$(curl -sS -m 30 -o /dev/null -w '%{http_code}' -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/$OWNER/$REPO/actions/workflows/$WF/dispatches" \
    -d "{\"ref\":\"main\",\"inputs\":{\"script\":\"$script\"}}")" || resp="curl_error"
  echo "$(date '+%Y-%m-%d %H:%M:%S %Z') dispatch $script -> $resp" >> "$LOG"
  [ "$resp" = "204" ]
}

# Manual one-off:  rootwork_dispatch.sh --now <pre_market|execute_orb|end_of_day>
if [ "${1:-}" = "--now" ]; then
  dispatch "${2:?usage: --now <pre_market|execute_orb|end_of_day>}"
  exit $?
fi

ET_DOW="$(TZ=America/New_York date +%u)"     # 1=Mon .. 7=Sun
ET_HM="$(TZ=America/New_York date +%H:%M)"
ET_DATE="$(TZ=America/New_York date +%Y-%m-%d)"
[ "$ET_DOW" -ge 6 ] && exit 0                # weekends off (holidays no-op safely server-side)

find "$STATE" -name '*.done' -mtime +7 -delete 2>/dev/null

fire () {                                     # fire <script> <start_hhmm> <end_hhmm>
  local script="$1" start="$2" end="$3"
  [[ "$ET_HM" > "$start" || "$ET_HM" == "$start" ]] || return 0
  [[ "$ET_HM" < "$end"   || "$ET_HM" == "$end"   ]] || return 0
  local lock="$STATE/$ET_DATE.$script.done"
  [ -f "$lock" ] && return 0
  if dispatch "$script"; then touch "$lock"; fi
}

# Windows are wider than the launchd interval so a tick is guaranteed to land
# inside. execute_orb dispatches early enough that, even with Actions queue lag,
# the code runs inside its own 09:36-09:46 ET entry window + bar-freshness guard.
# Holidays/half-days are handled server-side by the code's market-calendar gate.
fire pre_market  09:24 09:34
fire execute_orb 09:38 09:43
fire end_of_day  15:44 15:54
exit 0
DISPATCH_EOF
chmod 700 "$DISPATCH"

# ---- 5) launchd agent ------------------------------------------------------
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.rootwork.algotrader</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$DISPATCH</string>
  </array>
  <key>StartInterval</key><integer>120</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$STATE/launchd.out</string>
  <key>StandardErrorPath</key><string>$STATE/launchd.err</string>
</dict>
</plist>
EOF

# ---- 6) (re)load (bootstrap on modern macOS; VERIFY it actually loaded) -----
# `launchctl load -w` is deprecated and can return 0 while scheduling nothing.
# Use bootstrap, then assert the agent is really loaded, and fail loudly if not
# (a silent no-op on a remote machine is the worst case).
UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM/com.rootwork.algotrader" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST" 2>/dev/null \
  || launchctl load -w "$PLIST" 2>/dev/null || true
launchctl kickstart "gui/$UID_NUM/com.rootwork.algotrader" 2>/dev/null || true
if ! launchctl print "gui/$UID_NUM/com.rootwork.algotrader" >/dev/null 2>&1 \
   && ! launchctl list | grep -q com.rootwork.algotrader; then
  echo "!! The launchd agent did NOT load — NOTHING is scheduled."
  echo "   Check: launchctl print gui/$UID_NUM/com.rootwork.algotrader"
  exit 1
fi
echo "launchd agent loaded and verified."

echo
echo "Installed and scheduled. The trigger now runs every 2 minutes and will"
echo "dispatch pre_market / execute_orb / end_of_day at the right ET times,"
echo "Mon-Fri, automatically."
echo
echo "NEXT (do these so it survives reboots and never sleeps):"
echo "  1. Never sleep:   sudo pmset -a sleep 0 disksleep 0 womp 1"
echo "  2. Auto-login:    System Settings -> Users & Groups -> Automatically log in as <this user>"
echo
echo "VERIFY now (during market hours it fires one real paper run immediately):"
echo "  bash $DISPATCH --now execute_orb"
echo "  tail -f $STATE/dispatch.log      # expect: dispatch execute_orb -> 204"
echo "  ...then check the repo Actions tab for a new 'Trading Schedule' run."
echo
echo "To pause the trigger later:  launchctl unload \"$PLIST\""
echo "To resume:                   launchctl load -w \"$PLIST\""
