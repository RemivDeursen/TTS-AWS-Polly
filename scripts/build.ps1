$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

if (-not (Test-Path -LiteralPath ".venv")) {
    py -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\pyinstaller.exe" --clean --noconfirm packaging\TTS_Local.spec

Write-Host ""
Write-Host "Built dist\TTS_Local.exe"
Write-Host "Place rootkey.csv next to dist\TTS_Local.exe before running it."
