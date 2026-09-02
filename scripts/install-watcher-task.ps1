param(
    [string]$TaskName = "LectureTranscriberWatcher",
    [string]$ConfigPath = "$PSScriptRoot\..\config.yaml",
    [string]$PythonExe = "python",
    [ValidateRange(1, 1440)]
    [int]$EveryMinutes = 5,
    [string]$RunAsUser = "$env:USERDOMAIN\$env:USERNAME",
    [bool]$Silent = $true
)

$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path -Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = (Get-Command $PythonExe -ErrorAction Stop).Source
$fullConfigPath = Resolve-Path -Path $ConfigPath

$executePath = $pythonPath
if ($Silent) {
    $pythonWPath = Join-Path -Path (Split-Path -Path $pythonPath -Parent) -ChildPath "pythonw.exe"
    if (Test-Path -LiteralPath $pythonWPath) {
        $executePath = $pythonWPath
    }
}

Write-Host "Registering scheduled task '$TaskName' to run the lecture transcription watcher..."
$action = New-ScheduledTaskAction -Execute $executePath -Argument "-m lecture_transcriber --config `"$($fullConfigPath.Path)`" --once" -WorkingDirectory $projectRoot
$startAt = (Get-Date).AddMinutes(1)
$trigger = New-ScheduledTaskTrigger -Once -At $startAt -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances Queue -Hidden:$Silent
$principal = New-ScheduledTaskPrincipal -UserId $RunAsUser -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force -ErrorAction Stop
if ($Silent) {
    Write-Host "Scheduled task '$TaskName' registered successfully in silent mode. It runs every $EveryMinutes minute(s) while your desktop session is logged in (including when locked)."
} else {
    Write-Host "Scheduled task '$TaskName' registered successfully. It runs every $EveryMinutes minute(s) while your desktop session is logged in (including when locked)."
}
