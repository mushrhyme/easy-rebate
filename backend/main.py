"""
FastAPI 메인 애플리케이션
"""
import os
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from backend.api.routes import documents, items, search, websocket, auth, performance, sap_upload, rag_admin
from backend.core.config import settings
from backend.core.scheduler import setup_archive_scheduler
from database.registry import close_db

# 스케줄러 전역 변수
scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    애플리케이션 생명주기 관리
    - 시작 시: 스케줄러 시작
    - 종료 시: 스케줄러 중지 및 DB 연결 풀 정리
    """
    global scheduler
    
    # 시작 시
    scheduler = setup_archive_scheduler()
    scheduler.start()
    
    yield
    
    # 종료 시
    if scheduler:
        scheduler.shutdown()
    
    # 데이터베이스 연결 풀 정리
    close_db()


# FastAPI 앱 생성
app = FastAPI(
    title="条件請求書アップロードシステム API",
    description="PDF 업로드 및 관리 시스템 백엔드 API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 설정 (프론트엔드와 통신을 위해)
# 개발 모드에서는 로컬 네트워크 IP도 허용
def is_local_network_origin(origin: str) -> bool:
    """로컬 네트워크 IP인지 확인"""
    if not origin:
        return False
    try:
        # http:// 또는 https:// 제거
        url = origin.replace("http://", "").replace("https://", "")
        # 포트 제거
        host = url.split(":")[0]
        
        # localhost, 127.0.0.1 체크
        if host in ["localhost", "127.0.0.1"]:
            return True
        
        # 로컬 네트워크 IP 범위 체크
        parts = host.split(".")
        if len(parts) == 4:
            first = int(parts[0])
            second = int(parts[1])
            # 10.x.x.x, 172.16-31.x.x, 192.168.x.x
            if first == 10:
                return True
            if first == 172 and 16 <= second <= 31:
                return True
            if first == 192 and second == 168:
                return True
    except:
        pass
    return False

# CORS origins 설정
cors_origins = list(settings.CORS_ORIGINS)

# 개발 모드에서는 로컬 네트워크 origin도 동적으로 허용
if settings.DEBUG or os.getenv("ALLOW_LOCAL_NETWORK", "true").lower() == "true":
    # allow_origin_regex를 사용하여 로컬 네트워크 IP 패턴 및 도메인 허용
    # 개발 포트 범위: 3000-3999 (React, Vite 등 - 3002 포함), 5173 (Vite 기본 포트)
    import re
    # LOCAL_IP 환경 변수에서 도메인 추출
    local_ip = os.getenv('LOCAL_IP', '')
    domain_pattern = ''
    if local_ip:
        # http:// 또는 https:// 제거
        domain = local_ip.replace("http://", "").replace("https://", "")
        # 포트가 포함되어 있으면 제거
        if ":" in domain:
            domain = domain.split(":")[0]
        # 도메인 패턴 생성 (점을 이스케이프)
        if domain and '.' in domain:
            domain_pattern = f"|{re.escape(domain)}"
    
    # 포트 3000-3999 또는 5173 허용
    # localhost, 127.0.0.1, 로컬 네트워크 IP, 도메인 모두 허용
    cors_origin_regex = r"http://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[01])\.\d+\.\d+|192\.168\.\d+\.\d+" + domain_pattern + r"):(3\d{3}|5173)"
else:
    cors_origin_regex = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,  # 기본 허용 origins
    allow_origin_regex=cors_origin_regex,  # 로컬 네트워크 IP 패턴 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static 파일 서빙 (이미지 파일들)
static_dir = project_root / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 라우터 등록
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(items.router, prefix="/api/items", tags=["items"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(websocket.router, prefix="/ws", tags=["websocket"])
app.include_router(performance.router, prefix="/api/performance", tags=["performance"])
app.include_router(sap_upload.router, prefix="/api/sap-upload", tags=["sap-upload"])
app.include_router(rag_admin.router, prefix="/api/rag-admin", tags=["rag-admin"])


@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {"message": "条件請求書アップロードシステム API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"}


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """전역 예외 핸들러"""
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
