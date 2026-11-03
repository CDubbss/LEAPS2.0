# setup_scheduler.ps1
# Registers Windows Task Scheduler tasks for Leaps2.0 ML data pipeline.
# Run once from the project root — no admin rights required.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
#
# What it creates:
#   "Leaps2.0 - Label Outcomes"  — runs daily at 9:00 AM MT
#       Collects mark-to-market price snapshots at 7/14/21/28/35/40/50/60/90
#       business-day intervals and labels completed spreads with peak P&L outcomes.
#       Output → logs\label_outcomes.log (appended, timestamped)
#   "Leaps2.0 - Scheduled Scan"  — runs daily at 8:30 AM and 1:30 PM MT
#   "Leaps2.0 - Ted Scan"        — runs weekdays (Mon-Fri) at 8:45 AM MT
#       Automated "The Ted" candidate discovery + pre-screen (populates the
#       /ted/candidates cache) then labels any due track-record rows.
#       The trigger skips weekends; the script itself also skips NYSE holidays
#       (and weekends, as a backstop) and exits 0 on a non-trading day.
#       Output → logs\ted_scan.log

$ErrorActionPreference = "Stop"

# --- Paths ---
$root        = $PSScriptRoot
$python      = "$root\backend\.venv\Scripts\python.exe"
$logDir      = "$root\logs"
$logFile     = "$logDir\label_outcomes.log"
$scanLogFile = "$logDir\scheduled_scan.log"

