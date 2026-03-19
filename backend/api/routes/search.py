"""
검색 API
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import List, Optional

import pandas as pd
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Depends, Query, Body
from pydantic import BaseModel

from database.registry import get_db
from database.db_manager import _similarity_difflib, normalize_company_name_for_similarity
from backend.core.auth import get_current_user_optional, get_current_user
from backend.unit_price_lookup import split_name_and_capacity, find_similar_products
from modules.core.rag_manager import get_rag_manager
from modules.core.extractors.rag_extractor import convert_numpy_types
from modules.utils.config import get_project_root

logger = logging.getLogger(__name__)

router = APIRouter()

# 프로젝트 루트 (search.py: backend/api/routes/search.py -> parent*4 = project_root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_UNIT_PRICE_CSV = _PROJECT_ROOT / "database" / "csv" / "unit_price.csv"
_RETAIL_USER_CSV = _PROJECT_ROOT / "database" / "csv" / "retail_user.csv"
_DIST_RETAIL_CSV = _PROJECT_ROOT / "database" / "csv" / "dist_retail.csv"
_DOMAE_RETAIL_1_CSV = _PROJECT_ROOT / "database" / "csv" / "domae_retail_1.csv"
_DOMAE_RETAIL_2_CSV = _PROJECT_ROOT / "database" / "csv" / "domae_retail_2.csv"
_SAP_RETAIL_CSV = _PROJECT_ROOT / "database" / "csv" / "sap_retail.csv"
_SAP_PRODUCT_CSV = _PROJECT_ROOT / "database" / "csv" / "sap_product.csv"


# ----- sap_retail 검색 (정적 경로를 맨 위에 등록해 404 방지) -----
@router.get("/retail/candidates-by-sap-retail")
async def get_retail_candidates_by_sap_retail(
    query: str = Query("", description="検索語（소매처명・판매처명 등)"),
    top_k: int = Query(10, ge=1, le=30, description="반환 건수"),
    min_similarity: float = Query(0.0, ge=0.0, le=1.0, description="최소 유사도"),
    search_type: str = Query("all", description="all=둘 다 검색, retail=小売先만, vendor=受注先(판매처)만"),
):
    """sap_retail.csv에서 소매처명·판매처명·코드 유사도 검색. search_type=retail/vendor 시 해당 항목만 검색·코드 기준 중복 제거."""
    query = (query or "").strip()
    csv_path = _SAP_RETAIL_CSV
    if not query:
        return {"query": "", "matches": []}
    if not csv_path.exists():
        return {"query": query, "matches": [], "skipped_reason": "sap_retail.csv not found"}
    try:
        df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
        df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
        scored = []
        q_upper = query.upper()
        for _, r in df.iterrows():
            retail_name = (r.get("소매처명") or "").strip()
            dist_name = (r.get("판매처명") or "").strip()
            retail_code = (r.get("소매처코드") or "").strip()
            dist_code = (r.get("판매처코드") or "").strip()
            if not retail_code:
                continue
            s1 = _similarity_difflib(query, retail_name)
            s2 = _similarity_difflib(query, dist_name) if dist_name else 0.0
            part = 0.0
            if search_type != "vendor" and (query in retail_name or (q_upper and q_upper in (retail_name.upper() or ""))):
                part = 0.95 if query in retail_name else 0.9
            elif search_type != "retail" and dist_name and (query in dist_name or (q_upper and q_upper in dist_name.upper())):
                part = 0.95 if query in dist_name else 0.9
            code_score = 0.0
            if search_type != "vendor":
                if query == retail_code:
                    code_score = max(code_score, 1.0)
                elif retail_code.startswith(query):
                    code_score = max(code_score, 0.95)
                elif query in retail_code:
                    code_score = max(code_score, 0.9)
            if search_type != "retail" and dist_code:
                if query == dist_code:
                    code_score = max(code_score, 1.0)
                elif dist_code.startswith(query):
                    code_score = max(code_score, 0.95)
                elif query in dist_code:
                    code_score = max(code_score, 0.9)
            if search_type == "retail":
                score = max(s1, part, code_score)
            elif search_type == "vendor":
                score = max(s2, part, code_score)
            else:
                score = max(s1, s2, part, code_score)
            if score >= min_similarity:
                scored.append((score, retail_code, retail_name, dist_code, dist_name))
        scored.sort(key=lambda x: -x[0])
        # retail: 小売先코드 기준 첫 행만, vendor: 受注先코드(또는 명) 기준 첫 행만
        seen_retail, seen_vendor = set(), set()
        deduped = []
        for sc, rc, rn, dc, dn in scored:
            if search_type == "retail":
                if rc in seen_retail:
                    continue
                seen_retail.add(rc)
            elif search_type == "vendor":
                key = (dc or dn) or ""
                if key in seen_vendor:
                    continue
                seen_vendor.add(key)
            deduped.append((sc, rc, rn, dc, dn))
            if len(deduped) >= top_k:
                break
        matches = [
            {
                "소매처코드": rc,
                "소매처명": rn,
                "판매처코드": dc,
                "판매처명": dn,
                "similarity": round(sc, 4),
            }
            for sc, rc, rn, dc, dn in deduped
        ]
        return {"query": query, "matches": matches}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/retail/sap-row-by-retail-code")
async def get_sap_row_by_retail_code(
    retail_code: str = Query(..., description="소매처코드(小売先コード)"),
):
    """sap_retail에서 소매처코드로 첫 행 조회. SAP受注先・SAP小売先 표시용."""
    code = (retail_code or "").strip()
    if not code:
        return {"retail_code": "", "row": None}
    if not _SAP_RETAIL_CSV.exists():
        return {"retail_code": code, "row": None, "skipped_reason": "sap_retail.csv not found"}
    try:
        df = pd.read_csv(_SAP_RETAIL_CSV, dtype=str, encoding="utf-8-sig")
        df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
        rows = df[df["소매처코드"].astype(str).str.strip() == code]
        if rows.empty:
            return {"retail_code": code, "row": None}
        r = rows.iloc[0]
        return {
            "retail_code": code,
            "row": {
                "소매처코드": (r.get("소매처코드") or "").strip(),
                "소매처명": (r.get("소매처명") or "").strip(),
                "판매처코드": (r.get("판매처코드") or "").strip(),
                "판매처명": (r.get("판매처명") or "").strip(),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/retail/sap-row-by-vendor-code")
async def get_sap_row_by_vendor_code(
    vendor_code: str = Query(..., description="受注先コード(판매처코드)"),
):
    """sap_retail에서 受注先コード(판매처코드)로 첫 행 조회. SAP受注先(판매처명) 표시용."""
    code = (vendor_code or "").strip()
    if not code:
        return {"vendor_code": "", "row": None}
    if not _SAP_RETAIL_CSV.exists():
        return {"vendor_code": code, "row": None, "skipped_reason": "sap_retail.csv not found"}
    try:
        df = pd.read_csv(_SAP_RETAIL_CSV, dtype=str, encoding="utf-8-sig")
        df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
        rows = df[df["판매처코드"].astype(str).str.strip() == code]
        if rows.empty:
            return {"vendor_code": code, "row": None}
        r = rows.iloc[0]
        return {
            "vendor_code": code,
            "row": {
                "소매처코드": (r.get("소매처코드") or "").strip(),
                "소매처명": (r.get("소매처명") or "").strip(),
                "판매처코드": (r.get("판매처코드") or "").strip(),
                "판매처명": (r.get("판매처명") or "").strip(),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


class LearningRequestPageBody(BaseModel):
    """단일 페이지 학습 요청 (검토·정답지 탭 学習リクエスト). 관리자 체크 없음."""
    pdf_filename: str
    page_number: int


@router.post("/learning-request-page")
async def learning_request_page_search(
    body: LearningRequestPageBody,
    current_user=Depends(get_current_user),
):
    """
    해당 페이지만 벡터 DB에 반영. 로그인한 모든 사용자 호출 가능 (관리자 아님).
    검토 탭·정답지 탭의 「学習リクエスト」 버튼용.
    관리자일 경우 성공 후 판매처·소매처 / 제품 RAG 정답지 인덱스 자동 재구축.
    """
    from backend.api.routes import rag_admin
    return await rag_admin.execute_learning_request_page(
        body.pdf_filename, body.page_number, current_user
    )


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
    retail_user.csv 소매처명 전체(중복 제거). 거래처↔담당 유사도 매핑 시 notepad와 동일하게 전체 풀에서 최적 매칭용.
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
    in_vector = await db.run_sync(_get_in_vector_pdf_filenames, db)
    pdfs = await db.run_sync(db.get_review_tab_pdf_filenames, in_vector, year, month)
    customer_names = await db.run_sync(db.get_distinct_customer_names_for_pdfs, pdfs)
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
    pages = await db.run_sync(
        db.get_page_keys_by_customer_names,
        body.customer_names,
        body.form_type,
    )
    return {"pages": pages}


@router.post("/customer-similarity-mapping")
async def post_customer_similarity_mapping(
    body: CustomerSimilarityMappingRequest,
    current_user=Depends(get_current_user),
):
    """
    왼쪽(실제 거래처) 각각에 대해 오른쪽(담당) 중 유사도 최고인 1개 + 점수 반환.
    비교 시 거래처·retail_user 모두 전처리(株式会社/（株）/괄호·기호 제거) 후 difflib 유사도 사용.
    """
    left_list = [s.strip() for s in (body.customer_names or []) if s is not None]
    right_list = [s.strip() for s in (body.super_names or []) if s is not None]
    used_rights = set()
    mapped: List[dict] = []
    for left in left_list:
        best_right = ""
        best_score = 0.0
        left_norm = normalize_company_name_for_similarity(left)
        for right in right_list:
            right_norm = normalize_company_name_for_similarity(right)
            score = _similarity_difflib(left_norm, right_norm)
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
    top_k: int = Query(5, ge=1, le=50, description="반환 건수（평균 유사도 순 상위）"),
    min_similarity: float = Query(0.2, ge=0.0, le=1.0, description="미사용（호환용）"),
    sub_min_similarity: float = Query(0.0, ge=0.0, le=1.0, description="미사용（호환용）"),
):
    """
    제품명·용량 유사도를 각각 계산해 평균으로 정렬한 상위 top_k 반환. min_similarity 필터 없음.
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


