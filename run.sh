#!/bin/bash
# 설치 없이 실행할 때만 사용 (실행 위치 무관). --reload 없음 → 운영용.
# 권장: pip install -e . 후 어디서든 rebate-server (DEBUG로 reload 여부 결정)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --app-dir "$DIR"
