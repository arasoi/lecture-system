param(
    [string]$FolderPath = "D:\LectureFolders\AudioArchive",
    [ValidateRange(1, 3650)]
    [int]$OlderThanDays = 8
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $FolderPath -PathType Container)) {
    throw "Audio archive folder not found: $FolderPath"
}

$audioExtensions = @(
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".flac",
    ".opus",
    ".mkv",
    ".mp4",
    ".mov",
    ".avi",
    ".webm"
)

$cutoff = (Get-Date).AddDays(-$OlderThanDays)
$filesToDelete = Get-ChildItem -LiteralPath $FolderPath -File -Recurse |
    Where-Object {
        $audioExtensions -contains $_.Extension.ToLowerInvariant() -and $_.LastWriteTime -lt $cutoff
    } |
    Sort-Object LastWriteTime

if (-not $filesToDelete) {
    Write-Host "No audio files older than $OlderThanDays day(s) were found in $FolderPath."
    exit 0
}

foreach ($file in $filesToDelete) {
    Remove-Item -LiteralPath $file.FullName -Force -ErrorAction Stop
    Write-Host "Deleted $($file.FullName)"
}

Write-Host "Cleanup complete. Deleted $($filesToDelete.Count) file(s) older than $OlderThanDays day(s)."
