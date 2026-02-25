# 프론트엔드만 실행. (다른 터미널에서 dev-backend.ps1 실행)
$ErrorActionPreference = "Stop"
# 한글 출력 깨짐 방지 (cmd 창 UTF-8)
if ($Host.Name -eq "ConsoleHost") { chcp 65001 | Out-Null }
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

Write-Host "[dev-frontend] Frontend running. Stop: Ctrl+C" -ForegroundColor Magenta
npm run dev --prefix frontend
