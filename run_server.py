#!/usr/bin/env python3
"""
실행 위치와 무관하게 백엔드 서버를 띄웁니다.
사용: python /path/to/react_rebate/run_server.py  (어느 디렉터리에서든)
"""
import os
import sys
from pathlib import Path

# 이 스크립트가 있는 디렉터리 = 프로젝트 루트
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

import uvicorn
from backend.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
