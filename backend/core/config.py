"""
백엔드 설정 관리
"""
import os
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from modules.utils.config import load_env, get_project_root

# .env 파일 로드
load_env()

# CORS origins를 클래스 밖에서 계산 (Pydantic 모델 필드 제약 회피)
def _get_cors_origins() -> List[str]:
    """CORS 허용 origins 목록 생성"""
    cors_origins = [
        "http://localhost:3000",  # React 개발 서버
        "http://localhost:3001",  # Vite 개발 서버 (포트 충돌 시)
        "http://localhost:5173",  # Vite 개발 서버
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:5173",
    ]
    
    # 로컬 네트워크 접속을 위한 IP 주소 추가 (환경 변수로 설정 가능)
    local_ip = os.getenv('LOCAL_IP')
    if local_ip:
        cors_origins.extend([
            f"http://{local_ip}:3000",
            f"http://{local_ip}:3001",
            f"http://{local_ip}:5173",
        ])
    
    return cors_origins


class Settings(BaseSettings):
    """애플리케이션 설정"""
    
    # 서버 설정
    HOST: str = os.getenv("API_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("API_PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    # CORS 설정
    CORS_ORIGINS: List[str] = _get_cors_origins()
    
    # 파일 업로드 설정
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024  # 100MB
    UPLOAD_DIR: str = str(get_project_root() / "uploads")
    TEMP_DIR: str = str(get_project_root() / "temp")
    
    # 데이터베이스 설정 (기존 설정 재사용)
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
    DB_NAME: str = os.getenv("DB_NAME", "rebate_db")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    
    # WebSocket 설정
    WS_HEARTBEAT_INTERVAL: int = 30  # 초
    
    # API 키 설정 (선택사항)
    gemini_api_key: Optional[str] = None  # GEMINI_API_KEY 환경변수에서 로드
    openai_api_key: Optional[str] = None  # OPENAI_API_KEY 환경변수에서 로드
    upstage_api_key: Optional[str] = None  # UPSTAGE_API_KEY 환경변수에서 로드
    azure_api_key: Optional[str] = None  # AZURE_API_KEY 환경변수에서 로드
    azure_api_endpoint: Optional[str] = None  # AZURE_API_ENDPOINT 환경변수에서 로드
    
    model_config = SettingsConfigDict(
        env_file=get_project_root() / ".env",
        env_file_encoding="utf-8",
        extra="ignore"  # 정의되지 않은 필드는 무시
    )


settings = Settings()
