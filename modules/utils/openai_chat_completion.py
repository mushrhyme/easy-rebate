"""
OpenAI chat.completions 호출 전 payload 정규화·JSON 직렬화 검증·로깅.

HTTP 400 "could not parse the JSON body" 방지: NaN/Inf·numpy·Decimal 등 비표준 값 제거 후
json.dumps(..., allow_nan=False)로 사전 검증한다.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict

logger = logging.getLogger(__name__)

MAX_LOG_JSON_LEN = 12000
MAX_PREVIEW_CHARS = 200

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore


class OpenAIJsonSerializationError(ValueError):
    """OpenAI로 보내기 전 JSON 직렬화 검증 실패."""


def sanitize_for_openai_json(obj: Any) -> Any:
    """
    dict/list/스칼라를 RFC 8259에 맞게 직렬화 가능한 형태로 정규화.
    (NaN/Inf → None, numpy·Decimal 처리, 문자열 surrogate 정리)
    """
    if isinstance(obj, dict):
        return {str(k): sanitize_for_openai_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_openai_json(x) for x in obj]
    if isinstance(obj, tuple):
        return [sanitize_for_openai_json(x) for x in obj]
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, str):
        return _clean_utf8_string(obj)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, Decimal):
        try:
            v = float(obj)
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        except Exception:
            return _clean_utf8_string(str(obj))
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if np is not None:
        if isinstance(obj, (np.integer, np.floating)):
            return sanitize_for_openai_json(
                float(obj) if isinstance(obj, np.floating) else int(obj)
            )
        if isinstance(obj, np.ndarray):
            return sanitize_for_openai_json(obj.tolist())
    if isinstance(obj, bytes):
        return _clean_utf8_string(obj.decode("utf-8", errors="replace"))
    return str(obj)


def _clean_utf8_string(s: str) -> str:
    """JSON 인코딩 시 surrogate 등으로 실패하지 않도록 정규화."""
    return s.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


def verify_json_serializable(payload: Dict[str, Any]) -> str:
    """
    SDK가 보내는 본문과 동일하게 JSON 문자열을 만들 수 있는지 검증.
    반환: 검증에 사용한 JSON 문자열 (로그 재사용 가능).
    """
    try:
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise OpenAIJsonSerializationError(f"OpenAI 요청 payload JSON 직렬화 불가: {e}") from e


def _truncate(s: str, max_len: int = MAX_LOG_JSON_LEN) -> str:
    if len(s) <= max_len:
        return s
    half = max_len // 2
    return s[:half] + "\n... [truncated] ...\n" + s[-(max_len - half) :]


def _mask_secrets_in_text(s: str) -> str:
    """로그 문자열에 포함된 API 키 패턴 마스킹 (sk-...)."""
    return re.sub(r"\bsk-[A-Za-z0-9_-]{10,}\b", "sk-***", s)


def summarize_payload_for_log(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    로그용 요약: messages 안 긴 텍스트·data URL은 길이·앞부분만 (원본 구조 유지).
    """
    if not isinstance(payload, dict):
        return {"_type": type(payload).__name__}

    out: Dict[str, Any] = {}
    for k, v in payload.items():
        if k == "messages" and isinstance(v, list):
            out[k] = [_summarize_message(m) for m in v]
        else:
            out[k] = _summarize_value(v)
    return out


def _summarize_message(m: Any) -> Any:
    if not isinstance(m, dict):
        return m
    role = m.get("role")
    content = m.get("content")
    if isinstance(content, str):
        return {
            "role": role,
            "content": f"<str len={len(content)} preview={_truncate(content, MAX_PREVIEW_CHARS)!r}>",
        }
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "image_url":
                url = (p.get("image_url") or {}).get("url") or ""
                if isinstance(url, str) and url.startswith("data:"):
                    parts.append(
                        {
                            "type": "image_url",
                            "url": f"<data url len={len(url)} chars>",
                        }
                    )
                else:
                    parts.append(
                        {
                            "type": "image_url",
                            "url_preview": _truncate(str(url), 120),
                        }
                    )
            elif isinstance(p, dict) and p.get("type") == "text":
                raw_t = p.get("text")
                t = raw_t if isinstance(raw_t, str) else ("" if raw_t is None else str(raw_t))
                parts.append(
                    {
                        "type": "text",
                        "text_preview": _truncate(t, MAX_PREVIEW_CHARS),
                    }
                )
            else:
                parts.append(_summarize_value(p))
        return {"role": role, "content": parts}
    return {**m, "content": _summarize_value(content)}


