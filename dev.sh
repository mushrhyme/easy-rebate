#!/bin/bash
# 프로젝트 루트에서 실행. rebate-server + npm run dev 동시 기동.
# 종료 시 Ctrl+C 한 번으로 두 프로세스 모두 정리됨.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

cleanup() {
  echo ""
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM

# 백엔드 포트: .env의 API_PORT 또는 기본 8000
BACKEND_PORT=8000
[ -f .env ] && val=$(grep -E '^API_PORT=' .env 2>/dev/null | cut -d= -f2) && [ -n "$val" ] && BACKEND_PORT="$val"
[ -n "$API_PORT" ] && BACKEND_PORT="$API_PORT"

# 해당 포트 사용 중이면 기존 프로세스 종료
if lsof -ti:"$BACKEND_PORT" >/dev/null 2>&1; then
  echo "[dev.sh] 포트 $BACKEND_PORT 사용 중인 프로세스를 종료합니다."
  lsof -ti:"$BACKEND_PORT" | xargs kill 2>/dev/null || true
  sleep 1
fi

# 백엔드: 이미 uv sync 한 환경 사용 (매번 sync/다운로드 안 함)
( uv run --no-sync rebate-server 2>&1 | sed 's/^/[backend] /' ) &
BACKEND_PID=$!

# 프론트엔드: 포그라운드, 로그에 [frontend] 접두어
cd frontend && npm run dev 2>&1 | sed 's/^/[frontend] /'
