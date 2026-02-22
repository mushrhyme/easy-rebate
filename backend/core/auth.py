"""
인증 및 세션 관리 유틸리티
"""
from typing import Optional
from fastapi import HTTPException, Depends, Header
from database.registry import get_db


def get_current_user(session_id: Optional[str] = Header(None, alias="X-Session-ID")):
    """
    현재 로그인한 사용자를 가져오는 의존성 함수

    Args:
        session_id: 헤더에서 추출한 세션 ID

    Returns:
        사용자 정보 딕셔너리

    Raises:
        HTTPException: 세션이 유효하지 않거나 사용자가 인증되지 않은 경우
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"🔐 [인증] 세션 ID 확인: {session_id is not None}, 값: {session_id[:20] + '...' if session_id and len(session_id) > 20 else session_id}")
    
    if not session_id:
        logger.warning("❌ [인증] 세션 ID가 없습니다")
        raise HTTPException(status_code=401, detail="세션 ID가 필요합니다")

    db = get_db()
    user_info = db.get_session_user(session_id)

    if not user_info:
        logger.warning(f"❌ [인증] 유효하지 않은 세션 ID: {session_id[:20] + '...' if len(session_id) > 20 else session_id}")
        raise HTTPException(status_code=401, detail="유효하지 않은 세션입니다")

    logger.info(f"✅ [인증] 인증 성공: user_id={user_info.get('user_id')}")
    return user_info


def get_current_user_id(session_id: Optional[str] = Header(None, alias="X-Session-ID")) -> int:
    """
    현재 로그인한 사용자의 ID를 가져오는 의존성 함수

    Args:
        session_id: 헤더에서 추출한 세션 ID

    Returns:
        사용자 ID

    Raises:
        HTTPException: 세션이 유효하지 않거나 사용자가 인증되지 않은 경우
    """
    user_info = get_current_user(session_id)
    return user_info['user_id']


def get_current_user_optional(session_id: Optional[str] = Header(None, alias="X-Session-ID")):
    """
    현재 로그인한 사용자를 가져오는 의존성 함수 (선택적).
    세션이 없거나 유효하지 않으면 None 반환.

    Returns:
        사용자 정보 딕셔너리 또는 None
    """
    if not session_id:
        return None
    db = get_db()
    return db.get_session_user(session_id)


def require_auth(session_id: Optional[str] = Header(None, alias="X-Session-ID")):
    """
    인증이 필요한 엔드포인트에서 사용할 의존성 함수
    세션 검증만 수행하고 사용자 정보를 반환하지 않음

    Args:
        session_id: 헤더에서 추출한 세션 ID

    Raises:
        HTTPException: 세션이 유효하지 않은 경우
    """
    get_current_user(session_id)  # 검증만 수행