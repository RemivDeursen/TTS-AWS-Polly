$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath ".venv")) {
    py -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create virtual environment."
    }
}

$BuildPath = Join-Path $ProjectRoot ".pyinstaller-work"
$DistPath = Join-Path $ProjectRoot "dist"

if (Test-Path -LiteralPath $BuildPath) {
    Remove-Item -LiteralPath $BuildPath -Recurse -Force
}

Invoke-Checked { & ".\.venv\Scripts\python.exe" -m pip install --upgrade pip }
Invoke-Checked { & ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt }
Invoke-Checked {
    & ".\.venv\Scripts\pyinstaller.exe" `
        --clean `
        --noconfirm `
        --workpath $BuildPath `
        --distpath $DistPath `
        packaging\TTS_Local.spec
}

Write-Host ""
Write-Host "Built dist\TTS_Local.exe"
Write-Host "Place rootkey.csv next to dist\TTS_Local.exe before running it."
