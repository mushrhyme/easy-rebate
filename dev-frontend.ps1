# 프론트엔드만 실행. (다른 터미널에서 dev-backend.ps1 실행)
$ErrorActionPreference = "Stop"
# 한글 출력 깨짐 방지 (cmd 창 UTF-8)
if ($Host.Name -eq "ConsoleHost") { chcp 65001 | Out-Null }
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

$FrontendPort = 3002 # vite.config.ts server.port 와 동일

function Test-DevFrontendPortFree {
    param([int]$Port) # $Port: 확인할 로컬 포트 (예: 3002)
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return ($null -eq $listeners -or $listeners.Count -eq 0) # true = LISTEN 없음 → 기동 가능
}

if (-not (Test-DevFrontendPortFree -Port $FrontendPort)) {
    Write-Host "[dev-frontend] 포트 $FrontendPort 가 이미 사용 중입니다. 기존 Vite 창을 종료한 뒤 다시 실행하세요." -ForegroundColor Yellow
    exit 1
}

Write-Host "[dev-frontend] Frontend running. Stop: Ctrl+C" -ForegroundColor Magenta
npm run dev --prefix frontend
