$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Python environment is missing. Run .\setup-windows-native.ps1 first." -ForegroundColor Yellow
    exit 1
}

$BackendCmd = "Set-Location -LiteralPath '$Backend'; `$env:VQI_DATA_DIR='./data'; `$env:VQI_WORKER_COUNT='1'; & '$Python' -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
$FrontendCmd = "Set-Location -LiteralPath '$Frontend'; npm run dev"

Start-Process powershell -ArgumentList @('-NoExit','-ExecutionPolicy','Bypass','-Command',$BackendCmd)
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList @('-NoExit','-ExecutionPolicy','Bypass','-Command',$FrontendCmd)

Write-Host "Media Forge is starting." -ForegroundColor Green
Write-Host "Frontend: http://localhost:5173"
Write-Host "Health:   http://127.0.0.1:8000/api/health?refresh_hardware=true"
Write-Host ""
Write-Host "If Intel QSV initializes successfully, Auto will prefer it over MX330 CUDA-only scaling."
