# Bootstrap dependencies for the remote transcription workstation.
# Adjust package identifiers if your winget repository differs.

$ErrorActionPreference = 'Stop'

Write-Host "Installing Python, ffmpeg, and Ollama..."

$packages = @(
    @{ Id = 'Python.Python.3'; Name = 'Python 3' },
    @{ Id = 'Gyan.FFmpeg'; Name = 'FFmpeg' },
    @{ Id = 'Ollama.Ollama'; Name = 'Ollama' }
)

foreach ($pkg in $packages) {
    Write-Host "Installing $($pkg.Name)..."
    winget install --id $($pkg.Id) --silent --accept-package-agreements --accept-source-agreements
}

Write-Host "Installing Python dependencies..."
python -m pip install --upgrade pip
python -m pip install -r ..\requirements.txt

Write-Host "Bootstrap complete. Review README.md for configuration and use."
