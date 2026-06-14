$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (!(Test-Path ".venv")) {
    py -3 -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt

$env:PLAYWRIGHT_BROWSERS_PATH = "0"
.\.venv\Scripts\python.exe -m playwright install chromium

.\.venv\Scripts\pyinstaller.exe `
    --noconfirm `
    --windowed `
    --name GiffgaffActivationClient `
    --collect-all PySide6 `
    --collect-all playwright `
    run.py

Write-Host "Build complete: dist\GiffgaffActivationClient\GiffgaffActivationClient.exe"
