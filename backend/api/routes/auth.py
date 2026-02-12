"""
ユーザー認証およびセッション管理API
"""
import uuid
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Request, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from database.registry import get_db
from backend.core.auth import get_current_user_id

router = APIRouter()


class LoginRequest(BaseModel):
    """ログインリクエストモデル"""
    username: str


class LoginResponse(BaseModel):
    """ログイン応答モデル"""
    success: bool
    message: str
    user_id: Optional[int] = None
    username: Optional[str] = None
    display_name: Optional[str] = None
    display_name_ja: Optional[str] = None
    session_id: Optional[str] = None


class UserInfo(BaseModel):
    """ユーザー情報モデル"""
    user_id: int
    username: str
    display_name: str
    display_name_ja: Optional[str] = None
    is_active: bool
    last_login_at: Optional[str] = None
    login_count: int


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    req: Request,
    db=Depends(get_db)
):
    """
    ユーザーログイン

    Args:
        request: ログインリクエスト (usernameのみ必要)
        req: HTTPリクエスト (IPアドレス抽出用)
        db: データベースインスタンス

    Returns:
        ログイン結果
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"🔐 [로그인] 로그인 시도: username={request.username}")
        
        # ユーザー検索
        user = db.get_user_by_username(request.username)
        
        logger.info(f"🔐 [로그인] 사용자 조회 결과: {user is not None}")

        if not user:
            # ユーザーが存在しない
            logger.warning(f"❌ [로그인] 사용자를 찾을 수 없음: {request.username}")
            return LoginResponse(
                success=False,
                message="管理者承認が必要です",
                user_id=None,
                username=None,
                display_name=None,
                session_id=None
            )

        # 세션 ID 생성
        session_id = str(uuid.uuid4())
        logger.info(f"🔐 [로그인] 세션 ID 생성: {session_id[:20]}...")

        # IP 주소 추출
        ip_address = req.client.host if req.client else None
        user_agent = req.headers.get("user-agent")
        logger.info(f"🔐 [로그인] IP 주소: {ip_address}, User-Agent: {user_agent[:50] if user_agent else None}...")

        # 세션 생성
        logger.info(f"🔵 [로그인] 세션 생성 시도: user_id={user['user_id']}, session_id={session_id[:20]}...")
        session_created = db.create_user_session(
            user_id=user['user_id'],
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

        if not session_created:
            logger.error(f"❌ [로그인] 세션 생성 실패: user_id={user['user_id']}, session_id={session_id[:20]}...")
            raise HTTPException(status_code=500, detail="세션 생성에 실패했습니다")

        # 세션이 실제로 데이터베이스에 저장되었는지 확인
        verify_user_info = db.get_session_user(session_id)
        if not verify_user_info:
            logger.error(f"❌ [로그인] 세션 생성 후 검증 실패: session_id={session_id[:20]}... (데이터베이스에 세션이 없음)")
            raise HTTPException(status_code=500, detail="세션 생성 후 검증에 실패했습니다")
        
        logger.info(f"✅ [로그인] 세션 생성 및 검증 성공: user_id={user['user_id']}, session_id={session_id[:20]}..., verified_user_id={verify_user_info.get('user_id')}")

        # 로그인 정보 업데이트
        db.update_user_login_info(user['user_id'])

        logger.info(f"✅ [로그인] 로그인 성공: user_id={user['user_id']}, username={user['username']}")
        
        return LoginResponse(
            success=True,
            message="로그인 성공",
            user_id=user['user_id'],
            username=user['username'],
            display_name=user['display_name'],
            display_name_ja=user.get('display_name_ja'),
            session_id=session_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [로그인] 예외 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"로그인 처리 중 오류가 발생했습니다: {str(e)}")


@router.post("/logout")
async def logout(
    session_id: str,
    db=Depends(get_db)
):
    """
    사용자 로그아웃

    Args:
        session_id: 세션 ID
        db: データベースインスタンス

    Returns:
        로그아웃 결과
    """
    try:
        success = db.delete_user_session(session_id)

        if success:
            return {"success": True, "message": "로그아웃되었습니다"}
        else:
            return {"success": False, "message": "로그아웃 처리 중 오류가 발생했습니다"}

    except Exception as e:
        return {"success": False, "message": f"로그아웃 처리 중 오류가 발생했습니다: {str(e)}"}


@router.get("/me", response_model=UserInfo)
async def get_current_user(
    session_id: str,
    db=Depends(get_db)
):
    """
    현재 로그인한 사용자 정보 조회

    Args:
        session_id: 세션 ID
        db: データベースインスタンス

    Returns:
        사용자 정보
    """
    try:
        user_info = db.get_session_user(session_id)

        if not user_info:
            raise HTTPException(status_code=401, detail="유효하지 않은 세션입니다")

        return UserInfo(
            user_id=user_info['user_id'],
            username=user_info['username'],
            display_name=user_info['display_name'],
            display_name_ja=user_info.get('display_name_ja'),
            is_active=user_info['is_active'],
            last_login_at=user_info.get('last_login_at'),
            login_count=user_info.get('login_count', 0)
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 정보 조회 중 오류가 발생했습니다: {str(e)}")


@router.get("/validate-session")
async def validate_session(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    db=Depends(get_db)
):
    """
    세션 유효성 검증

    Args:
        x_session_id: 헤더에서 추출한 세션 ID (X-Session-ID)
        db: データベースインスタンス

    Returns:
        세션 유효성 결과
    """
    try:
        # 세션 ID가 없으면 유효하지 않은 세션으로 처리
        if not x_session_id:
            return {"valid": False, "message": "세션 ID가 필요합니다"}

        user_info = db.get_session_user(x_session_id)

        if user_info:
            return {
                "valid": True,
                "user": {
                    "user_id": user_info['user_id'],
                    "username": user_info['username'],
                    "display_name": user_info['display_name'],
                    "display_name_ja": user_info.get('display_name_ja'),
                }
            }
        else:
            return {"valid": False, "message": "유효하지 않은 세션입니다"}

    except Exception as e:
        return {"valid": False, "message": f"세션 검증 중 오류가 발생했습니다: {str(e)}"}


# ============================================
# 사용자 관리 API (관리자용)
# ============================================

class CreateUserRequest(BaseModel):
    """사용자 생성 요청 모델"""
    username: str
    display_name: str
    display_name_ja: Optional[str] = None


class UpdateUserRequest(BaseModel):
    """사용자 업데이트 요청 모델"""
    display_name: Optional[str] = None
    display_name_ja: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/users")
async def get_users(
    current_user_id: int = Depends(get_current_user_id),
    db=Depends(get_db)
):
    """
    모든 사용자 목록 조회 (관리자용)

    Args:
        current_user_id: 현재 사용자 ID (인증용)
        db: データベースインスタンス

    Returns:
        사용자 목록 (users 테이블 행 그대로 반환)
    """
    try:
        users = db.get_all_users()
        return users
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 목록 조회 중 오류가 발생했습니다: {str(e)}")


@router.post("/users", response_model=dict)
async def create_user(
    request: CreateUserRequest,
    current_user_id: int = Depends(get_current_user_id),
    db=Depends(get_db)
):
    """
    새 사용자 생성 (관리자용)

    Args:
        request: 사용자 생성 요청
        current_user_id: 현재 사용자 ID (생성자 기록용)
        db: データベースインスタンス

    Returns:
        생성 결과
    """
    try:
        # 사용자명 중복 체크
        existing_user = db.get_user_by_username(request.username)
        if existing_user:
            raise HTTPException(status_code=400, detail="이미 존재하는 사용자명입니다")

        # 사용자 생성
        user_id = db.create_user(
            username=request.username,
            display_name=request.display_name,
            display_name_ja=request.display_name_ja,
            created_by_user_id=current_user_id,
        )

        if user_id:
            return {
                "success": True,
                "message": "사용자가 생성되었습니다",
                "user_id": user_id
            }
        else:
            raise HTTPException(status_code=500, detail="사용자 생성에 실패했습니다")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 생성 중 오류가 발생했습니다: {str(e)}")


@router.put("/users/{user_id}", response_model=dict)
async def update_user(
    user_id: int,
    request: UpdateUserRequest,
    current_user_id: int = Depends(get_current_user_id),
    db=Depends(get_db)
):
    """
    사용자 정보 업데이트 (관리자용)

    Args:
        user_id: 업데이트할 사용자 ID
        request: 업데이트 요청
        current_user_id: 현재 사용자 ID (권한 확인용)
        db: データベースインスタンス

    Returns:
        업데이트 결과
    """
    try:
        # 사용자 존재 확인
        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

        # 업데이트 수행
        success = db.update_user(
            user_id=user_id,
            display_name=request.display_name,
            display_name_ja=request.display_name_ja,
            is_active=request.is_active,
        )

        if success:
            return {"success": True, "message": "사용자 정보가 업데이트되었습니다"}
        else:
            raise HTTPException(status_code=500, detail="사용자 업데이트에 실패했습니다")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 업데이트 중 오류가 발생했습니다: {str(e)}")


@router.delete("/users/{user_id}", response_model=dict)
async def deactivate_user(
    user_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db=Depends(get_db)
):
    """
    사용자 비활성화 (관리자용)

    Args:
        user_id: 비활성화할 사용자 ID
        current_user_id: 현재 사용자 ID (권한 확인용)
        db: データベースインスタンス

    Returns:
        비활성화 결과
    """
    try:
        # 자기 자신은 비활성화할 수 없음
        if user_id == current_user_id:
            raise HTTPException(status_code=400, detail="자기 자신을 비활성화할 수 없습니다")

        # 사용자 존재 확인
        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

        # 비활성화 수행
        success = db.update_user(user_id=user_id, is_active=False)

        if success:
            return {"success": True, "message": "사용자가 비활성화되었습니다"}
        else:
            raise HTTPException(status_code=500, detail="사용자 비활성화에 실패했습니다")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 비활성화 중 오류가 발생했습니다: {str(e)}")