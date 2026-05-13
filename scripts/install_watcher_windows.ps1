# Install agent-handoff watcher as a Windows Scheduled Task.
# Runs every 30 seconds, starts on login.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/install_watcher_windows.ps1

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) {
    Write-Error "python not found in PATH"
    exit 1
}

$Script = Join-Path $RepoRoot "scripts\resume.py"
$TaskName = "AgentHandoffWatcher"

# Remove old task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null

$Action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "`"$Script`" --watch" `
    -WorkingDirectory $RepoRoot

$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddSeconds(10) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Force | Out-Null

Write-Host "Registered: $TaskName"
Write-Host "Watcher polls answers/ every 60s (Windows min repetition interval)."
Write-Host "To uninstall: Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
