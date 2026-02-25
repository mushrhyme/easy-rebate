"""
검색 API
"""
import asyncio
import json
from pathlib import Path
from typing import List, Optional

import pandas as pd
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Depends, Query, Body
from pydantic import BaseModel

from database.registry import get_db
from database.db_manager import _similarity_difflib
from backend.core.auth import get_current_user_optional, get_current_user
from backend.unit_price_lookup import split_name_and_capacity, find_similar_products

router = APIRouter()

# 프로젝트 루트 (search.py: backend/api/routes/search.py -> parent*4 = project_root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_UNIT_PRICE_CSV = _PROJECT_ROOT / "database" / "csv" / "unit_price.csv"


def _get_in_vector_pdf_filenames(db) -> List[str]:
    """rag_vector_index에서 벡터 인덱스에 포함된 pdf_filename 목록 반환."""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT metadata_json FROM rag_vector_index
                WHERE index_name = 'base' AND (form_type IS NULL OR form_type = '')
                ORDER BY updated_at DESC LIMIT 1
            """)
            row = cursor.fetchone()
        if not row:
            return []
        meta = row[0]
        if meta is None:
            return []
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                return []
        if not isinstance(meta, dict):
            return []
        metadata_dict = meta.get("metadata") or meta.get("Metadata") or {}
        pdf_names = set()
        for _doc_id, doc_data in (metadata_dict or {}).items():
            if not isinstance(doc_data, dict):
                continue
            inner = doc_data.get("metadata") or doc_data.get("Metadata") or {}
            pn = (inner or {}).get("pdf_name") or (inner or {}).get("pdf_filename")
            if pn:
                pdf_names.add(pn)
        return [
            p if (p and str(p).lower().endswith(".pdf")) else f"{p}.pdf"
            for p in pdf_names
        ]
    except Exception:
        return []


class PagesByCustomersRequest(BaseModel):
    customer_names: List[str]
    form_type: Optional[str] = None


class CustomerSimilarityMappingRequest(BaseModel):
    """거래처(왼쪽) vs 담당(오른쪽) 유사도 매핑 요청. notepad find_similar_supers와 동일한 difflib 사용."""
    customer_names: List[str]
    super_names: List[str]


@router.get("/customer")
async def search_by_customer(
    customer_name: str = Query(..., description="거래처명"),
    exact_match: bool = Query(False, description="완전 일치 여부"),
    form_type: Optional[str] = Query(None, description="양식지 타입 필터"),
    my_supers_only: bool = Query(False, description="로그인 사용자 담당 슈퍼만 (유사도 90% 이상)"),
    db=Depends(get_db),
    current_user=Depends(get_current_user_optional),
):
    """
    거래처명으로 검색.
    my_supers_only=True이면 로그인 필요, 담당 슈퍼명과 유사도 90% 이상인 항목만 반환.
    """
    if my_supers_only and not current_user:
        raise HTTPException(status_code=401, detail="내 담당만 보려면 로그인이 필요합니다")
    super_names: Optional[List[str]] = None
    if my_supers_only and current_user:
        from modules.utils.retail_user_utils import get_super_names_for_username
        super_names = get_super_names_for_username(current_user["username"] or "")
        if not super_names:
            return {"query": customer_name, "total_items": 0, "total_pages": 0, "pages": []}
    try:
        results = db.search_items_by_customer(
            customer_name=customer_name,
            exact_match=exact_match,
            form_type=form_type,
            super_names=super_names,
            min_similarity=0.9,
        )
        print(f"🔍 [search/customer] query={customer_name!r}, my_supers_only={my_supers_only}, items 결과={len(results)}건")
        
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


@router.get("/my-supers")
async def get_my_supers(current_user=Depends(get_current_user)):
    """
    로그인 사용자 담당 거래처(슈퍼) 목록 (retail_user.csv 기준).
    검토 탭에서 거래처 목록 버튼 클릭 시 "내 담당 거래처" 표시용.
    """
    from modules.utils.retail_user_utils import get_super_names_for_username
    super_names = get_super_names_for_username(current_user["username"] or "")
    return {"super_names": super_names}


@router.get("/all-super-names")
async def get_all_super_names_route(current_user=Depends(get_current_user)):
    """
    retail_user.csv 대표슈퍼명 전체(중복 제거). 거래처↔담당 유사도 매핑 시 notepad와 동일하게 전체 풀에서 최적 매칭용.
    """
    from modules.utils.retail_user_utils import get_all_super_names
    return {"super_names": get_all_super_names()}


@router.get("/my-super-pages")
async def get_my_super_pages(
    form_type: Optional[str] = Query(None, description="양식지 타입 필터"),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    로그인 사용자 담당 슈퍼(거래처)에 해당하는 항목이 있는 페이지 목록.
    retail_user.csv 기준, 검토 탭 "내 담당만" 필터용 (유사도 90% 이상).
    """
    from modules.utils.retail_user_utils import get_super_names_for_username
    super_names = get_super_names_for_username(current_user["username"] or "")
    pages = db.get_page_keys_by_super_names(
        super_names=super_names,
        form_type=form_type,
        min_similarity=0.9,
    )
    return {"pages": pages}


