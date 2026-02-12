"""
검색 API
"""
import asyncio
from typing import List, Optional
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Depends, Query

from database.registry import get_db

router = APIRouter()


@router.get("/customer")
async def search_by_customer(
    customer_name: str = Query(..., description="거래처명"),
    exact_match: bool = Query(False, description="완전 일치 여부"),
    form_type: Optional[str] = Query(None, description="양식지 타입 필터"),
    db=Depends(get_db)
):
    """
    거래처명으로 검색
    
    Args:
        customer_name: 거래처명
        exact_match: 완전 일치 여부
        form_type: 양식지 타입 필터 (선택사항)
        db: 데이터베이스 인스턴스
    """
    try:
        results = db.search_items_by_customer(
            customer_name=customer_name,
            exact_match=exact_match,
            form_type=form_type
        )
        print(f"🔍 [search/customer] query={customer_name!r}, items 결과={len(results)}건")
        
        # 파일명과 페이지별로 그룹화
        grouped_results = {}
        for item in results:
            pdf_filename = item.get('pdf_filename')
            page_number = item.get('page_number')
            key = (pdf_filename, page_number)
            
            if key not in grouped_results:
                grouped_results[key] = {
                    'pdf_filename': pdf_filename,
                    'page_number': page_number,
                    'items': [],
                    'form_type': item.get('form_type')
                }
            grouped_results[key]['items'].append(item)
        
        # items 검색 결과가 0이면 page_data.page_meta(JSON 텍스트)에서 폴백 검색
        if len(results) == 0 and customer_name.strip():
            fallback_pages = db.search_pages_by_customer_in_page_meta(customer_name.strip())
            print(f"🔍 [search/customer] items 0건 → page_meta 폴백 검색: {len(fallback_pages)}페이지")
            for row in fallback_pages:
                pdf_filename = row.get('pdf_filename')
                page_number = row.get('page_number')
                if not pdf_filename or not page_number:
                    continue
                key = (pdf_filename, page_number)
                if key in grouped_results:
                    continue
                page_result = db.get_page_result(pdf_filename, page_number)
                if page_result and page_result.get('items'):
                    grouped_results[key] = {
                        'pdf_filename': pdf_filename,
                        'page_number': page_number,
                        'items': page_result['items'],
                        'form_type': row.get('form_type') or (page_result.get('form_type') if isinstance(page_result.get('form_type'), str) else None)
                    }
        
        total_items = sum(len(g['items']) for g in grouped_results.values())
        return {
            "query": customer_name,
            "total_items": total_items,
            "total_pages": len(grouped_results),
            "pages": list(grouped_results.values())
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{pdf_filename}/pages/{page_number}/image")
async def get_page_image_url(
    pdf_filename: str,
    page_number: int,
    db=Depends(get_db)
):
    """
    페이지 이미지 URL 조회 (page_role 정보 포함)

    Args:
        pdf_filename: PDF 파일명
        page_number: 페이지 번호
        db: 데이터베이스 인스턴스
    """
    try:
        # 이미지 파일 경로 조회
        image_path = db.get_page_image_path(pdf_filename, page_number)

        # page_role 정보 조회
        # documents.get_page_meta 와 동일하게 db.get_page_result 를 사용하여
        # current / archive 등 테이블 구조 변경에 상관없이 일관된 방식으로 page_role 을 가져온다.
        page_role = None
        try:
            page_result = db.get_page_result(pdf_filename, page_number)
            if page_result:
                page_role = page_result.get("page_role")
        except Exception:
            # page_role 조회 실패 시 None 유지 (배지 비표시)
            pass

        if not image_path:
            raise HTTPException(status_code=404, detail="Image not found")

        # 파일 시스템 경로를 URL 경로로 변환
        # "static/images/..." -> "/static/images/..."
        if image_path.startswith("static/"):
            # 경로의 각 세그먼트를 개별적으로 인코딩 (슬래시는 유지)
            path_parts = image_path.split('/')
            encoded_parts = [quote(part, safe='') for part in path_parts]
            image_url = '/' + '/'.join(encoded_parts)
        else:
            # 이미 URL 경로인 경우 각 세그먼트를 인코딩
            if image_path.startswith('/'):
                path_parts = image_path[1:].split('/')
                encoded_parts = [quote(part, safe='') for part in path_parts]
                image_url = '/' + '/'.join(encoded_parts)
            else:
                path_parts = image_path.split('/')
                encoded_parts = [quote(part, safe='') for part in path_parts]
                image_url = '/'.join(encoded_parts)

        print(f"🖼️ 이미지 URL 생성: {image_path} -> {image_url}")

        response = {
            "image_url": image_url,
            "format": "jpeg"
        }

        # page_role이 있으면 응답에 포함
        if page_role:
            response["page_role"] = page_role

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _ocr_text_from_upstage_result(result: dict) -> str:
    """Upstage OCR 응답 dict에서 전체 텍스트 추출."""
    if not result or not isinstance(result, dict):
        return ""
    text = result.get("text") or result.get("result") or result.get("content")
    if isinstance(text, str) and text.strip():
        return text.strip()
    if "pages" in result:
        pages = result.get("pages") or []
        parts = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            pt = page.get("text") or page.get("content")
            if isinstance(pt, str) and pt.strip():
                parts.append(pt.strip())
                continue
            words = page.get("words") or []
            if words:
                parts.append(" ".join(w.get("text", "") for w in words if isinstance(w, dict)))
        if parts:
            return "\n".join(parts)
    return ""


@router.get("/{pdf_filename}/pages/{page_number}/ocr-text")
async def get_page_ocr_text(
    pdf_filename: str,
    page_number: int,
    db=Depends(get_db)
):
    """
    페이지 OCR 텍스트 조회 (정답지 생성 탭에서 이미지 아래 표시용)

    1) debug2/{pdf_name}/page_{N}_ocr_text.txt (RAG 파싱 시 저장된 파일)
    2) 저장된 페이지 이미지로 Upstage OCR 실행
    3) PDF 세션 경로에서 추출
    4) result/ 페이지 JSON의 text 필드 시도
    """
    try:
        pdf_name = pdf_filename
        if pdf_name.lower().endswith(".pdf"):
            pdf_name = pdf_name[:-4]

        ocr_text = ""

        # 1) debug2/{pdf_name}/page_{N}_ocr_text.txt (RAG 파싱 시 저장된 OCR 텍스트)
        try:
            from pathlib import Path
            from modules.utils.config import get_project_root

            root = get_project_root()
            debug2_file = root / "debug2" / pdf_name / f"page_{page_number}_ocr_text.txt"
            if debug2_file.exists():
                ocr_text = debug2_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

        # 2) 저장된 페이지 이미지로 OCR
        if not ocr_text.strip():
            try:
                image_path = db.get_page_image_path(pdf_filename, page_number)
                if image_path:
                    from pathlib import Path
                    from modules.utils.config import get_project_root

                    root = get_project_root()
                    full_path = Path(image_path) if Path(image_path).is_absolute() else root / image_path
                    if full_path.exists():
                        image_bytes = full_path.read_bytes()
                        from modules.core.extractors.upstage_extractor import get_upstage_extractor
                        extractor = get_upstage_extractor(enable_cache=False)
                        raw = await asyncio.to_thread(
                            extractor.extract_from_image_raw, image_bytes=image_bytes
                        )
                        if raw:
                            ocr_text = _ocr_text_from_upstage_result(raw)
            except Exception:
                pass

        # 3) PDF 파일에서 직접 추출 시도
        if not ocr_text.strip():
            try:
                from pathlib import Path
                from modules.utils.pdf_utils import find_pdf_path
                from modules.utils.pdf_utils import PdfTextExtractor

                pdf_path_str = find_pdf_path(pdf_name)
                if pdf_path_str:
                    def _extract_pdf_text():
                        ext = PdfTextExtractor()
                        try:
                            return ext.extract_text(Path(pdf_path_str), page_number) or ""
                        finally:
                            ext.close_all()

                    ocr_text = await asyncio.to_thread(_extract_pdf_text)
            except Exception:
                pass

        # 4) result/ 페이지 JSON의 text 필드 시도
        if not ocr_text.strip():
            try:
                from modules.core.storage import PageStorage
                page_data = PageStorage.load_page(pdf_name, page_number)
                if page_data and isinstance(page_data.get("text"), str):
                    ocr_text = page_data["text"]
            except Exception:
                pass

        return {"ocr_text": ocr_text or ""}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
