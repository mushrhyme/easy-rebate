"""
Database singleton registry

Provides a single `DatabaseManager` instance for the application to reuse.
"""
import logging
import os

# .env를 먼저 로드 (registry가 config보다 먼저 import되는 경우에도 DB 설정 적용)
try:
    from modules.utils.config import load_env
    load_env()
except Exception:
    pass

from .db_manager import DatabaseManager

_db_host = os.getenv('DB_HOST', 'localhost')
_db_name = os.getenv('DB_NAME', 'rebate')
_db_port = int(os.getenv('DB_PORT', '5432'))

# 전역 DB 인스턴스 (애플리케이션 스코프)
# 동시 사용자 증가 시: .env에서 DB_MAX_CONN을 20~30 등으로 올리면 풀 포화를 완화할 수 있음 (PostgreSQL max_connections와 맞출 것)
_db_min_conn = int(os.getenv('DB_MIN_CONN', '1'))
_db_max_conn = int(os.getenv('DB_MAX_CONN', '10'))
_APP_DB = DatabaseManager(
    host=_db_host,
    port=_db_port,
    database=_db_name,
    user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD', ''),
    min_conn=_db_min_conn,
    max_conn=_db_max_conn,
)
logging.getLogger(__name__).info(
    "DB pool created: host=%s port=%s database=%s min_conn=%s max_conn=%s (풀 포화 시 .env DB_MAX_CONN 상향, PostgreSQL max_connections 이내)",
    _db_host, _db_port, _db_name, _db_min_conn, _db_max_conn,
)


def get_db() -> DatabaseManager:
    """애플리케이션 전역 DatabaseManager 인스턴스 반환"""
    return _APP_DB


def close_db() -> None:
    """애플리케이션 종료 시 연결 풀 닫기(선택적 호출)"""
    try:
        _APP_DB.close()
    except Exception:
        pass


