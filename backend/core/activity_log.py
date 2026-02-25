"""
사용자 활동 로그: 터미널에 [시간] [인트라넷 아이디] [작업] 형식으로 출력.
Uvicorn 하에서도 보이도록 logging + stderr 사용.
사용자별로 아이디 색상 구분 (TTY일 때만, 환경변수 ACTIVITY_LOG_NO_COLOR=1 이면 비활성).
"""
import os
import sys
import logging
from datetime import datetime

# ANSI: 사용자별 색상 (bright). 같은 사용자는 항상 같은 색.
_RESET = "\033[0m"
_USER_COLORS = [
    "\033[92m",  # green
    "\033[94m",  # blue
    "\033[95m",  # magenta
    "\033[96m",  # cyan
    "\033[93m",  # yellow
    "\033[91m",  # red
]


def _color_for_user(username: str | None) -> str:
    """사용자명 해시로 색상 인덱스 반환. None이면 리셋만."""
    if not username:
        return _RESET
    n = sum(ord(c) for c in username) % len(_USER_COLORS)
    return _USER_COLORS[n]


def _use_color() -> bool:
    """stderr가 TTY이고, NO_COLOR 요청이 없으면 True."""
    if os.environ.get("ACTIVITY_LOG_NO_COLOR", "").lower() in ("1", "true", "yes"):
        return False
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


# Uvicorn/reload 환경에서도 터미널에 나오도록 stderr에 직접 출력하는 로거
_logger = logging.getLogger("activity")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setLevel(logging.INFO)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.setLevel(logging.INFO)
    _logger.addHandler(_handler)
    _logger.propagate = False


def log(username: str | None, action: str) -> None:
    """활동 한 줄 출력. username이 None이면 '-'. TTY일 때 사용자별 색상 적용."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    uid = username if username else "-"
    if _use_color():
        color = _color_for_user(username)
        _logger.info("[%s] [%s%s%s] %s", ts, color, uid, _RESET, action)
    else:
        _logger.info("[%s] [%s] %s", ts, uid, action)
