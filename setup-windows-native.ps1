$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"

Write-Host "Media Forge 3.2 - Native Windows setup" -ForegroundColor Green

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3.11+ is required." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js 20.19+ is required." }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "FFmpeg must be installed and available on PATH." }
if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) { throw "ffprobe must be installed and available on PATH." }
if (-not (Get-Command deno -ErrorAction SilentlyContinue)) { Write-Host "Warning: Deno is not on PATH. Current YouTube extraction can be more reliable with Deno installed." -ForegroundColor Yellow }
if (-not (Get-Command aria2c -ErrorAction SilentlyContinue)) { Write-Host "Info: aria2c is optional. YouTube will use native concurrent fragments without it." -ForegroundColor DarkGray }

$Venv = Join-Path $Backend ".venv"
if (-not (Test-Path $Venv)) {
    Write-Host "Creating Python environment..."
    python -m venv $Venv
}
$Python = Join-Path $Venv "Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Backend "requirements.txt")

Push-Location $Frontend
try {
    npm ci
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Run .\start-windows-native.ps1 to start both backend and frontend."
Write-Host "Native Windows mode is the recommended way to expose Intel Quick Sync on Docker Desktop machines."