@router.get("/product/candidates-by-sap-product")
async def get_product_candidates_by_sap_product(
    query: str = Query("", description="検索語（제품명으로 검색）"),
    top_k: int = Query(10, ge=1, le=30, description="반환 건수"),
    min_similarity: float = Query(0.0, ge=0.0, le=1.0, description="최소 유사도"),
):
    """
    sap_product.csv에서 제품명·商品コード로 검색. 단가 탭 최종후보 검색 → 제품코드만 반환.
    반환: [{ 제품코드, 제품명 }, ...] （仕切・本部長는 unit_price에서 商品コード로 별도 조회）
    """
    q = (query or "").strip()
    if not q:
        return {"query": "", "matches": []}
    if not _SAP_PRODUCT_CSV.exists():
        return {"query": q, "matches": [], "skipped_reason": "sap_product.csv not found"}
    try:
        df_sap = pd.read_csv(_SAP_PRODUCT_CSV, dtype=str, encoding="utf-8-sig")
        df_sap.columns = [c.strip().lstrip("\ufeff") for c in df_sap.columns]
        scored = []
        for _, r in df_sap.iterrows():
            # CSV 컬럼: 제품명 또는 商品名
            name = (r.get("제품명") or r.get("商品名") or "").strip()
            sap_name = (r.get("SAP제품명") or "").strip()
            code = (r.get("제품코드") or r.get("商品コード") or "").strip()
            if not code:
                continue
            s1 = _similarity_difflib(q, name) if name else 0.0
            s2 = _similarity_difflib(q, sap_name) if sap_name else 0.0
            # 商品コード(숫자) 검색: 일치/접두사/포함 시 높은 점수
            code_score = 0.0
            if q == code:
                code_score = 1.0
            elif code.startswith(q):
                code_score = 0.95
            elif q in code:
                code_score = 0.9
            score = max(s1, s2, code_score)
            if score >= min_similarity:
                scored.append((score, code, name or sap_name))
        scored.sort(key=lambda x: (-x[0], -(int(x[1]) if x[1].isdigit() else 0)))
        # 제품명이 동일할 경우 숫자(商品コード)가 더 큰 것만 남김
        seen_name: dict[str, tuple[float, str, str]] = {}
        for score, code, name in scored:
            try:
                code_num = int(code)
            except (ValueError, TypeError):
                code_num = 0
            if name not in seen_name or (int(seen_name[name][1]) if seen_name[name][1].isdigit() else 0) < code_num:
                seen_name[name] = (score, code, name)
        rows = sorted(seen_name.values(), key=lambda x: (-x[0], -(int(x[1]) if x[1].isdigit() else 0)))[:top_k]
        matches = [{"제품코드": code, "제품명": name or ""} for _, code, name in rows]
        return {"query": q, "matches": matches}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/product/name-by-code")
