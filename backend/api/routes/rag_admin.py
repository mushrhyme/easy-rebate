"""
RAG / 벡터 DB 관리용 관리자 API
"""

from typing import Optional, Dict, Any, List, Tuple
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from database.registry import get_db
from backend.core.auth import get_current_user
from modules.core.build_faiss_db import build_faiss_db
from modules.core.rag_manager import get_rag_manager
from modules.utils.hash_utils import compute_page_hash, get_page_key


router = APIRouter()


def _ensure_rag_candidate_column(db):
    """
    is_rag_candidate 컬럼이 없으면 추가 (마이그레이션)
    """
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # 컬럼 존재 여부 확인
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'page_data_current' 
                AND column_name = 'is_rag_candidate'
            """)
            if cursor.fetchone():
                # 컬럼이 이미 존재
                return
            
            # 컬럼이 없으면 추가
            cursor.execute("""
                ALTER TABLE page_data_current
                ADD COLUMN IF NOT EXISTS is_rag_candidate BOOLEAN NOT NULL DEFAULT FALSE
            """)
            cursor.execute("""
                ALTER TABLE page_data_archive
                ADD COLUMN IF NOT EXISTS is_rag_candidate BOOLEAN NOT NULL DEFAULT FALSE
            """)
            conn.commit()
    except Exception as e:
        # 마이그레이션 실패해도 계속 진행 (이미 컬럼이 있을 수도 있음)
        pass


def _ensure_admin(user: Dict[str, Any]) -> None:
    """
    관리자 권한 확인 (username 이 'admin' 인 사용자만 허용)
    """
    username = user.get("username")
    if username != "admin":
        raise HTTPException(status_code=403, detail="관리자만 접근할 수 있습니다")


@router.post("/build")
async def build_vector_db(
    payload: Dict[str, Optional[str]] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    벡터 DB 재구축 트리거 (관리자 전용)

    - 선택적으로 form_type(예: '01', '02') 를 지정할 수 있음
      지정하지 않으면 모든 양식 폴더 대상
    - 현재는 img 폴더 기반 build_faiss_db 를 그대로 사용
    """
    _ensure_admin(current_user)

    form_type: Optional[str] = None
    if payload:
        form_type = payload.get("form_type") or None

    # 동기 실행 (요청이 완료될 때까지 대기)
    try:
        build_faiss_db(
            form_folder=form_type,
            auto_merge=True,
            text_extraction_method="excel",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"벡터 DB 생성 중 오류가 발생했습니다: {e}")

    # 최신 통계 조회
    rag_manager = get_rag_manager()
    total_vectors = rag_manager.count_examples()

    db = get_db()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT form_type, SUM(vector_count) AS total_vectors
            FROM rag_vector_index
            GROUP BY form_type
            ORDER BY form_type
            """
        )
        per_form = [
            {"form_type": row[0], "vector_count": int(row[1] or 0)}
            for row in cursor.fetchall()
        ]

    return {
        "success": True,
        "message": "벡터 DB 생성이 완료되었습니다.",
        "total_vectors": int(total_vectors),
        "per_form_type": per_form,
    }


@router.get("/status")
async def get_vector_db_status(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    현재 벡터 DB 상태 조회 (관리자 전용)
    """
    _ensure_admin(current_user)

    rag_manager = get_rag_manager()
    total_vectors = rag_manager.count_examples()

    db = get_db()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT form_type, SUM(vector_count) AS total_vectors
            FROM rag_vector_index
            GROUP BY form_type
            ORDER BY form_type
            """
        )
        per_form = [
            {"form_type": row[0], "vector_count": int(row[1] or 0)}
            for row in cursor.fetchall()
        ]

    return {
        "total_vectors": int(total_vectors),
        "per_form_type": per_form,
    }


class BuildFromLearningPagesRequest(BaseModel):
    """검토 화면에서 선택한 페이지들로 벡터 DB 생성 요청"""

    form_type: Optional[str] = None


@router.get("/learning-flag")
async def get_learning_flag(
    pdf_filename: str,
    page_number: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    특정 페이지가 벡터 DB 학습 대상인지 여부 조회 (관리자 전용)
    """
    _ensure_admin(current_user)

    db = get_db()
    _ensure_rag_candidate_column(db)  # 컬럼이 없으면 자동 추가
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT is_rag_candidate
            FROM page_data_current
            WHERE pdf_filename = %s AND page_number = %s
            """,
            (pdf_filename, page_number),
        )
        row = cursor.fetchone()

    return {"selected": bool(row[0]) if row else False}


class LearningFlagRequest(BaseModel):
    pdf_filename: str
    page_number: int
    selected: bool


@router.post("/learning-flag")
async def set_learning_flag(
    request: LearningFlagRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    특정 페이지의 벡터 DB 학습 대상 플래그 설정 (관리자 전용)
    """
    _ensure_admin(current_user)

    db = get_db()
    _ensure_rag_candidate_column(db)  # 컬럼이 없으면 자동 추가
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE page_data_current
            SET is_rag_candidate = %s, updated_at = CURRENT_TIMESTAMP
            WHERE pdf_filename = %s AND page_number = %s
            """,
            (request.selected, request.pdf_filename, request.page_number),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Page not found")

    return {"success": True}


@router.get("/learning-pages")
async def get_learning_pages(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    현재 벡터 DB 학습 대상으로 체크된 페이지 목록 조회 (관리자 전용)
    """
    _ensure_admin(current_user)

    db = get_db()
    _ensure_rag_candidate_column(db)  # 컬럼이 없으면 자동 추가
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT pdf_filename, page_number
            FROM page_data_current
            WHERE is_rag_candidate = TRUE
            ORDER BY pdf_filename, page_number
            """
        )
        rows = cursor.fetchall()

    pages = [{"pdf_filename": r[0], "page_number": r[1]} for r in rows]
    return {"count": len(pages), "pages": pages}


@router.post("/build-from-learning-pages")
async def build_vector_from_learning_pages(
    request: BuildFromLearningPagesRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    is_rag_candidate = TRUE 로 설정된 페이지들로부터 벡터 DB 생성 (관리자 전용)
    """
    _ensure_admin(current_user)

    db = get_db()
    _ensure_rag_candidate_column(db)  # 컬럼이 없으면 자동 추가
    
    with db.get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT 
                p.pdf_filename,
                p.page_number,
                i.item_id,
                i.item_order,
                i.customer,
                i.product_name,
                i.item_data,
                d.form_type,
                d.data_year,
                d.data_month
            FROM page_data_current p
            JOIN items_current i
              ON i.pdf_filename = p.pdf_filename
             AND i.page_number = p.page_number
            LEFT JOIN documents_current d
              ON p.pdf_filename = d.pdf_filename
            WHERE p.is_rag_candidate = TRUE
            ORDER BY p.pdf_filename, p.page_number, i.item_order
            """
        )
        rows: List[Dict[str, Any]] = cursor.fetchall()

    if not rows:
        raise HTTPException(status_code=400, detail="학습 대상으로 선택된 페이지가 없습니다.")

    # form_type 결정 (요청값 우선, 없으면 문서에서 첫 번째 값 사용)
    form_type_for_index: Optional[str] = request.form_type
    if not form_type_for_index:
        for row in rows:
            doc_form_type = row.get("form_type")
            if doc_form_type:
                form_type_for_index = doc_form_type
                break
        if not form_type_for_index:
            form_type_for_index = ""

    # (pdf_filename, page_number) 단위로 그룹화
    from collections import defaultdict

    pages_map: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["pdf_filename"], row["page_number"])
        pages_map[key].append(row)

    shard_pages: List[Dict[str, Any]] = []

    for (pdf_filename, page_number), item_rows in pages_map.items():
        if not item_rows:
            continue

        # pdf_name (확장자 제거)
        pdf_name = pdf_filename[:-4] if pdf_filename.lower().endswith(".pdf") else pdf_filename

        lines: List[str] = []
        merged_items: List[Dict[str, Any]] = []

        # 연월/폼타입 정보 (첫 행 기준)
        first_row = item_rows[0]
        data_year = first_row.get("data_year")
        data_month = first_row.get("data_month")

        for row in item_rows:
            customer = row.get("customer")
            product_name = row.get("product_name")
            item_data = row.get("item_data") or {}
            item_id = row["item_id"]

            if customer:
                lines.append(f"得意先名: {customer}")
            if product_name:
                lines.append(f"商品名: {product_name}")

            if isinstance(item_data, dict):
                for key in sorted(item_data.keys()):
                    value = item_data.get(key)
                    if value is None:
                        continue
                    lines.append(f"{key}: {value}")

            merged_item: Dict[str, Any] = {}
            if isinstance(item_data, dict):
                merged_item.update(item_data)
            if customer and "得意先名" not in merged_item:
                merged_item["得意先名"] = customer
            if product_name and "商品名" not in merged_item:
                merged_item["商品名"] = product_name
            merged_item["pdf_filename"] = pdf_filename
            merged_item["page_number"] = page_number
            merged_item["item_id"] = item_id

            merged_items.append(merged_item)

        ocr_text = "\n".join(lines)
        if not ocr_text:
            # 내용이 전혀 없으면 스킵
            continue

        answer_json: Dict[str, Any] = {"items": merged_items}

        metadata: Dict[str, Any] = {
            "pdf_name": pdf_name,
            "page_num": page_number,
            "form_type": form_type_for_index,
            "source": "db_learning_pages",
            "data_year": data_year,
            "data_month": data_month,
        }

        page_key = get_page_key(pdf_name, page_number)
        page_hash = compute_page_hash(ocr_text, answer_json)

        shard_pages.append(
            {
                "pdf_name": pdf_name,
                "page_num": page_number,
                "ocr_text": ocr_text,
                "answer_json": answer_json,
                "metadata": metadata,
                "page_key": page_key,
                "page_hash": page_hash,
            }
        )

    if not shard_pages:
        raise HTTPException(status_code=400, detail="벡터화할 유효한 데이터가 없습니다.")

    rag_manager = get_rag_manager()

    result = rag_manager.build_shard(
        shard_pages,
        form_type=form_type_for_index or None,
    )
    if not result:
        raise HTTPException(status_code=500, detail="Shard 생성에 실패했습니다.")

    shard_identifier, _shard_id = result

    merged = rag_manager.merge_shard(shard_identifier)
    if not merged:
        raise HTTPException(
            status_code=500,
            detail="Shard를 base 인덱스에 병합하는 데 실패했습니다.",
        )

    rag_manager.reload_index()
    total_vectors = rag_manager.count_examples()

    db = get_db()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT form_type, SUM(vector_count) AS total_vectors
            FROM rag_vector_index
            GROUP BY form_type
            ORDER BY form_type
            """
        )
        per_form = [
            {"form_type": row[0], "vector_count": int(row[1] or 0)}
            for row in cursor.fetchall()
        ]

    return {
        "success": True,
        "message": "선택된 페이지들로부터 벡터 DB를 생성했습니다.",
        "processed_pages": len(shard_pages),
        "total_vectors": int(total_vectors),
        "per_form_type": per_form,
    }