@router.get("/review-tab-customers")
async def get_review_tab_customers(
    year: Optional[int] = Query(None, description="연도 (선택, 없으면 전체)"),
    month: Optional[int] = Query(None, description="월 (선택, 없으면 전체)"),
    db=Depends(get_db),
):
    """
    검토 탭에 있는 모든 거래처 목록 (정답지·벡터 등록 문서 제외, items의 得意先/customer 중복 제거).
    검토 탭에서 거래처 목록 버튼 클릭 시 "검토 탭 전체 거래처" 표시용.
    """
    in_vector = _get_in_vector_pdf_filenames(db)
    pdfs = db.get_review_tab_pdf_filenames(in_vector, year=year, month=month)
    customer_names = db.get_distinct_customer_names_for_pdfs(pdfs)
    return {"customer_names": customer_names}


@router.post("/pages-by-customers")
async def post_pages_by_customers(
    body: PagesByCustomersRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    선택한 customer명 목록에 해당하는 항목이 있는 페이지 목록 반환 (완전 일치).
    모달에서 確認 후 필터 적용용.
    """
    if not body.customer_names:
        return {"pages": []}
    pages = db.get_page_keys_by_customer_names(
        customer_names=body.customer_names,
        form_type=body.form_type,
    )
    return {"pages": pages}


@router.post("/customer-similarity-mapping")
async def post_customer_similarity_mapping(
    body: CustomerSimilarityMappingRequest,
    current_user=Depends(get_current_user),
):
    """
    왼쪽(실제 거래처) 각각에 대해 오른쪽(담당) 중 유사도 최고인 1개 + 점수 반환.
    notepad.ipynb find_similar_supers와 동일한 difflib 유사도 사용 (Levenshtein 아님).
    """
    left_list = [s.strip() for s in (body.customer_names or []) if s is not None]
    right_list = [s.strip() for s in (body.super_names or []) if s is not None]
    used_rights = set()
    mapped: List[dict] = []
    for left in left_list:
        best_right = ""
        best_score = 0.0
        for right in right_list:
            score = _similarity_difflib(left, right)
            if score > best_score:
                best_score = score
                best_right = right
        if best_right:
            used_rights.add(best_right)
        mapped.append({"left": left, "right": best_right, "score": round(best_score, 4)})
    unmapped_rights = [r for r in right_list if r not in used_rights]
    return {"mapped": mapped, "unmapped_rights": unmapped_rights}


@router.get("/unit-price-by-product")
async def get_unit_price_by_product(
    product_name: str = Query(..., description="商品名（제품명）"),
    top_k: int = Query(10, ge=1, le=50, description="반환 건수"),
    min_similarity: float = Query(0.2, ge=0.0, le=1.0, description="제품명 최소 유사도"),
    sub_min_similarity: float = Query(0.0, ge=0.0, le=1.0, description="제품용량 최소 유사도"),
):
    """
    제품명(商品名)을 입력받아 용량을 분리하고, unit_price.csv에서 제품명·용량 유사도로
    매칭된 시키리/본부장 단가 목록을 반환. 검토 탭에서 그리드 추가용.
    """
    if not _UNIT_PRICE_CSV.exists():
        raise HTTPException(status_code=503, detail="unit_price.csv not found")
    try:
        base_name, capacity = split_name_and_capacity(product_name)
        sub_query = capacity if capacity else None
        df = find_similar_products(
            query=base_name,
            csv_path=_UNIT_PRICE_CSV,
            col="제품명",
            top_k=top_k,
            min_similarity=min_similarity,
            sub_col="제품용량",
            sub_query=sub_query,
            sub_min_similarity=sub_min_similarity,
        )
        # NaN 등 처리하여 JSON 직렬화 가능한 리스트로 변환
        records = []
        for _, row in df.iterrows():
            rec = row.to_dict()
            for k, v in rec.items():
                if hasattr(v, "item") and callable(getattr(v, "item", None)):
                    try:
                        rec[k] = v.item()
                    except (ValueError, AttributeError):
                        rec[k] = None if pd.isna(v) else v
                elif hasattr(v, "__float__") and pd.isna(v):
                    rec[k] = None
                else:
                    rec[k] = v
            records.append(rec)
        return {
            "base_name": base_name,
            "capacity": capacity,
            "product_name_input": product_name,
            "matches": records,
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
            # 이미지가 아직 DB에 없어도 404 대신 200 + image_url: null 반환 (검토 탭 등에서 에러 대신 안내 표시)
            return {
                "image_url": None,
                "format": "jpeg",
                **({"page_role": page_role} if page_role else {}),
            }

        # Windows 등에서 DB에 백슬래시로 저장된 경로를 URL용 슬래시로 정규화
        image_path = image_path.replace("\\", "/")

        # 파일 시스템 경로를 URL 경로로 변환 ("static/images/..." -> "/static/images/...")
        if image_path.startswith("static/"):
            path_parts = image_path.split("/")
            encoded_parts = [quote(part, safe="") for part in path_parts]
            image_url = "/" + "/".join(encoded_parts)
        elif image_path.startswith("/"):
            path_parts = image_path[1:].split("/")
            encoded_parts = [quote(part, safe="") for part in path_parts]
            image_url = "/" + "/".join(encoded_parts)
        else:
            path_parts = image_path.split("/")
            encoded_parts = [quote(part, safe="") for part in path_parts]
            image_url = "/" + "/".join(encoded_parts)

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


@router.get("/{pdf_filename}/pages/{page_number}/ocr-text")
async def get_page_ocr_text(
    pdf_filename: str,
    page_number: int,
    db=Depends(get_db)
):
    """
    페이지 OCR 텍스트 조회 (정답지 생성 탭에서 이미지 아래 표시용)

    1) debug2/{pdf_name}/page_{N}_ocr_text.txt (RAG 파싱 시 저장된 파일)
    2) 저장된 페이지 이미지로 Azure OCR(표 복원)
    3) PDF 세션 경로에서 Azure(표 복원) 또는 PyMuPDF 추출
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

        # 2) 저장된 페이지 이미지로 Azure OCR(표 복원)
        if not ocr_text.strip():
            try:
                image_path = db.get_page_image_path(pdf_filename, page_number)
                if image_path:
                    from pathlib import Path
                    from modules.utils.config import get_project_root
                    from modules.core.extractors.azure_extractor import get_azure_extractor
                    from modules.utils.table_ocr_utils import raw_to_full_text

                    root = get_project_root()
                    full_path = Path(image_path) if Path(image_path).is_absolute() else root / image_path
                    if full_path.exists():
                        extractor = get_azure_extractor(model_id="prebuilt-layout", enable_cache=False)
                        raw = await asyncio.to_thread(
                            extractor.extract_from_image_raw, image_path=full_path
                        )
                        if raw:
                            ocr_text = raw_to_full_text(raw)  # 표시용: 인식한 전체 문자열
            except Exception:
                pass

        # 3) PDF 파일에서 Azure(표 복원) 또는 PyMuPDF 추출
        if not ocr_text.strip():
            try:
                from pathlib import Path
                from modules.utils.pdf_utils import find_pdf_path, PdfTextExtractor

                pdf_path_str = find_pdf_path(pdf_name)
                if pdf_path_str:
                    def _extract_pdf_text():
                        ext = PdfTextExtractor(upload_channel="mail")
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


