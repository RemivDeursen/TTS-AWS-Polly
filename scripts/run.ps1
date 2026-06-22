$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$entrypoint = Join-Path $projectRoot "TTS_Local.py"

if (-not (Test-Path $python)) {
    Write-Host "Virtual environment not found. Creating .venv..."
    py -m venv (Join-Path $projectRoot ".venv")
}

& $python -m pip install -r (Join-Path $projectRoot "requirements.txt")
& $python $entrypoint
