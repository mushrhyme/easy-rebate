# 백엔드만 실행. (다른 터미널에서 dev-frontend.ps1 실행)
$ErrorActionPreference = "Stop"
# 한글 출력 깨짐 방지 (cmd 창 UTF-8)
if ($Host.Name -eq "ConsoleHost") { chcp 65001 | Out-Null }
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

$BackendPort = 8000
if (Test-Path .env) {
    $m = Get-Content .env | Select-String -Pattern '^API_PORT=(\d+)' | Select-Object -First 1
    if ($m) { $BackendPort = [int]$m.Matches.Groups[1].Value }
}
if ($env:API_PORT) { $BackendPort = [int]$env:API_PORT }

$conn = Get-NetTCPConnection -LocalPort $BackendPort -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    Write-Host "[dev-backend] Port $BackendPort in use, stopping process..."
    Get-NetTCPConnection -LocalPort $BackendPort -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

Write-Host "[dev-backend] Backend running. Stop: Ctrl+C" -ForegroundColor Cyan
# UV_RELOAD=0: 단일 프로세스로 실행 → 로그가 이 창에 그대로 출력됨 (reload 시 자식 프로세스 로그가 안 보이던 문제 회피)
$env:UV_RELOAD = "0"
uv run --no-sync rebate-server
