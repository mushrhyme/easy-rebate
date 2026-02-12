"""
분석 LLM 등 설정 API (UI에서 변경 가능)
"""
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter()

# 프로젝트 루트 (backend/main.py 기준 parent.parent)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_RAG_PROVIDER_FILE = _PROJECT_ROOT / "config" / "rag_provider.json"

ALLOWED_PROVIDERS = ("gemini", "gpt5.2")


def _read_rag_provider() -> str:
    """설정 파일에서 rag_provider 값을 읽음. 없으면 'gemini'."""
    if not _RAG_PROVIDER_FILE.exists():
        return "gemini"
    try:
        data = json.loads(_RAG_PROVIDER_FILE.read_text(encoding="utf-8"))
        p = (data.get("provider") or "gemini").strip().lower()
        return p if p in ALLOWED_PROVIDERS else "gemini"
    except Exception:
        return "gemini"


def _write_rag_provider(provider: str) -> None:
    """설정 파일에 rag_provider 저장."""
    if provider not in ALLOWED_PROVIDERS:
        raise ValueError(f"provider must be one of {ALLOWED_PROVIDERS}")
    _RAG_PROVIDER_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RAG_PROVIDER_FILE.write_text(
        json.dumps({"provider": provider}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@router.get("/rag-provider")
async def get_rag_provider():
    """분석(기본 RAG)에 사용할 LLM: gemini | gpt5.2"""
    return {"provider": _read_rag_provider()}


@router.put("/rag-provider")
async def set_rag_provider(body: dict):
    """분석 LLM 설정 변경. body: { "provider": "gemini" | "gpt5.2" }"""
    provider = (body.get("provider") or "").strip().lower()
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"provider must be one of {list(ALLOWED_PROVIDERS)}",
        )
    _write_rag_provider(provider)
    return {"provider": provider}