def _summarize_value(v: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "<max depth>"
    if isinstance(v, str) and len(v) > MAX_PREVIEW_CHARS:
        return f"<str len={len(v)} preview={_truncate(v, MAX_PREVIEW_CHARS)!r}>"
    if isinstance(v, dict):
        return {kk: _summarize_value(vv, depth + 1) for kk, vv in v.items()}
    if isinstance(v, list):
        if len(v) > 50:
            return [_summarize_value(x, depth + 1) for x in v[:50]] + [f"... (+{len(v) - 50} items)"]
        return [_summarize_value(x, depth + 1) for x in v]
    return v


def log_openai_request_payload(payload: Dict[str, Any], context: str = "") -> None:
    """호출 직전 상세 로그(DEBUG 전용): 요약·json_len·본문 미리보기. 기본 INFO 레벨에서는 출력 안 함."""
    serialized = verify_json_serializable(payload)
    summary = summarize_payload_for_log(payload)
    try:
        summary_json = json.dumps(summary, ensure_ascii=False, allow_nan=False)
    except Exception:
        summary_json = str(summary)
    summary_json = _mask_secrets_in_text(summary_json)
    safe_preview = _mask_secrets_in_text(_truncate(serialized))
    logger.debug(
        "[OpenAI] %s | payload_type=%s | summary_json=%s | json_len=%d | json_stringify_preview=%s",
        context,
        type(payload).__name__,
        summary_json,
        len(serialized),
        safe_preview,
    )


def log_openai_api_error(exc: Exception, payload: Dict[str, Any], context: str = "") -> None:
    """에러 시: 예외 메시지·가능하면 HTTP 본문·마지막으로 검증한 payload 재출력."""
    logger.error("[OpenAI] %s 호출 실패: %s", context, exc)
    status = getattr(exc, "status_code", None)
    if status is not None:
        logger.error("[OpenAI] %s status_code=%s", context, status)
    body = getattr(exc, "body", None)
    if body is not None:
        logger.error("[OpenAI] %s error_body=%s", context, body)
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "text", None):
        try:
            t = resp.text[:2000]
            logger.error("[OpenAI] %s response.text_preview=%s", context, _mask_secrets_in_text(t))
        except Exception:
            pass
    try:
        serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        logger.error(
            "[OpenAI] %s last_payload_json_len=%s | last_payload_preview=%s",
            context,
            len(serialized),
            _mask_secrets_in_text(_truncate(serialized, 8000)),
        )
    except Exception as e:
        logger.error("[OpenAI] %s last_payload 직렬화 실패 (로그용): %s", context, e)


def chat_completions_create_safe(
    client: Any,
    *,
    context: str = "",
    **kwargs: Any,
) -> Any:
    """
    kwargs를 sanitize → JSON 검증 → (DEBUG 시에만) 요청 상세 로그 → client.chat.completions.create(**kwargs).

    재시도(429 등)는 호출부에서 call_with_retry(lambda: chat_completions_create_safe(...))로 감싼다.
    """
    payload: Dict[str, Any] = sanitize_for_openai_json(kwargs)
    assert isinstance(payload, dict)
    verify_json_serializable(payload)
    if logger.isEnabledFor(logging.DEBUG):
        log_openai_request_payload(payload, context=context or "chat.completions.create")
    try:
        return client.chat.completions.create(**payload)
    except Exception as e:
        log_openai_api_error(e, payload, context=context or "chat.completions.create")
        raise


class OpenAIChatCompletionGuard:
    """
    OpenAI chat.completions.create 직전 payload 처리 (sanitize·검증·로깅).
    모듈 수준 함수(chat_completions_create_safe 등)와 동일 동작.
    """

    @staticmethod
    def sanitize(obj: Any) -> Any:
        return sanitize_for_openai_json(obj)

    @staticmethod
    def create_safe(client: Any, *, context: str = "", **kwargs: Any) -> Any:
        return chat_completions_create_safe(client, context=context, **kwargs)
