"""
OCR 테스트용 API (Upstage 전체 응답, bbox 포함)
PDF 업로드 → ページ画像表示・ページ別OCR・キーイン保存
master_code.xlsx B/D열 기준 RAG(임베딩) 유사 코드 추천
"""
import asyncio
import sys
import tempfile
import uuid
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import numpy as np
import fitz  # PyMuPDF
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, List, Any, Dict

try:
    import faiss
except ImportError:
    faiss = None

router = APIRouter()

MASTER_CODE_PATH = project_root / "master_code.xlsx"
B_COLUMN_INDEX = 1  # 0-based (B = 2nd column)
SUGGEST_TOP_N = 3

OCR_TEST_UPLOAD_DIR = Path(tempfile.gettempdir()) / "react_rebate_ocr_test"


def _ensure_upload_dir() -> Path:
    OCR_TEST_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return OCR_TEST_UPLOAD_DIR


def _get_pdf_path(upload_id: str) -> Path:
    return _ensure_upload_dir() / f"{upload_id}.pdf"


class KeyinSaveRequest(BaseModel):
    keyed_values: Dict[str, str] = {}
    image_filename: Optional[str] = None


class SuggestCodesRequest(BaseModel):
    value: str = ""
    field: Optional[str] = None  # "スーパー" のときD列で類似検索、それ以外はB列


def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _get_master_code_rows_af() -> List[Dict[str, str]]:
    """master_code.xlsx A~F열 전체 행 반환 (각 행은 a,b,c,d,e,f 키)"""
    if not MASTER_CODE_PATH.exists():
        return []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(MASTER_CODE_PATH, read_only=True)
        ws = wb.active
        rows = []
        for row in ws.iter_rows(min_row=1, max_col=6, values_only=True):
            # A=0, B=1, C=2, D=3, E=4, F=5
            a = _cell_str(row[0]) if len(row) > 0 else ""
            b = _cell_str(row[1]) if len(row) > 1 else ""
            c = _cell_str(row[2]) if len(row) > 2 else ""
            d = _cell_str(row[3]) if len(row) > 3 else ""
            e = _cell_str(row[4]) if len(row) > 4 else ""
            f = _cell_str(row[5]) if len(row) > 5 else ""
            if b or d:
                rows.append({"a": a, "b": b, "c": c, "d": d, "e": e, "f": f})
        wb.close()
        return rows
    except Exception:
        return []


# ---- master_code RAG (임베딩 + FAISS, B/D열별 캐시) ----
_MASTER_CODE_RAG_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
_master_code_rag_cache: Dict[str, Any] = {
    "mtime": None,
    "model": None,
    "index_b": None,
    "rows_b": None,
    "index_d": None,
    "rows_d": None,
}


def _get_master_code_embedding_model():
    """RAGManager와 동일한 임베딩 모델 (lazy load)."""
    if _master_code_rag_cache["model"] is None:
        import os
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from sentence_transformers import SentenceTransformer
        _master_code_rag_cache["model"] = SentenceTransformer(_MASTER_CODE_RAG_MODEL)
    return _master_code_rag_cache["model"]


def _build_master_code_rag_index():
    """master_code.xlsx 기준 B열/D열 임베딩 + FAISS 인덱스 구축 (파일 mtime 변경 시 재구축)."""
    if not MASTER_CODE_PATH.exists():
        _master_code_rag_cache["mtime"] = None
        _master_code_rag_cache["index_b"] = None
        _master_code_rag_cache["rows_b"] = []
        _master_code_rag_cache["index_d"] = None
        _master_code_rag_cache["rows_d"] = []
        return
    mtime = MASTER_CODE_PATH.stat().st_mtime
    if _master_code_rag_cache["mtime"] == mtime and _master_code_rag_cache["index_b"] is not None:
        return
    rows = _get_master_code_rows_af()
    rows_b = [r for r in rows if r["b"]]
    rows_d = [r for r in rows if r["d"]]
    if not rows_b and not rows_d:
        _master_code_rag_cache["mtime"] = mtime
        _master_code_rag_cache["index_b"] = None
        _master_code_rag_cache["rows_b"] = []
        _master_code_rag_cache["index_d"] = None
        _master_code_rag_cache["rows_d"] = []
        return
    model = _get_master_code_embedding_model()
    dim = model.encode(["dummy"], convert_to_numpy=True).shape[1]

    def build_one(texts: List[str], row_list: List[Dict]) -> tuple:
        if not row_list:
            return None, []
        vecs = model.encode(texts, convert_to_numpy=True).astype(np.float32)
        index = faiss.IndexFlatL2(dim)
        index.add(vecs)
        return index, row_list

    if faiss is None:
        raise ImportError("master_code RAG를 사용하려면 faiss-cpu가 필요합니다: pip install faiss-cpu")
    idx_b, r_b = build_one([r["b"] for r in rows_b], rows_b)
    idx_d, r_d = build_one([r["d"] for r in rows_d], rows_d)
    _master_code_rag_cache["mtime"] = mtime
    _master_code_rag_cache["index_b"] = idx_b
    _master_code_rag_cache["rows_b"] = r_b
    _master_code_rag_cache["index_d"] = idx_d
    _master_code_rag_cache["rows_d"] = r_d


