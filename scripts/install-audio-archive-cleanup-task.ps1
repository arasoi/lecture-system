param(
    [string]$TaskName = "LectureAudioArchiveCleanup",
    [string]$FolderPath = "D:\LectureFolders\AudioArchive",
    [ValidateRange(1, 3650)]
    [int]$OlderThanDays = 8,
    [string]$RunAsUser = "$env:USERDOMAIN\$env:USERNAME"
)

$ErrorActionPreference = "Stop"

$cleanupScript = (Resolve-Path -Path (Join-Path $PSScriptRoot "cleanup-audio-archive.ps1")).Path
$powershellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$cleanupScript`" -FolderPath `"$FolderPath`" -OlderThanDays $OlderThanDays"

Write-Host "Registering scheduled task '$TaskName' to clean audio archive '$FolderPath' every Monday at 3:00 AM..."
$action = New-ScheduledTaskAction -Execute $powershellExe -Argument $arguments -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 3:00AM
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $RunAsUser -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force -ErrorAction Stop
Write-Host "Scheduled task '$TaskName' registered successfully."
