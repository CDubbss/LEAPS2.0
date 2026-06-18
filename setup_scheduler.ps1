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
