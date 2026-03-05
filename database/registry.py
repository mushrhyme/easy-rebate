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
# 풀 포화 완화: 기본 max_conn=20, 필요 시 .env DB_MAX_CONN=30 등 (PostgreSQL max_connections 이내)
_db_min_conn = int(os.getenv('DB_MIN_CONN', '1'))
_db_max_conn = int(os.getenv('DB_MAX_CONN', '20'))
_db_conn_timeout = int(os.getenv('DB_CONN_TIMEOUT', '30'))  # getconn 대기 초과 시 예외, 0=무한대기
_APP_DB = DatabaseManager(
    host=_db_host,
    port=_db_port,
    database=_db_name,
    user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD', ''),
    min_conn=_db_min_conn,
    max_conn=_db_max_conn,
    conn_timeout=_db_conn_timeout,
)
logging.getLogger(__name__).info(
    "DB pool created: host=%s port=%s database=%s min_conn=%s max_conn=%s conn_timeout=%ss",
    _db_host, _db_port, _db_name, _db_min_conn, _db_max_conn, _db_conn_timeout,
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


