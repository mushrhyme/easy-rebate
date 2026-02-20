"""
비밀번호 해시 및 검증 (bcrypt 직접 사용)
passlib는 최신 bcrypt 패키지와 호환 문제가 있어, bcrypt 패키지를 직접 사용함.
bcrypt는 비밀번호를 최대 72바이트로 제한하므로, 넘기기 전에 잘라 둠.
"""
import logging
import bcrypt

logger = logging.getLogger(__name__)

# bcrypt 최대 비밀번호 길이 (바이트)
_BCRYPT_MAX_BYTES = 72
_DEFAULT_ROUNDS = 12


def _truncate_to_bytes(s: str, max_bytes: int = _BCRYPT_MAX_BYTES) -> bytes:
    """UTF-8 바이트 길이가 max_bytes를 넘지 않도록 자른 뒤 bytes로 반환."""
    if not s:
        return b""
    if not isinstance(s, str):
        s = str(s)
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return encoded
    return encoded[:max_bytes]


def hash_password(password: str) -> str:
    """비밀번호를 bcrypt로 해시하여 문자열로 반환 (DB 저장용)."""
    raw = password or ""
    p = _truncate_to_bytes(raw)
    salt = bcrypt.gensalt(rounds=_DEFAULT_ROUNDS)
    hashed = bcrypt.hashpw(p, salt)
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """평문 비밀번호와 저장된 해시를 비교."""
    if not plain or not hashed:
        return False
    p = _truncate_to_bytes(plain)
    try:
        h = hashed.encode("utf-8") if isinstance(hashed, str) else hashed
        return bcrypt.checkpw(p, h)
    except Exception:
        return False