def _search_master_code_rag(query: str, use_d_column: bool, top_k: int = SUGGEST_TOP_N) -> List[Dict[str, str]]:
    """RAG(임베딩)로 master_code에서 유사 코드 상위 top_k건 반환."""
    query = (query or "").strip()
    _build_master_code_rag_index()
    if use_d_column:
        index, rows = _master_code_rag_cache["index_d"], _master_code_rag_cache["rows_d"]
    else:
        index, rows = _master_code_rag_cache["index_b"], _master_code_rag_cache["rows_b"]
    if not rows or index is None or index.ntotal == 0:
        return rows[:top_k] if query else rows[:top_k]
    if not query:
        return rows[:top_k]
    model = _get_master_code_embedding_model()
    q_vec = model.encode([query], convert_to_numpy=True).astype(np.float32)
    k = min(top_k, index.ntotal)
    distances, indices = index.search(q_vec, k)
    result = []
    for idx in indices[0]:
        if idx >= 0 and idx < len(rows):
            result.append(rows[idx])
    return result


@router.post("/suggest-codes")
async def suggest_codes(body: SuggestCodesRequest):
    """
    master_code.xlsx: 受注先はB列、スーパーはD列基準で RAG(임베딩) 유사 3건을 A~F열 전체로 반환.
    """
    value = (body.value or "").strip()
    use_d_column = (body.field or "").strip() == "スーパー"
    try:
        suggestions = await asyncio.to_thread(
            _search_master_code_rag, value, use_d_column, SUGGEST_TOP_N
        )
    except ImportError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"suggestions": suggestions}


@router.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    """
    PDFをアップロードし、一時保存。ページ数を返す。
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDFファイルをアップロードしてください。")
    try:
        pdf_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ファイル読み込みエラー: {e}")
    upload_id = str(uuid.uuid4())
    pdf_path = _get_pdf_path(upload_id)
    _ensure_upload_dir()
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)

    def _get_page_count():
        doc = fitz.open(pdf_path)
        try:
            return doc.page_count
        finally:
            doc.close()

    try:
        num_pages = await asyncio.to_thread(_get_page_count)
    except Exception:
        if pdf_path.exists():
            pdf_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="PDFの読み込みに失敗しました。")
    return {"upload_id": upload_id, "num_pages": num_pages}


@router.get("/pdf-page-image")
async def get_pdf_page_image(upload_id: str, page: int):
    """
    アップロード済みPDFの指定ページを画像で返す。
    """
    if page < 1:
        raise HTTPException(status_code=400, detail="pageは1以上です。")
    pdf_path = _get_pdf_path(upload_id)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="アップロードが見つかりません。")

    def _render_page():
        doc = fitz.open(pdf_path)
        try:
            if page > doc.page_count:
                raise ValueError(f"ページ番号が範囲外です（最大{doc.page_count}）。")
            page_obj = doc.load_page(page - 1)
            pix = page_obj.get_pixmap(dpi=150)
            return pix.tobytes("png")
        finally:
            doc.close()

    try:
        img_bytes = await asyncio.to_thread(_render_page)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return Response(content=img_bytes, media_type="image/png")


class OcrPdfPageRequest(BaseModel):
    upload_id: str
    page: int


@router.post("/ocr-pdf-page")
async def ocr_pdf_page(body: OcrPdfPageRequest):
    """
    アップロード済みPDFの指定ページでUpstage OCRを実行し、結果（words + bbox）を返す。
    """
    pdf_path = _get_pdf_path(body.upload_id)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="アップロードが見つかりません。")
    try:
        from modules.core.extractors.upstage_extractor import get_upstage_extractor
        extractor = get_upstage_extractor(enable_cache=False)
        result = await asyncio.to_thread(
            extractor.extract_from_pdf_page_raw, pdf_path, body.page
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR実行エラー: {e}")
    if result is None:
        raise HTTPException(status_code=502, detail="OCRの結果が取得できませんでした。")
    return result


@router.post("/keyin")
async def save_keyin(body: KeyinSaveRequest):
    """
    キーイン結果(受注先, スーパー等)を保存。現状は受け取り・成功返却のみ。
    """
    # TODO: DBやファイルへ永続化する場合はここで実装
    return {"success": True}


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
        result = await asyncio.to_thread(
            extract_json_with_rag,
            ocr_text=body.ocr_text,
            ocr_words=body.words if body.words else None,
            page_width=body.page_width,
            page_height=body.page_height,
            debug_dir=None,
            page_num=1,
            form_type=body.form_type,
            include_bbox=True,  # OCR 탭: 이미지에 박스 그리기용 좌표 포함
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
        result = await asyncio.to_thread(
            extractor.extract_from_image_raw, image_bytes=image_bytes
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR実行エラー: {e}")

    if result is None:
        raise HTTPException(status_code=502, detail="Upstage OCRの結果が取得できませんでした。APIキーを確認してください。")

    return result
