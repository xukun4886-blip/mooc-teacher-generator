param([int]$Port = 8765, [switch]$NoBrowser, [string]$Config = 'config/m2.local.json')
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $repoRoot
if (-not (Test-Path -LiteralPath 'frontend/dist/index.html') -or (Get-ChildItem -LiteralPath 'frontend/src' -Recurse -File | Where-Object LastWriteTime -gt (Get-Item -LiteralPath 'frontend/dist/index.html').LastWriteTime)) {
    Push-Location -LiteralPath 'frontend'
    try {
        npm.cmd ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
}
if (Get-NetTCPConnection -State Listen -LocalAddress '127.0.0.1' -LocalPort $Port -ErrorAction SilentlyContinue) {
    $workbenchHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 10
    if ($workbenchHealth.application -ne 'mooc-workbench' -or -not $workbenchHealth.worker_alive) { throw 'Port is occupied by an unexpected or unhealthy service' }
    if (-not $NoBrowser) { & '.\.venv-m1\Scripts\python.exe' tools/m2_open.py --port $Port --config $Config }
    else { Write-Host "本地工作台已运行：http://127.0.0.1:$Port/" }
    exit $LASTEXITCODE
}
if ($NoBrowser) { & '.\.venv-m1\Scripts\python.exe' -m mooc_m2 --config $Config --port $Port }
else { & '.\.venv-m1\Scripts\python.exe' -m mooc_m2 --config $Config --port $Port --open }
