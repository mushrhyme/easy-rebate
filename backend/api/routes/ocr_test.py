"""
OCR 테스트용 API (Upstage 전체 응답, bbox 포함)
이미지 1장 업로드 → Upstage OCR → 전체 JSON 반환 (텍스트 클릭 하이라이트 UI용)
+ 구조화(좌표付き): OCR 결과를 LLM에 넘겨 _word_indices → _bbox 부여, DB 저장 없이 일회성 반환
"""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from fastapi import APIRouter, File, UploadFile, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Any

router = APIRouter()


class StructureRequest(BaseModel):
    ocr_text: str
    words: List[Any]
    page_width: int
    page_height: int
    form_type: Optional[str] = None


@router.post("/structure")
async def structure_from_ocr(body: StructureRequest):
    """
    OCR 결과(텍스트 + words)를 받아 RAG+LLM으로 구조화하고,
    _word_indices → _bbox 변환까지 수행해 반환. DB 저장 없음(일회성 테스트용).
    """
    try:
        from modules.core.extractors.rag_extractor import extract_json_with_rag
        result = extract_json_with_rag(
            ocr_text=body.ocr_text,
            ocr_words=body.words if body.words else None,
            page_width=body.page_width,
            page_height=body.page_height,
            debug_dir=None,
            page_num=1,
            form_type=body.form_type,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ocr")
async def ocr_image(file: UploadFile = File(...)):
    """
    이미지 파일 1장을 받아 Upstage OCR을 수행하고,
    전체 응답(pages[].words[].boundingBox 포함)을 반환합니다.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="画像ファイルをアップロードしてください。")

    try:
        image_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ファイル読み込みエラー: {e}")

    try:
        from modules.core.extractors.upstage_extractor import get_upstage_extractor
        extractor = get_upstage_extractor(enable_cache=False)
        result = extractor.extract_from_image_raw(image_bytes=image_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR実行エラー: {e}")

    if result is None:
        raise HTTPException(status_code=502, detail="Upstage OCRの結果が取得できませんでした。APIキーを確認してください。")

    return result
