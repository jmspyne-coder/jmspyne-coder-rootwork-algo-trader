<#
  Rootwork Algo Trader - Windows trigger tasks (the always-on PC path).

  Registers the three scheduled tasks that fire the trading workflow via
  `gh workflow run`, plus wake-from-sleep so a sleeping PC still fires on time.
  These are the SAME task names the Mac README cutover references, so disabling
  them later (Disable-ScheduledTask -TaskName RootworkAlgo-*) hands the trigger
  cleanly to the Mac.

  Run in an ELEVATED PowerShell:  powershell -ExecutionPolicy Bypass -File register_tasks.ps1

  PREREQS:
   - gh CLI installed and authenticated for THIS user (gh auth status).
   - The PC clock is CENTRAL time. The times below are CT and map to ET as
     9:25 / 9:40 / 3:45 ET. If this PC is on a different timezone, adjust.
   - Independent of these tasks, the GitHub-cron health check (09:58 ET) emails
     "TRIGGER DID NOT FIRE" if a morning run is missed, so a sleeping/off PC is
     never a silent failure.
#>

$ErrorActionPreference = "Stop"
$repo = "jmspyne-coder/rootwork-algo-trader"
$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) { throw "gh CLI not found on PATH. Install it and run 'gh auth login' first." }

# script -> local CT time
$jobs = @(
  @{ Name = "RootworkAlgo-premarket";  Script = "pre_market";   At = "8:25AM" },
  @{ Name = "RootworkAlgo-execute";    Script = "execute_orb";  At = "8:40AM" },
  @{ Name = "RootworkAlgo-eod";        Script = "end_of_day";   At = "2:45PM" },
  # Watchdog at 8:58 CT (9:58 ET): dispatches the health check from the PC too,
  # so the "TRIGGER DID NOT FIRE" alarm does not depend on GitHub's own cron.
  # The GitHub-cron health check still runs independently as the PC-off backstop.
  @{ Name = "RootworkAlgo-healthcheck"; Script = "health_check"; At = "8:58AM" }
)

foreach ($j in $jobs) {
  $action  = New-ScheduledTaskAction -Execute $gh `
    -Argument "workflow run trading_schedule.yml -R $repo -f script=$($j.Script)"
  $trigger = New-ScheduledTaskTrigger -Daily -At $j.At
  # WakeToRun: wake the PC from sleep to fire on time. StartWhenAvailable: if the
  # PC was fully off at the trigger, run as a (late) catch-up when it next wakes -
  # the code's freshness guard then skips the stale entry and logs it, and the
  # health check surfaces it, so a late fire is visible, never a silent bad trade.
  $settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
  # Weekdays only.
  $trigger.DaysOfWeek = 62  # Mon-Fri bitmask (2+4+8+16+32)

  if (Get-ScheduledTask -TaskName $j.Name -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $j.Name -Confirm:$false
  }
  Register-ScheduledTask -TaskName $j.Name -Action $action -Trigger $trigger `
    -Settings $settings -RunLevel Limited -User $env:USERNAME -Force | Out-Null
  Write-Host "Registered $($j.Name) at $($j.At) CT (script=$($j.Script))"
}

Write-Host ""
Write-Host "Done. Verify:  Get-ScheduledTask -TaskName RootworkAlgo-* | Get-ScheduledTaskInfo | Format-Table TaskName,NextRunTime,LastTaskResult"
