"""
ユーザー認証およびセッション管理API
"""
import uuid
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Request, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from database.registry import get_db
from backend.core.auth import get_current_user_id, get_current_user as get_current_user_dep
from backend.core.password import hash_password, verify_password
from backend.core.activity_log import log as activity_log

router = APIRouter()


class LoginRequest(BaseModel):
    """ログインリクエストモデル"""
    username: str
    password: str


class LoginResponse(BaseModel):
    """ログイン応答モデル"""
    success: bool
    message: str
    user_id: Optional[int] = None
    username: Optional[str] = None
    display_name: Optional[str] = None
    display_name_ja: Optional[str] = None
    session_id: Optional[str] = None
    must_change_password: bool = False


class UserInfo(BaseModel):
    """ユーザー情報モデル"""
    user_id: int
    username: str
    display_name: str
    display_name_ja: Optional[str] = None
    is_active: bool
    is_admin: bool = False
    last_login_at: Optional[str] = None
    login_count: int
    must_change_password: bool = False


def _is_admin(user_info: dict) -> bool:
    """username='admin' 또는 is_admin=True 이면 관리자."""
    return user_info.get("username") == "admin" or bool(user_info.get("is_admin"))


def require_admin(user_info: dict = Depends(get_current_user_dep)):
    """관리자만 허용. 아니면 403."""
    if not _is_admin(user_info):
        raise HTTPException(status_code=403, detail="관리자만 접근할 수 있습니다")
    return user_info


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
        user = db.get_user_by_username(request.username)
        if not user:
            logger.warning("[auth] user not found username=%s", request.username)
            return LoginResponse(
                success=False,
                message="管理者承認が必要です",
                user_id=None,
                username=None,
                display_name=None,
                session_id=None,
                must_change_password=False,
            )

        # 비밀번호 검증: password_hash가 없으면 초기 비밀번호(ID와 동일)만 허용
        password_ok = False
        force_change = user.get("force_password_change", True)
        stored_hash = user.get("password_hash")

        if stored_hash:
            password_ok = verify_password(request.password, stored_hash)
        else:
            # 초기 비밀번호: ID(username)와 동일할 때만 로그인 허용
            password_ok = request.password == request.username

        if not password_ok:
            logger.warning("[auth] password mismatch username=%s", request.username)
            return LoginResponse(
                success=False,
                message="비밀번호가 올바르지 않습니다",
                user_id=None,
                username=None,
                display_name=None,
                session_id=None,
                must_change_password=False,
            )

        session_id = str(uuid.uuid4())
        ip_address = req.client.host if req.client else None
        user_agent = req.headers.get("user-agent")
        session_created = db.create_user_session(
            user_id=user['user_id'],
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

        if not session_created:
            logger.error("[auth] create_user_session failed user_id=%s", user['user_id'])
            raise HTTPException(status_code=500, detail="세션 생성에 실패했습니다")
        verify_user_info = db.get_session_user(session_id)
        if not verify_user_info:
            logger.error("[auth] session verify failed")
            raise HTTPException(status_code=500, detail="세션 생성 후 검증에 실패했습니다")
        db.update_user_login_info(user['user_id'])
        activity_log(user['username'], "로그인")

        return LoginResponse(
            success=True,
            message="로그인 성공",
            user_id=user['user_id'],
            username=user['username'],
            display_name=user['display_name'],
            display_name_ja=user.get('display_name_ja'),
            session_id=session_id,
            must_change_password=force_change,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[auth] exception: %s", type(e).__name__, exc_info=True)
        raise HTTPException(status_code=500, detail="로그인 처리 중 오류가 발생했습니다.")


@router.post("/logout")
async def logout(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    db=Depends(get_db),
):
    """
    사용자 로그아웃 (X-Session-ID 헤더에서 세션 ID 사용)

    Args:
        x_session_id: 헤더의 세션 ID
        db: データベースインスタンス

    Returns:
        로그아웃 결과
    """
    if not x_session_id:
        return {"success": False, "message": "세션 ID가 필요합니다"}
    try:
        user_info = db.get_session_user(x_session_id)
        username = user_info.get("username") if user_info else None
        success = db.delete_user_session(x_session_id)

        if success:
            activity_log(username, "로그아웃")
            return {"success": True, "message": "로그아웃되었습니다"}
        else:
            return {"success": False, "message": "로그아웃 처리 중 오류가 발생했습니다"}

    except Exception as e:
        return {"success": False, "message": f"로그아웃 처리 중 오류가 발생했습니다: {str(e)}"}


@router.get("/me", response_model=UserInfo)
async def get_current_user(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    db=Depends(get_db),
):
    """
    현재 로그인한 사용자 정보 조회 (X-Session-ID 헤더에서 세션 ID 사용)

    Args:
        x_session_id: 헤더의 세션 ID
        db: データベースインスタンス

    Returns:
        사용자 정보
    """
    if not x_session_id:
        raise HTTPException(status_code=401, detail="세션 ID가 필요합니다")
    try:
        user_info = db.get_session_user(x_session_id)

        if not user_info:
            raise HTTPException(status_code=401, detail="유효하지 않은 세션입니다")

        return UserInfo(
            user_id=user_info['user_id'],
            username=user_info['username'],
            display_name=user_info['display_name'],
            display_name_ja=user_info.get('display_name_ja'),
            is_active=user_info['is_active'],
            is_admin=_is_admin(user_info),
            last_login_at=user_info.get('last_login_at'),
            login_count=user_info.get('login_count', 0),
            must_change_password=user_info.get('force_password_change', False),
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
                    "is_admin": _is_admin(user_info),
                },
                "must_change_password": user_info.get('force_password_change', False),
            }
        else:
            return {"valid": False, "message": "유효하지 않은 세션입니다"}

    except Exception as e:
        return {"valid": False, "message": f"세션 검증 중 오류가 발생했습니다: {str(e)}"}


# ============================================
# 사용자 관리 API (관리자용)
# ============================================

class CreateUserRequest(BaseModel):
    """사용자 생성 요청 모델 (users 테이블 키값 전체 입력 가능)"""
    username: str
    display_name: str
    display_name_ja: Optional[str] = None
    department_ko: Optional[str] = None
    department_ja: Optional[str] = None
    role: Optional[str] = None
    category: Optional[str] = None


class UpdateUserRequest(BaseModel):
    """사용자 업데이트 요청 모델"""
    display_name: Optional[str] = None
    display_name_ja: Optional[str] = None
    department_ko: Optional[str] = None
    department_ja: Optional[str] = None
    role: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    password: Optional[str] = None  # 관리자 설정용: 전달 시 해당 비밀번호로 설정, 빈 문자열이면 로그인ID로 초기화


@router.get("/users")
async def get_users(
    current_user: dict = Depends(require_admin),
    db=Depends(get_db)
):
    """
    모든 사용자 목록 조회 (관리자 전용)
    """
    try:
        users = db.get_all_users()
        return users
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 목록 조회 중 오류가 발생했습니다: {str(e)}")


@router.post("/users", response_model=dict)
async def create_user(
    request: CreateUserRequest,
    current_user: dict = Depends(require_admin),
    db=Depends(get_db)
):
    """
    새 사용자 생성 (관리자 전용)
    """
    try:
        existing_user = db.get_user_by_username(request.username)
        if existing_user:
            raise HTTPException(status_code=400, detail="이미 존재하는 사용자명입니다")

        initial_password_hash = hash_password(request.username)
        user_id = db.create_user(
            username=request.username,
            display_name=request.display_name,
            display_name_ja=request.display_name_ja,
            department_ko=request.department_ko,
            department_ja=request.department_ja,
            role=request.role,
            category=request.category,
            created_by_user_id=current_user["user_id"],
            password_hash=initial_password_hash,
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
    current_user: dict = Depends(require_admin),
    db=Depends(get_db)
):
    """
    사용자 정보 업데이트 (관리자 전용)
    """
    try:
        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

        success = db.update_user(
            user_id=user_id,
            display_name=request.display_name,
            display_name_ja=request.display_name_ja,
            department_ko=request.department_ko,
            department_ja=request.department_ja,
            role=request.role,
            category=request.category,
            is_active=request.is_active,
            is_admin=request.is_admin,
        )

        # 관리자 비밀번호 설정: 해시 저장 후 force_password_change=TRUE로 두어 다음 로그인 시 변경 유도
        if request.password is not None:
            raw = (request.password or "").strip() or (user.get("username") or "")
            db.update_password(user_id, hash_password(raw), force_password_change=True)

        if success:
            return {"success": True, "message": "사용자 정보가 업데이트되었습니다"}
        else:
            raise HTTPException(status_code=500, detail="사용자 업데이트에 실패했습니다")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 업데이트 중 오류가 발생했습니다: {str(e)}")


class ChangePasswordRequest(BaseModel):
    """비밀번호 변경 요청"""
    current_password: str
    new_password: str


@router.post("/change-password", response_model=dict)
async def change_password(
    request: ChangePasswordRequest,
    user_info: dict = Depends(get_current_user_dep),
    db=Depends(get_db),
):
    """
    비밀번호 변경 (로그인 후). 초기 비밀번호(ID와 동일)인 경우 current_password에 ID 입력.
    """
    try:
        user_id = user_info["user_id"]
        username = user_info["username"]
        stored_hash = user_info.get("password_hash")
        force_change = user_info.get("force_password_change", True)

        # 현재 비밀번호 확인: 저장된 해시가 있으면 검증, 없거나 초기 상태면 current == username 허용
        current_raw = (request.current_password or "").strip() if hasattr(request.current_password, "strip") else str(request.current_password or "")
        if len(current_raw.encode("utf-8")) > 72:
            current_raw = current_raw.encode("utf-8")[:72].decode("utf-8", errors="ignore")
        current_ok = False
        if stored_hash:
            current_ok = verify_password(current_raw, stored_hash)
        else:
            current_ok = current_raw == username

        if not current_ok:
            raise HTTPException(status_code=400, detail="현재 비밀번호가 올바르지 않습니다")

        if not request.new_password or len(request.new_password.strip()) < 1:
            raise HTTPException(status_code=400, detail="새 비밀번호를 입력해 주세요")

        # bcrypt 72바이트 제한: 넘기기 전에 여기서 자름
        new_raw = (request.new_password or "").strip()
        if new_raw == username:
            raise HTTPException(
                status_code=400,
                detail="ログインIDと同一のパスワードは使用できません",
            )
        if isinstance(new_raw, str) and len(new_raw.encode("utf-8")) > 72:
            new_raw = new_raw.encode("utf-8")[:72].decode("utf-8", errors="ignore")
        new_hash = hash_password(new_raw)
        success = db.update_password(user_id, new_hash, force_password_change=False)
        if not success:
            raise HTTPException(status_code=500, detail="비밀번호 변경에 실패했습니다")
        activity_log(username, "비밀번호 변경")
        return {"success": True, "message": "비밀번호가 변경되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"비밀번호 변경 중 오류: {str(e)}")


@router.delete("/users/{user_id}", response_model=dict)
async def delete_user(
    user_id: int,
    current_user: dict = Depends(require_admin),
    db=Depends(get_db)
):
    """
    사용자 DB 행 삭제 (관리자 전용)
    """
    try:
        if user_id == current_user["user_id"]:
            raise HTTPException(status_code=400, detail="자기 자신을 삭제할 수 없습니다")

        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

        success = db.delete_user(user_id)

        if success:
            return {"success": True, "message": "사용자가 삭제되었습니다"}
        else:
            raise HTTPException(status_code=500, detail="사용자 삭제에 실패했습니다")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사용자 삭제 중 오류가 발생했습니다: {str(e)}")