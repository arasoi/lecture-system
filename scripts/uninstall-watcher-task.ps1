param(
    [string]$TaskName = "LectureTranscriberWatcher"
)

$ErrorActionPreference = 'Stop'

Write-Host "Unregistering scheduled task '$TaskName'..."
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
Write-Host "Scheduled task '$TaskName' unregistered."
