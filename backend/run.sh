#!/bin/bash
# FastAPI 백엔드 실행 스크립트

# 프로젝트 루트로 이동
cd "$(dirname "$0")/.."

# 가상환경 활성화 (있는 경우)
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 서버 실행
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