class RerunOcrBody(BaseModel):
    """OCR 다시 인식 요청 (정답지 탭: Azure 전용)"""
    provider: str = "azure"  # 정답지 영역에서는 Azure만 사용
    azure_model: Optional[str] = None  # prebuilt-read | prebuilt-layout | prebuilt-document (기본 prebuilt-layout)


@router.post("/{pdf_filename}/pages/{page_number}/ocr-rerun")
async def rerun_page_ocr(
    pdf_filename: str,
    page_number: int,
    body: RerunOcrBody,
    db=Depends(get_db),
):
    """
    현재 페이지에 대해 Azure OCR을 다시 수행하고 결과를 debug2에 저장한 뒤 반환.
    정답지 생성 탭 전용 — 저장되는 OCR 텍스트는 항상 Azure.
    """
    provider = (body.provider or "azure").strip().lower()
    if provider != "azure":
        raise HTTPException(status_code=400, detail="정답지 영역에서는 Azure OCR만 사용 가능합니다.")

    pdf_name = pdf_filename if not pdf_filename.lower().endswith(".pdf") else pdf_filename[:-4]
    root = Path(__file__).resolve().parent.parent.parent.parent  # project root

    # 1) 페이지 이미지 경로 (DB) 또는 PDF 경로 확보
    image_path = db.get_page_image_path(pdf_filename, page_number)
    full_image_path = None
    if image_path:
        full_image_path = Path(image_path) if Path(image_path).is_absolute() else root / image_path
        if not full_image_path.exists():
            full_image_path = None

    pdf_path_str = None
    if not full_image_path:
        from modules.utils.pdf_utils import find_pdf_path
        pdf_path_str = find_pdf_path(pdf_name)
    pdf_path = Path(pdf_path_str) if pdf_path_str and Path(pdf_path_str).exists() else None

    if not full_image_path and not pdf_path:
        raise HTTPException(
            status_code=404,
            detail="페이지 이미지 또는 PDF를 찾을 수 없습니다. 이미지 저장 후 다시 시도하세요.",
        )

    ocr_text = ""

    if provider == "azure":
        try:
            from modules.core.extractors.azure_extractor import get_azure_extractor
            from modules.utils.table_ocr_utils import raw_to_full_text

            azure_model = (body.azure_model or "prebuilt-layout").strip() or "prebuilt-layout"
            extractor = get_azure_extractor(model_id=azure_model, enable_cache=False)
            raw = None
            if full_image_path:
                raw = await asyncio.to_thread(extractor.extract_from_image_raw, image_path=full_image_path)
            elif pdf_path:
                raw = await asyncio.to_thread(
                    extractor.extract_from_pdf_page_raw, pdf_path, page_number
                )
            if raw:
                ocr_text = raw_to_full_text(raw) or ""  # 표시용: 인식한 전체 문자열
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Azure OCR 실패: {e}")

    if not ocr_text.strip():
        raise HTTPException(
            status_code=422,
            detail="OCR 결과가 비어 있습니다. 이미지 품질 또는 페이지를 확인하세요.",
        )

    # debug2에 저장하여 이후 get_page_ocr_text에서 이 결과를 사용하도록 함
    debug2_dir = root / "debug2" / pdf_name
    debug2_dir.mkdir(parents=True, exist_ok=True)
    ocr_file = debug2_dir / f"page_{page_number}_ocr_text.txt"
    ocr_file.write_text(ocr_text, encoding="utf-8")

    return {"ocr_text": ocr_text}