async def get_product_name_by_code(
    code: str = Query(..., description="商品コード（제품코드）"),
):
    """
    sap_product.csv에서 商品コード로 1건 조회해 제품명 반환. 単価 탭 検索 필드 표시용.
    반환: { 제품명: "..." } or { 제품명: null } (없으면 null)
    """
    code = (code or "").strip()
    if not code or not _SAP_PRODUCT_CSV.exists():
        return {"제품명": None}
    try:
        df_sap = pd.read_csv(_SAP_PRODUCT_CSV, dtype=str, encoding="utf-8-sig")
        df_sap.columns = [c.strip().lstrip("\ufeff") for c in df_sap.columns]
        for _, r in df_sap.iterrows():
            c = (r.get("제품코드") or r.get("商品コード") or "").strip()
            if c != code:
                continue
            name = (r.get("제품명") or r.get("商品名") or "").strip()
            return {"제품명": name or None}
        return {"제품명": None}
    except Exception:
        return {"제품명": None}


@router.get("/unit-price-by-product-code")
async def get_unit_price_by_product_code(
    product_code: str = Query(..., description="商品コード（제품코드）"),
):
    """
    unit_price.csv에서 商品コード로 1건 조회. 仕切・本部長 자동완성용.
    반환: { 商品コード, 仕切, 本部長 } or null
    """
    code = (product_code or "").strip()
    if not code:
        return {"row": None}
    if not _UNIT_PRICE_CSV.exists():
        return {"row": None}
    try:
        df = pd.read_csv(_UNIT_PRICE_CSV, dtype=str, encoding="utf-8-sig")
        df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
        for _, r in df.iterrows():
            c = (r.get("제품코드") or "").strip()
            if c != code:
                continue
            try:
                시키리 = float(r.get("시키리") or 0) if pd.notna(r.get("시키리")) else None
                본부장 = float(r.get("본부장") or 0) if pd.notna(r.get("본부장")) else None
            except (TypeError, ValueError):
                시키리, 본부장 = None, None
            return {
                "row": {
                    "商品コード": code,
                    "仕切": 시키리,
                    "本部長": 본부장,
                },
            }
        return {"row": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/retail-candidates-by-customer")
async def get_retail_candidates_by_customer(
    customer_name: str = Query(..., description="거래처명(得意先 등)"),
    top_k: int = Query(20, ge=1, le=100, description="반환 건수"),
    min_similarity: float = Query(0.5, ge=0.0, le=1.0, description="소매처명 최소 유사도"),
):
    """
    거래처명으로 retail_user.csv 소매처명과 유사도 매칭 후보 반환.
    컬럼: 소매처코드, 소매처명, 판매처코드, 판매처명 (판매처는 dist_retail.csv).
    """
    if not _RETAIL_USER_CSV.exists():
        raise HTTPException(status_code=503, detail="retail_user.csv not found")
    customer_name = (customer_name or "").strip()
    if not customer_name:
        return {"customer_name_input": "", "matches": []}
    try:
        df_retail = pd.read_csv(_RETAIL_USER_CSV, dtype=str)
        # (소매처명, 소매처코드) 유사도 계산 → 상위 top_k, min_similarity 이상
        scored = []
        for _, r in df_retail.iterrows():
            name = (r.get("소매처명") or "").strip()
            code = (r.get("소매처코드") or "").strip()
            if not name or not code:
                continue
            score = _similarity_difflib(customer_name, name)
            if score >= min_similarity:
                scored.append((score, name, code))
        scored.sort(key=lambda x: -x[0])
        retail_tuples = scored[:top_k]  # (score, 소매처명, 소매처코드)

        # dist_retail: 소매처코드 → [(판매처코드, 판매처명), ...] (첫 행만 또는 전부)
        dist_by_retail = {}
        if _DIST_RETAIL_CSV.exists():
            df_dist = pd.read_csv(_DIST_RETAIL_CSV, dtype=str)
            for _, r in df_dist.iterrows():
                retail_code = (r.get("소매처코드") or "").strip()
                dist_code = (r.get("판매처코드") or "").strip()
                dist_name = (r.get("판매처명") or "").strip()
                if not retail_code:
                    continue
                if retail_code not in dist_by_retail:
                    dist_by_retail[retail_code] = []
                dist_by_retail[retail_code].append((dist_code, dist_name))

        matches = []
        for score, retail_name, retail_code in retail_tuples:
            dist_list = dist_by_retail.get(retail_code) or [(None, None)]
            for dist_code, dist_name in dist_list:
                matches.append({
                    "소매처코드": retail_code,
                    "소매처명": retail_name,
                    "판매처코드": dist_code or "",
                    "판매처명": dist_name or "",
                    "similarity": round(score, 4),
                })
        return {"customer_name_input": customer_name, "matches": matches}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _dist_by_retail_first() -> dict:
    """소매처코드 → (판매처코드, 판매처명) 첫 행만. dist_retail 기준."""
    out = {}
    if not _DIST_RETAIL_CSV.exists():
        return out
    try:
        df = pd.read_csv(_DIST_RETAIL_CSV, dtype=str)
        for _, r in df.iterrows():
            retail = (r.get("소매처코드") or "").strip()
            dist_c = (r.get("판매처코드") or "").strip()
            dist_n = (r.get("판매처명") or "").strip()
            if retail and retail not in out:
                out[retail] = (dist_c, dist_n)
    except Exception:
        pass
    return out


def _sap_dist_by_retail_first() -> dict:
    """소매처코드 → (판매처코드, 판매처명) 첫 행만. sap_retail 기준."""
    out = {}
    if not _SAP_RETAIL_CSV.exists():
        return out
    try:
        df = pd.read_csv(_SAP_RETAIL_CSV, dtype=str)
        for _, r in df.iterrows():
            retail = (r.get("소매처코드") or "").strip()
            dist_c = (r.get("판매처코드") or "").strip()
            dist_n = (r.get("판매처명") or "").strip()
            if retail and retail not in out:
                out[retail] = (dist_c, dist_n)
    except Exception:
        pass
    return out


def _dist_for_retail(retail_code: str) -> tuple:
    """매핑한 소매처코드로 판매처코드/판매처명 반환. sap_retail 우선, 없으면 dist_retail."""
    code = (retail_code or "").strip()
    if not code:
        return ("", "")
    sap = _sap_dist_by_retail_first()
    if code in sap:
        return sap[code]
    return _dist_by_retail_first().get(code) or ("", "")


@router.get("/retail/by-customer-code")
async def get_retail_by_customer_code(
    customer_code: str = Query(..., description="得意先コード(도매소매처코드)"),
):
    """
    得意先コード(도매소매처코드)로 domae_retail_1 조회 → 해당 행의 소매처코드/소매처명 1건 반환.
    판매처코드/판매처명은 dist_retail에서 조회해 함께 반환.
    """
    customer_code = (customer_code or "").strip()
    if not customer_code:
        return {"customer_code_input": "", "match": None, "skipped_reason": None}
    if not _DOMAE_RETAIL_1_CSV.exists():
        return {"customer_code_input": customer_code, "match": None, "skipped_reason": "domae_retail_1.csv not found"}
    try:
        df = pd.read_csv(_DOMAE_RETAIL_1_CSV, dtype=str)
        # 得意先コード = domae_retail_1의 도매소매처코드(1열). 소매처코드(2열)로 착각하면 안 됨
        row = df[df["도매소매처코드"].astype(str).str.strip() == customer_code]
        if row.empty:
            return {"customer_code_input": customer_code, "match": None, "skipped_reason": None}
        r = row.iloc[0]
        retail_code = (r.get("소매처코드") or "").strip()
        retail_name = (r.get("소매처명") or "").strip()
        dist_c, dist_n = _dist_for_retail(retail_code)
        return {
            "customer_code_input": customer_code,
            "match": {
                "도매소매처코드": customer_code,
                "도매소매처명": "",  # domae_retail_1에는 도매소매처명 컬럼 없음
                "소매처코드": retail_code,
                "소매처명": retail_name,
                "판매처코드": dist_c,
                "판매처명": dist_n,
                "similarity": 1.0,
            },
            "skipped_reason": None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/retail/candidates-by-shop-name")
async def get_retail_candidates_by_shop_name(
    customer_name: str = Query(..., description="거래처명(得意先 등)"),
    top_k: int = Query(5, ge=1, le=20, description="반환 건수"),
    min_similarity: float = Query(0.0, ge=0.0, le=1.0, description="소매처명 최소 유사도"),
):
    """
    거래처명으로 domae_retail_2의 소매처명과 유사도 매칭 후보 반환 (소매처코드 + dist_retail 판매처).
    """
    customer_name = (customer_name or "").strip()
    if not customer_name:
        return {"customer_name_input": "", "matches": []}
    if not _DOMAE_RETAIL_2_CSV.exists():
        return {"customer_name_input": customer_name, "matches": [], "skipped_reason": "domae_retail_2.csv not found"}
    try:
        df = pd.read_csv(_DOMAE_RETAIL_2_CSV, dtype=str, encoding="utf-8-sig")
        df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
        cols = list(df.columns)
        scored = []
        for _, r in df.iterrows():
            # domae_retail_2 1열 = 도매소매처명. 인덱스로 읽어 컬럼명/인코딩 이슈 회피
            domae_name = (str(r.iloc[0]) if len(cols) > 0 else "") or ""
            domae_name = (domae_name or "").strip()
            name = (r.get("소매처명") or "").strip()
            code = (r.get("소매처코드") or "").strip()
            retail_name = (r.get("소매처명") or "").strip()
            # 일부 행만 2열/3열 값이 반대로 들어간 경우: 코드 컬럼에 이름, 이름 컬럼에 코드 → 표시 시 보정
            if code and retail_name:
                code_like = retail_name.isdigit() and len(retail_name) >= 4
                name_like = not code.isdigit() or "■" in code
                if name_like and code_like:
                    code, retail_name = retail_name, code
            if not name or not code:
                continue
            score = _similarity_difflib(customer_name, name)
            if score >= min_similarity:
                scored.append((score, name, code, retail_name, domae_name))
        scored.sort(key=lambda x: -x[0])
        top = scored[:top_k]
        matches = []
        for score, shop_name, retail_code, retail_name, domae_name in top:
            dist_c, dist_n = _dist_for_retail(retail_code)  # 보정된 코드로 판매처 조회
            matches.append({
                "도매소매처코드": "",  # domae_retail_2에는 도매소매처코드 컬럼 없음
                "도매소매처명": domae_name,
                "소매처코드": retail_code,
                "소매처명": retail_name,
                "판매처코드": dist_c,
                "판매처명": dist_n,
                "similarity": round(score, 4),
            })
        return {"customer_name_input": customer_name, "matches": matches}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _retail_code_to_names() -> dict:
    """소매처코드 → (소매처명, 판매처코드, 판매처명). dist_retail 우선, 없으면 retail_user로 소매처명만."""
    out = {}
    if _DIST_RETAIL_CSV.exists():
        try:
            df = pd.read_csv(_DIST_RETAIL_CSV, dtype=str)
            for _, r in df.iterrows():
                rc = (r.get("소매처코드") or "").strip()
                rn = (r.get("소매처명") or "").strip()
                dc = (r.get("판매처코드") or "").strip()
                dn = (r.get("판매처명") or "").strip()
                if rc and rc not in out:
                    out[rc] = (rn, dc, dn)
        except Exception:
            pass
    if _RETAIL_USER_CSV.exists():
        try:
            df = pd.read_csv(_RETAIL_USER_CSV, dtype=str)
            for _, r in df.iterrows():
                rc = (r.get("소매처코드") or "").strip()
                rn = (r.get("소매처명") or "").strip()
                if rc and rc not in out:
                    out[rc] = (rn, "", "")
                elif rc:
                    prev = out[rc]
                    if not prev[0] and rn:
                        out[rc] = (rn, prev[1], prev[2])
        except Exception:
            pass
    return out


@router.get("/retail/candidates-by-rag-answer")
async def get_retail_candidates_by_rag_answer(
    customer_name: str = Query(..., description="거래처명(得意先)"),
    top_k: int = Query(5, ge=1, le=20, description="반환 건수"),
    min_similarity: float = Query(0.0, ge=0.0, le=1.0, description="최소 유사도"),
):
    """
    得意先으로 판매처-소매처 RAG 정답지 벡터 인덱스 검색.
    반환: RetailMatch 형식(得意先, 소매처코드, 소매처명, 판매처코드, 판매처명, similarity).
    """
    customer_name = (customer_name or "").strip()
    if not customer_name:
        return {"customer_name_input": "", "matches": []}
    try:
        rag = get_rag_manager()
        raw = rag.search_retail_rag_answer(customer_name, top_k=top_k, min_similarity=min_similarity)
        if not raw:
            return {"customer_name_input": customer_name, "matches": [], "skipped_reason": "RAG 정답지 인덱스가 비어있거나 검색 결과 없음"}
        code_to_names = _retail_code_to_names()
        matches = []
        for r in raw:
            retail_code = (r.get("小売先コード") or "").strip()
            dist_c = (r.get("受注先コード") or "").strip()
            retail_n, dist_c_lookup, dist_n = code_to_names.get(retail_code, ("", "", ""))
            if not dist_c and dist_c_lookup:
                dist_c = dist_c_lookup
            if not dist_n and dist_c:
                dist_n = _dist_for_retail(retail_code)[1] or dist_n
            sim = r.get("similarity", 0.0)
            matches.append({
                "得意先": r.get("得意先", ""),
                "도매소매처코드": "",
                "도매소매처명": r.get("得意先", ""),
                "소매처코드": retail_code,
                "소매처명": retail_n or retail_code,
                "판매처코드": dist_c,
                "판매처명": dist_n or dist_c,
                "similarity": float(sim) if sim is not None else 0.0,
            })
        return convert_numpy_types({"customer_name_input": customer_name, "matches": matches})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/product/candidates-by-rag-answer")
async def get_product_candidates_by_rag_answer(
    query: str = Query(..., description="商品名（제품명）"),
    top_k: int = Query(5, ge=1, le=20, description="반환 건수"),
    min_similarity: float = Query(0.0, ge=0.0, le=1.0, description="최소 유사도"),
):
    """
    商品名으로 제품 RAG 정답지 벡터 인덱스 검색. 단가 탭에서 RAG 후보 표시·適用용.
    반환: { product_name_input, matches: [{ 商品名, 商品コード, 仕切, 本部長, similarity }], skipped_reason? }
    """
    query = (query or "").strip()
    if not query:
        return {"product_name_input": "", "matches": []}
    try:
        rag = get_rag_manager()
        raw = rag.search_product_rag_answer(query, top_k=top_k, min_similarity=min_similarity)
        if not raw:
            return {
                "product_name_input": query,
                "matches": [],
                "skipped_reason": "RAG 정답지 인덱스가 비어있거나 검색 결과 없음",
            }
        # 商品コード + 商品名 조합 기준 중복 제거
        # - 동일 (商品コード, 商品名)이 여러 후보로 나오면 similarity가 가장 높은 1건만 유지
        best_by_key: dict[tuple[str, str], dict] = {}
        for r in raw:
            code = (r.get("商品コード") or "").strip()
            name = (r.get("商品名") or "").strip()
            if not code and not name:
                continue
            try:
                sim = float(r.get("similarity", 0.0) or 0.0)
            except (TypeError, ValueError):
                sim = 0.0
            key = (code, name)
            prev = best_by_key.get(key)
            if prev is None:
                best_by_key[key] = r
                continue
            try:
                prev_sim = float(prev.get("similarity", 0.0) or 0.0)
            except (TypeError, ValueError):
                prev_sim = 0.0
            if sim > prev_sim:
                best_by_key[key] = r

        deduped_raw = sorted(
            best_by_key.values(),
            key=lambda x: float(x.get("similarity", 0.0) or 0.0),
            reverse=True,
        )

        matches = []
        for r in deduped_raw:
            shikiri = r.get("仕切")
            honbu = r.get("本部長")
            if isinstance(shikiri, str) and shikiri.strip() != "":
                try:
                    shikiri = float(shikiri)
                except (TypeError, ValueError):
                    pass
            if isinstance(honbu, str) and honbu.strip() != "":
                try:
                    honbu = float(honbu)
                except (TypeError, ValueError):
                    pass
            sim = r.get("similarity", 0.0)
            matches.append({
                "商品名": (r.get("商品名") or "").strip(),
                "商品コード": (r.get("商品コード") or "").strip(),
                "仕切": shikiri,
                "本部長": honbu,
                "similarity": float(sim) if sim is not None else 0.0,
            })
        return convert_numpy_types({"product_name_input": query, "matches": matches})
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
    페이지 OCR 텍스트 조회 (정답지 생성 탭 전용).
    DB(page_meta._ocr_text, ocr_text) 우선 사용, debug2 없어도 동작.
    """
    try:
        pdf_name = pdf_filename
        if pdf_name.lower().endswith(".pdf"):
            pdf_name = pdf_name[:-4]

        def _fetch_ocr_from_db():
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT page_meta, ocr_text FROM page_data_current WHERE pdf_filename = %s AND page_number = %s",
                    (pdf_filename, page_number),
                )
                row = cur.fetchone()
            if not row:
                return ""
            meta = row[0] if isinstance(row[0], dict) else (json.loads(row[0]) if row[0] and isinstance(row[0], str) else None)
            if isinstance(meta, dict) and (meta.get("_ocr_text") or "").strip():
                return (meta["_ocr_text"] or "").strip()
            if row[1] and (row[1] or "").strip():
                return (row[1] or "").strip()
            return ""

        try:
            ocr_text = await db.run_sync(_fetch_ocr_from_db)
        except Exception:
            ocr_text = ""

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
    현재 페이지에 대해 Azure OCR을 다시 수행하고 결과를 DB에 저장한 뒤 반환.
    정답지 생성 탭 전용. debug2 폴더는 선택(있으면 저장, 없어도 동작).
    """
    provider = (body.provider or "azure").strip().lower()
    if provider != "azure":
        raise HTTPException(status_code=400, detail="정답지 영역에서는 Azure OCR만 사용 가능합니다.")

    pdf_name = pdf_filename if not pdf_filename.lower().endswith(".pdf") else pdf_filename[:-4]
    root = get_project_root()  # debug2 등 경로 일치 (config 기준)

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

    # DB에 저장: 이후 get_page_ocr_text는 DB에서 읽음 (debug2 없어도 동작)
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE page_data_current SET ocr_text = %s
                WHERE pdf_filename = %s AND page_number = %s
                """,
                (ocr_text, pdf_filename, page_number),
            )
            conn.commit()
    except Exception:
        pass  # 저장 실패해도 응답은 반환

    # debug2: 프로젝트 루트/debug2/pdf_name 하위에 OCR 텍스트 저장
    try:
        debug2_dir = root / "debug2" / pdf_name
        try:
            debug2_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning("debug2 디렉터리 생성 실패: path=%s, error=%s", debug2_dir, e)
            debug2_dir = None
        if debug2_dir is not None:
            out_file = debug2_dir / f"page_{page_number}_ocr_text.txt"
            out_file.write_text(ocr_text, encoding="utf-8")
            logger.info("debug2 저장 완료: %s", out_file)
    except Exception as e:
        logger.warning("debug2 OCR 텍스트 저장 실패: pdf=%s page=%s, error=%s", pdf_filename, page_number, e)

    return {"ocr_text": ocr_text}
