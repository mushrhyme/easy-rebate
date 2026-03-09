"""
img 폴더의 PDF·정답 JSON 기준으로 pgvector(rag_page_embeddings) 벡터 DB를 채우는 스크립트.

build_faiss_db와 동일한 img 폴더 구조를 사용하며, RAG 검색에 쓰이는
rag_page_embeddings 테이블만 upsert합니다. FAISS(rag_vector_index)는 건드리지 않음.

실행 예:
  python -m modules.core.build_pgvector_db
  python -m modules.core.build_pgvector_db finet   # 특정 하위 폴더만
"""

import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

from modules.core.build_faiss_db import (
    find_pdf_pages,
    load_answer_json,
    get_ocr_cache_path,
    load_ocr_cache,
    save_ocr_cache,
)
from modules.core.rag_manager import get_rag_manager
from modules.utils.config import get_project_root, get_extraction_method_for_upload_channel, folder_name_to_upload_channel
from modules.utils.pdf_utils import PdfTextExtractor


def _log(msg: str) -> None:
    print(msg, flush=True)


def _collect_pages_with_ocr(
    img_dir: Path,
    form_folder: str,
    text_extractor: PdfTextExtractor,
) -> List[Dict[str, Any]]:
    """
    img 하위 폴더를 스캔해, OCR 텍스트와 answer_json을 갖춘 페이지 리스트 반환.
    각 항목: pdf_name, page_num, pdf_filename, form_type, ocr_text, answer_json
    """
    pages = find_pdf_pages(img_dir, form_folder, verbose=False)
    result = []
    for p in pages:
        pdf_name = p.get("pdf_name") or ""
        page_num = p.get("page_num") or 0
        pdf_path = p.get("pdf_path")
        answer_path = p.get("answer_json_path")
        form_type = (p.get("form_type") or form_folder or "").strip() or None

        if not answer_path or not answer_path.exists():
            continue
        answer_json = load_answer_json(answer_path)
        if not answer_json:
            continue

        cache_path = get_ocr_cache_path(answer_path, page_num)
        ocr_text = load_ocr_cache(cache_path)
        if not ocr_text and pdf_path and pdf_path.exists():
            ocr_text = text_extractor.extract_text(Path(pdf_path), page_num)
            if ocr_text:
                save_ocr_cache(cache_path, ocr_text)

        if not (ocr_text or "").strip():
            _log(f"  ⚠️ OCR 없음 스킵: {pdf_name} p.{page_num}")
            continue

        pdf_filename = f"{pdf_name}.pdf" if not pdf_name.endswith(".pdf") else pdf_name
        result.append({
            "pdf_name": pdf_name,
            "page_num": page_num,
            "pdf_filename": pdf_filename,
            "form_type": form_type,
            "ocr_text": ocr_text.strip(),
            "answer_json": answer_json,
        })
    return result


def build_pgvector_db(
    img_dir: Optional[Path] = None,
    form_folder: Optional[str] = None,
    text_extraction_method: str = "pymupdf",
) -> None:
    """
    img 폴더 하위를 스캔하여 rag_page_embeddings(pgvector)에만 upsert합니다.

    Args:
        img_dir: img 폴더 경로 (None이면 프로젝트 루트/img)
        form_folder: 하위 폴더 하나만 지정 (예: "finet"). None이면 img 하위 전체
        text_extraction_method: OCR용 추출 방법 (pymupdf / excel 등)
    """
    if img_dir is None:
        img_dir = get_project_root() / "img"
    if not img_dir.exists():
        _log(f"❌ img 폴더를 찾을 수 없습니다: {img_dir}")
        return

    _log("🔄 RAG Manager 초기화 중...")
    try:
        rag_manager = get_rag_manager()
        if not getattr(rag_manager, "use_db", False) or not getattr(rag_manager, "db", None):
            _log("❌ DB 모드가 아니거나 DB 연결이 없습니다. pgvector 업데이트를 할 수 없습니다.")
            return
        _log("✅ RAG Manager 초기화 완료\n")
    except Exception as e:
        _log(f"❌ RAG Manager 초기화 실패: {e}")
        return

    if form_folder:
        form_folders = [form_folder]
    else:
        form_folders = sorted(
            d.name for d in img_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    total_upserted = 0
    for current_form_folder in form_folders:
        _log(f"\n{'='*60}")
        _log(f"📂 폴더 '{current_form_folder}' 처리 중")
        _log(f"{'='*60}\n")

        upload_channel = folder_name_to_upload_channel(current_form_folder)
        extraction_method = get_extraction_method_for_upload_channel(upload_channel)
        extractor = PdfTextExtractor(method=extraction_method, upload_channel=upload_channel)

        try:
            pages_with_ocr = _collect_pages_with_ocr(img_dir, current_form_folder, extractor)
            if not pages_with_ocr:
                _log(f"⚠️ 폴더 '{current_form_folder}': 처리 가능한 페이지가 없습니다.\n")
                continue
            _log(f"✅ {len(pages_with_ocr)}개 페이지 수집 완료\n")

            for i, page in enumerate(pages_with_ocr, 1):
                pdf_filename = page["pdf_filename"]
                page_num = page["page_num"]
                ocr_text = page["ocr_text"]
                answer_json = page["answer_json"]
                form_type = page.get("form_type")

                ok = rag_manager.upsert_page_embedding(
                    pdf_filename,
                    page_num,
                    ocr_text,
                    answer_json,
                    form_type,
                )
                if ok:
                    total_upserted += 1
                    if i % 10 == 0 or i == len(pages_with_ocr):
                        _log(f"  📄 {current_form_folder}: {i}/{len(pages_with_ocr)} upsert 완료")
                else:
                    _log(f"  ⚠️ upsert 실패: {pdf_filename} p.{page_num}")
        finally:
            extractor.close_all()

        _log(f"✅ 폴더 '{current_form_folder}': {len(pages_with_ocr)}페이지 처리\n")

    _log("=" * 60)
    _log(f"📊 pgvector(rag_page_embeddings) 구축 완료: 총 {total_upserted}건 upsert")
    _log("=" * 60)


if __name__ == "__main__":
    _log("🚀 pgvector 벡터 DB 구축 시작\n")
    form_folder = None
    if len(sys.argv) > 1:
        form_folder = sys.argv[1]
        _log(f"📁 지정된 폴더: {form_folder}\n")
    build_pgvector_db(form_folder=form_folder, text_extraction_method="excel")
    _log("\n✅ 완료!")
