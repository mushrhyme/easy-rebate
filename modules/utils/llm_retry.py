"""
LLM API 호출 시 429(Rate Limit) 재시도 유틸.

동시 분석·정답지 생성 등으로 LLM 호출이 몰릴 때 429 대비
지수 백오프 + jitter로 재시도합니다.
"""
import random
import time
from typing import Callable, TypeVar

_T = TypeVar("_T")

# 기본: 최대 4회 재시도, 초기 대기 2초, 최대 대기 60초
DEFAULT_MAX_RETRIES = 4
DEFAULT_INITIAL_DELAY = 2.0
DEFAULT_MAX_DELAY = 60.0


def _is_retryable_llm_error(e: Exception) -> bool:
    """429 또는 rate limit 관련 오류면 True."""
    msg = (getattr(e, "message", "") or str(e)).lower()
    if "rate" in msg or "429" in msg or "too many" in msg:
        return True
    code = getattr(e, "status_code", None)
    if code == 429:
        return True
    resp = getattr(e, "response", None)
    if resp is not None and getattr(resp, "status_code", None) == 429:
        return True
    return False


def call_with_retry(
    fn: Callable[[], _T],
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
) -> _T:
    """
    fn()을 실행하고, 429/rate limit 시 지수 백오프+jitter로 재시도.

    Args:
        fn: 인자 없는 호출 가능 객체 (예: lambda: client.chat.completions.create(...))
        max_retries: 최대 시도 횟수 (첫 시도 포함)
        initial_delay: 첫 재시도 대기 초
        max_delay: 대기 상한 초

    Returns:
        fn() 반환값
    """
    last_error: Exception | None = None
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if attempt == max_retries - 1 or not _is_retryable_llm_error(e):
                raise
            sleep_time = min(delay + random.uniform(0, 1), max_delay)
            time.sleep(sleep_time)
            delay = min(delay * 2, max_delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError("call_with_retry: unreachable")