# --- Validate venv exists ---
if (-not (Test-Path $python)) {
    Write-Error "Python venv not found at: $python`nRun: cd backend && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

# --- Create logs directory ---
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Write-Host "Logs directory: $logDir" -ForegroundColor Gray

# --- Build the cmd.exe argument string ---
# We use cmd.exe so we can redirect stdout+stderr to the log file.
# The Python module is run from the project root (required for package imports).
$cmdArgs = "/c `"echo [%DATE% %TIME%] Starting label_outcomes >> `"$logFile`" 2>&1 && cd /d `"$root`" && `"$python`" -m backend.ml.label_outcomes >> `"$logFile`" 2>&1 && echo [%DATE% %TIME%] Done >> `"$logFile`" 2>&1`""

# --- Task: Label Outcomes ---
$taskName = "Leaps2.0 - Label Outcomes"

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument $cmdArgs

$trigger = New-ScheduledTaskTrigger -Daily -At "09:00AM"

$settings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Leaps2.0: collect option price snapshots and label spread outcomes for ML training." `
    -Force | Out-Null

Write-Host ""
Write-Host "Task registered:" -ForegroundColor Green
Write-Host "  Name     : $taskName"
Write-Host "  Schedule : Daily at 9:00 AM MT"
Write-Host "  Log file : $logFile"

# ---------------------------------------------------------------------------
# Task 2: Scheduled Scan — runs the full scanner pipeline twice daily
# ---------------------------------------------------------------------------
$scanTaskName = "Leaps2.0 - Scheduled Scan"
$scanConfig   = "$root\backend\scripts\scan_config.json"

$scanCmdArgs = "/c `"echo [%DATE% %TIME%] Starting scheduled_scan >> `"$scanLogFile`" 2>&1 && cd /d `"$root`" && `"$python`" -m backend.scripts.scheduled_scan --config `"$scanConfig`" >> `"$scanLogFile`" 2>&1 && echo [%DATE% %TIME%] Done >> `"$scanLogFile`" 2>&1`""

$scanAction = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument $scanCmdArgs

# Two daily triggers: 8:30 AM and 1:30 PM MT
# Edit or remove the afternoon trigger to suit your schedule.
$scanTriggerMorning   = New-ScheduledTaskTrigger -Daily -At "08:30AM"
$scanTriggerAfternoon = New-ScheduledTaskTrigger -Daily -At "01:30PM"

$scanSettings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $scanTaskName `
    -Action $scanAction `
    -Trigger @($scanTriggerMorning, $scanTriggerAfternoon) `
    -Settings $scanSettings `
    -Description "Leaps2.0: automated LEAPS options scan. Results saved to logs/scheduled_scans/. Edit backend/scripts/scan_config.json to adjust filters." `
    -Force | Out-Null

Write-Host ""
Write-Host "Task registered:" -ForegroundColor Green
Write-Host "  Name     : $scanTaskName"
Write-Host "  Schedule : Daily at 8:30 AM and 1:30 PM MT"
Write-Host "  Config   : $scanConfig"
Write-Host "  Log file : $scanLogFile"
Write-Host "  Results  : $root\logs\scheduled_scans\"

# ---------------------------------------------------------------------------
# Task 3: Ted Scan — automated "The Ted" candidate discovery + track-record label
# ---------------------------------------------------------------------------
$tedTaskName = "Leaps2.0 - Ted Scan"
$tedLogFile  = "$logDir\ted_scan.log"

# Discovery (populates the /ted/candidates cache) then label any due track-record rows.
$tedCmdArgs = "/c `"echo [%DATE% %TIME%] Starting ted_scan >> `"$tedLogFile`" 2>&1 && cd /d `"$root`" && `"$python`" -m backend.scripts.ted_scan >> `"$tedLogFile`" 2>&1 && `"$python`" -m backend.scripts.ted_scan --label >> `"$tedLogFile`" 2>&1 && echo [%DATE% %TIME%] Done >> `"$tedLogFile`" 2>&1`""

$tedAction  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $tedCmdArgs
# Weekdays only — markets are shut on weekends. NYSE holidays can't be expressed
# in a Task Scheduler trigger, so ted_scan.py also self-skips holidays in code.
$tedTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "08:45AM"
# DST pin: New-ScheduledTaskTrigger stamps the current UTC offset onto
# StartBoundary, so the fire time drifts an hour across DST changes
# (8:45 MDT -> 7:45 MST). Overwrite it with an offset-less, local wall-clock
# timestamp so Task Scheduler runs it at 8:45 AM local year-round.
$tedTrigger.StartBoundary = (Get-Date "08:45:00").ToString("yyyy-MM-ddTHH:mm:ss")
$tedSettings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $tedTaskName `
    -Action $tedAction `
    -Trigger $tedTrigger `
    -Settings $tedSettings `
    -Description "Leaps2.0: automated 'The Ted' earnings-IV candidate discovery + pre-screen, and track-record labeling. Populates the /ted/candidates cache. Runs weekdays only; skips NYSE holidays in code." `
    -Force | Out-Null

Write-Host ""
Write-Host "Task registered:" -ForegroundColor Green
Write-Host "  Name     : $tedTaskName"
Write-Host "  Schedule : Weekdays (Mon-Fri) at 8:45 AM MT (skips NYSE holidays in code)"
Write-Host "  Log file : $tedLogFile"

# ---------------------------------------------------------------------------
# Task 4: NYSE Expansion Scan — the separate expansion tier (own DB + model)
# ---------------------------------------------------------------------------
# Scans _NYSE_EXPANSION into spread_outcomes_nyse.db (NOT the core DB), then
# labels that DB. Staggered off the core scan's 8:30/1:30 window to avoid
# yfinance/FMP rate-limit collisions. No-op until _NYSE_EXPANSION is populated
# by backend/scripts/build_nyse_expansion.py.
$nyseTaskName = "Leaps2.0 - NYSE Expansion Scan"
$nyseConfig   = "$root\backend\scripts\scan_config_nyse.json"
$nyseLogFile  = "$logDir\nyse_expansion_scan.log"
$nyseDb       = "$root\backend\ml\data\spread_outcomes_nyse.db"

$nyseCmdArgs = "/c `"echo [%DATE% %TIME%] Starting nyse_expansion_scan >> `"$nyseLogFile`" 2>&1 && cd /d `"$root`" && `"$python`" -m backend.scripts.scheduled_scan --config `"$nyseConfig`" >> `"$nyseLogFile`" 2>&1 && `"$python`" -m backend.ml.label_outcomes --db-path `"$nyseDb`" >> `"$nyseLogFile`" 2>&1 && echo [%DATE% %TIME%] Done >> `"$nyseLogFile`" 2>&1`""

$nyseAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $nyseCmdArgs
# Weekdays only, DST-pinned (same idiom as the Ted task). Two staggered runs.
$nyseTrigMorning   = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "09:15AM"
$nyseTrigAfternoon = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "02:00PM"
$nyseTrigMorning.StartBoundary   = (Get-Date "09:15:00").ToString("yyyy-MM-ddTHH:mm:ss")
$nyseTrigAfternoon.StartBoundary = (Get-Date "14:00:00").ToString("yyyy-MM-ddTHH:mm:ss")
$nyseSettings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $nyseTaskName `
    -Action $nyseAction `
    -Trigger @($nyseTrigMorning, $nyseTrigAfternoon) `
    -Settings $nyseSettings `
    -Description "Leaps2.0: separate NYSE-expansion tier scan. Writes spread_outcomes_nyse.db + spread_ranker_nyse (isolated from the core model), then labels it. Weekdays only; skips NYSE holidays in code." `
    -Force | Out-Null

Write-Host ""
Write-Host "Task registered:" -ForegroundColor Green
Write-Host "  Name     : $nyseTaskName"
Write-Host "  Schedule : Weekdays (Mon-Fri) at 9:15 AM and 2:00 PM MT (skips NYSE holidays in code)"
Write-Host "  Config   : $nyseConfig"
Write-Host "  Log file : $nyseLogFile"
Write-Host "  DB       : $nyseDb  (separate from the core model's DB)"

Write-Host ""
Write-Host "To run scan immediately:" -ForegroundColor Cyan
Write-Host "  Start-ScheduledTask -TaskName '$scanTaskName'"
Write-Host ""
Write-Host "To adjust scan filters, edit:"
Write-Host "  $scanConfig"
Write-Host ""
Write-Host "To view all tasks in Task Scheduler UI:"
Write-Host "  taskschd.msc  →  Task Scheduler Library"
Write-Host ""
