"""
아이템 관리 API
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Body, Query
from pydantic import BaseModel

from database.registry import get_db
from backend.api.routes.websocket import manager
from backend.core.auth import get_current_user
from backend.unit_price_lookup import split_name_and_capacity, find_similar_products
from backend.core.activity_log import log as activity_log

router = APIRouter()

# 프로젝트 루트 (items.py: backend/api/routes/items.py -> parent*4 = project_root)
_ITEMS_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_UNIT_PRICE_CSV = _ITEMS_PROJECT_ROOT / "database" / "csv" / "unit_price.csv"


# 통계 API는 반드시 동적 경로보다 먼저 정의해야 함
@router.get("/stats/review")
async def get_review_stats(
    db=Depends(get_db)
):
    """
    검토 상태 통계 조회 (최적화: 인덱스 활용 및 쿼리 최적화)
    
    Returns:
        각 페이지별 1次/2次 검토 완료 여부 (모든 아이템이 체크되어야 완료)
        + 검토율 (체크된 아이템 수 / 전체 아이템 수)
    """
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # 각 페이지별 1次/2次 검토 상태 집계 (최적화: 인덱스 활용)
            # idx_items_pdf_page 인덱스를 활용하여 GROUP BY 성능 향상
            # items_current와 items_archive 모두 조회
            cursor.execute("""
                SELECT 
                    pdf_filename,
                    page_number,
                    -- 모든 아이템이 체크되어야 true
                    BOOL_AND(COALESCE(first_review_checked, false)) as first_reviewed,
                    BOOL_AND(COALESCE(second_review_checked, false)) as second_reviewed,
                    -- 검토율 계산용
                    COUNT(*) as total_count,
                    COUNT(*) FILTER (WHERE first_review_checked = true) as first_checked_count,
                    COUNT(*) FILTER (WHERE second_review_checked = true) as second_checked_count
                FROM (
                    SELECT pdf_filename, page_number, first_review_checked, second_review_checked
                    FROM items_current
                    UNION ALL
                    SELECT pdf_filename, page_number, first_review_checked, second_review_checked
                    FROM items_archive
                ) AS all_items
                GROUP BY pdf_filename, page_number
                ORDER BY pdf_filename, page_number
            """)
            rows = cursor.fetchall()
            
            # 페이지별 검토 상태
            page_stats = []
            first_reviewed_count = 0
            first_not_reviewed_count = 0
            second_reviewed_count = 0
            second_not_reviewed_count = 0
            
            for row in rows:
                pdf_filename, page_number, first_reviewed, second_reviewed, total_count, first_checked, second_checked = row
                first_reviewed = bool(first_reviewed) if first_reviewed is not None else False
                second_reviewed = bool(second_reviewed) if second_reviewed is not None else False
                
                # 검토율 계산 (퍼센트)
                first_review_rate = round((first_checked / total_count) * 100) if total_count > 0 else 0
                second_review_rate = round((second_checked / total_count) * 100) if total_count > 0 else 0
                
                page_stats.append({
                    "pdf_filename": pdf_filename,
                    "page_number": page_number,
                    "first_reviewed": first_reviewed,
                    "second_reviewed": second_reviewed,
                    "first_review_rate": first_review_rate,
                    "second_review_rate": second_review_rate,
                    "total_items": total_count,
                    "first_checked_count": first_checked,
                    "second_checked_count": second_checked
                })
                
                if first_reviewed:
                    first_reviewed_count += 1
                else:
                    first_not_reviewed_count += 1
                    
                if second_reviewed:
                    second_reviewed_count += 1
                else:
                    second_not_reviewed_count += 1
            
            return {
                "first_reviewed_count": first_reviewed_count,
                "first_not_reviewed_count": first_not_reviewed_count,
                "second_reviewed_count": second_reviewed_count,
                "second_not_reviewed_count": second_not_reviewed_count,
                "total_pages": len(page_stats),
                "page_stats": page_stats
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/available-year-months")
async def get_available_year_months(db=Depends(get_db)):
    """
    現況フィルタ用。請求年月が設定されている文書の distinct (data_year, data_month) 一覧。
    返却: [{ "year": int, "month": int }, ...] 降順。
    """
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT data_year AS y, data_month AS m
                FROM (
                    SELECT data_year, data_month FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    UNION
                    SELECT data_year, data_month FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                ) t
                ORDER BY y DESC, m DESC
            """)
            rows = cursor.fetchall()
            return {"year_months": [{"year": r[0], "month": r[1]} for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _ym_filter_clause(year: Optional[int], month: Optional[int]) -> tuple[str, tuple]:
    """연월 필터 절과 파라미터 반환. (clause, params) — 둘 다 지정 시에만 필터 적용."""
    if year is not None and month is not None:
        return " AND data_year = %s AND data_month = %s", (year, month)
    return "", ()


def _ym_params_list(year: Optional[int], month: Optional[int], count: int = 1) -> tuple:
    """연월 파라미터를 count회 반복 (여러 CTE용)."""
    if year is not None and month is not None:
        return (year, month) * count
    return ()


@router.get("/stats/review-by-items")
async def get_review_stats_by_items(
    year: Optional[int] = Query(None, description="請求年"),
    month: Optional[int] = Query(None, description="請求月"),
    db=Depends(get_db),
):
    """
    検討状況をアイテム数基準で集計。detail ページ・得意先ありのアイテムのみ対象。
    year/month 指定時はその請求年月で絞り込み。
    """
    ym_clause, _ = _ym_filter_clause(year, month)
    ym_params = _ym_params_list(year, month, 2)  # current + archive
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                WITH non_base_docs AS (
                    SELECT pdf_filename FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                    UNION
                    SELECT pdf_filename FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                ),
                detail_items AS (
                    SELECT i.pdf_filename, i.first_review_checked, i.second_review_checked
                    FROM items_current i
                    INNER JOIN page_data_current p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN non_base_docs d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                    UNION ALL
                    SELECT i.pdf_filename, i.first_review_checked, i.second_review_checked
                    FROM items_archive i
                    INNER JOIN page_data_archive p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN non_base_docs d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                )
                SELECT
                    COUNT(*) AS total_item_count,
                    COUNT(DISTINCT pdf_filename) AS total_document_count,
                    COUNT(*) FILTER (WHERE first_review_checked = true) AS first_checked_count,
                    COUNT(*) FILTER (WHERE second_review_checked = true) AS second_checked_count
                FROM detail_items
            """, ym_params)
            row = cursor.fetchone()
            total = row[0] or 0
            total_docs = row[1] or 0
            first_checked = row[2] or 0
            second_checked = row[3] or 0
            return {
                "total_item_count": total,
                "total_document_count": total_docs,
                "first_checked_count": first_checked,
                "first_not_checked_count": total - first_checked,
                "second_checked_count": second_checked,
                "second_not_checked_count": total - second_checked,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/review-by-user")
async def get_review_stats_by_user(
    year: Optional[int] = Query(None, description="請求年"),
    month: Optional[int] = Query(None, description="請求月"),
    db=Depends(get_db),
):
    """
    検討チェックを誰が何件したか（증빙용 현황판）。
    year/month 指定時はその請求年月で絞り込み。
    """
    ym_clause, _ = _ym_filter_clause(year, month)
    ym_params = _ym_params_list(year, month, 2)
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                WITH non_base_docs AS (
                    SELECT pdf_filename FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                    UNION
                    SELECT pdf_filename FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                ),
                detail_items AS (
                    SELECT i.first_reviewed_by_user_id, i.second_reviewed_by_user_id
                    FROM items_current i
                    INNER JOIN page_data_current p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN non_base_docs d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                    UNION ALL
                    SELECT i.first_reviewed_by_user_id, i.second_reviewed_by_user_id
                    FROM items_archive i
                    INNER JOIN page_data_archive p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN non_base_docs d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                ),
                first_agg AS (
                    SELECT first_reviewed_by_user_id AS user_id, COUNT(*) AS first_checked_count
                    FROM detail_items
                    WHERE first_reviewed_by_user_id IS NOT NULL
                    GROUP BY first_reviewed_by_user_id
                ),
                second_agg AS (
                    SELECT second_reviewed_by_user_id AS user_id, COUNT(*) AS second_checked_count
                    FROM detail_items
                    WHERE second_reviewed_by_user_id IS NOT NULL
                    GROUP BY second_reviewed_by_user_id
                )
                SELECT
                    u.user_id,
                    COALESCE(u.display_name_ja, u.display_name, u.username) AS display_name,
                    COALESCE(f.first_checked_count, 0) AS first_checked_count,
                    COALESCE(s.second_checked_count, 0) AS second_checked_count
                FROM users u
                LEFT JOIN first_agg f ON u.user_id = f.user_id
                LEFT JOIN second_agg s ON u.user_id = s.user_id
                WHERE f.user_id IS NOT NULL OR s.user_id IS NOT NULL
                ORDER BY (COALESCE(f.first_checked_count, 0) + COALESCE(s.second_checked_count, 0)) DESC
            """, ym_params)
            rows = cursor.fetchall()
            return {
                "by_user": [
                    {
                        "user_id": r[0],
                        "display_name": r[1] or str(r[0]),
                        "first_checked_count": int(r[2] or 0),
                        "second_checked_count": int(r[3] or 0),
                    }
                    for r in rows
                ],
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/detail-summary")
async def get_detail_summary(
    year: Optional[int] = Query(None, description="請求年"),
    month: Optional[int] = Query(None, description="請求月"),
    db=Depends(get_db),
):
    """
    detail ページのみ・得意先ありのアイテム数で集計。year/month 指定時はその請求年月で絞り込み。
    """
    ym_clause, _ = _ym_filter_clause(year, month)
    ym_params = _ym_params_list(year, month, 2)
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                WITH doc_info AS (
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                    UNION ALL
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                ),
                detail_items AS (
                    SELECT i.pdf_filename, d.upload_channel, d.form_type, d.data_year, d.data_month
                    FROM items_current i
                    INNER JOIN page_data_current p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN doc_info d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                    UNION ALL
                    SELECT i.pdf_filename, d.upload_channel, d.form_type, d.data_year, d.data_month
                    FROM items_archive i
                    INNER JOIN page_data_archive p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN doc_info d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                )
                SELECT
                    COUNT(*) AS total_item_count,
                    COUNT(DISTINCT pdf_filename) AS total_document_count
                FROM detail_items
            """, ym_params)
            row = cursor.fetchone()
            total_item_count = row[0] or 0
            total_document_count = row[1] or 0

            cursor.execute("""
                WITH doc_info AS (
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                    UNION ALL
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                ),
                detail_items AS (
                    SELECT i.pdf_filename, d.upload_channel, d.form_type, d.data_year, d.data_month
                    FROM items_current i
                    INNER JOIN page_data_current p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN doc_info d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                    UNION ALL
                    SELECT i.pdf_filename, d.upload_channel, d.form_type, d.data_year, d.data_month
                    FROM items_archive i
                    INNER JOIN page_data_archive p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN doc_info d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                )
                SELECT COALESCE(upload_channel, '—') AS ch, COUNT(*) AS cnt
                FROM detail_items
                GROUP BY upload_channel
                ORDER BY cnt DESC
            """, ym_params)
            by_channel = [{"channel": r[0], "item_count": r[1]} for r in cursor.fetchall()]

            cursor.execute("""
                WITH doc_info AS (
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                    UNION ALL
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                ),
                detail_items AS (
                    SELECT i.pdf_filename, d.upload_channel, d.form_type, d.data_year, d.data_month
                    FROM items_current i
                    INNER JOIN page_data_current p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN doc_info d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                    UNION ALL
                    SELECT i.pdf_filename, d.upload_channel, d.form_type, d.data_year, d.data_month
                    FROM items_archive i
                    INNER JOIN page_data_archive p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN doc_info d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                )
                SELECT COALESCE(form_type::text, '—') AS ft, COUNT(*) AS cnt
                FROM detail_items
                GROUP BY form_type
                ORDER BY ft
            """, ym_params)
            by_form_type = [{"form_type": r[0], "item_count": r[1]} for r in cursor.fetchall()]

            cursor.execute("""
                WITH doc_info AS (
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                    UNION ALL
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                ),
                detail_items AS (
                    SELECT i.pdf_filename, d.upload_channel, d.form_type, d.data_year, d.data_month
                    FROM items_current i
                    INNER JOIN page_data_current p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN doc_info d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                    UNION ALL
                    SELECT i.pdf_filename, d.upload_channel, d.form_type, d.data_year, d.data_month
                    FROM items_archive i
                    INNER JOIN page_data_archive p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN doc_info d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                )
                SELECT COALESCE(data_year, 0) AS y, COALESCE(data_month, 0) AS m, COUNT(*) AS cnt
                FROM detail_items
                WHERE (data_year IS NOT NULL AND data_month IS NOT NULL)
                GROUP BY data_year, data_month
                ORDER BY data_year DESC, data_month DESC
                LIMIT 6
            """, ym_params)
            by_year_month = [{"year": r[0], "month": r[1], "item_count": r[2]} for r in cursor.fetchall()]

            cursor.execute("""
                WITH doc_info AS (
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                    UNION ALL
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                ),
                detail_items AS (
                    SELECT i.pdf_filename, d.upload_channel, d.form_type, d.data_year, d.data_month
                    FROM items_current i
                    INNER JOIN page_data_current p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN doc_info d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                    UNION ALL
                    SELECT i.pdf_filename, d.upload_channel, d.form_type, d.data_year, d.data_month
                    FROM items_archive i
                    INNER JOIN page_data_archive p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN doc_info d ON i.pdf_filename = d.pdf_filename
                    WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                        i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                )
                SELECT COALESCE(data_year, 0) AS y, COALESCE(data_month, 0) AS m,
                       COALESCE(form_type::text, '—') AS ft, COUNT(*) AS cnt
                FROM detail_items
                WHERE (data_year IS NOT NULL AND data_month IS NOT NULL)
                GROUP BY data_year, data_month, form_type
                ORDER BY data_year DESC, data_month DESC, form_type
            """, ym_params)
            rows_ym_by_form = cursor.fetchall()
            top_ym = {(d["year"], d["month"]) for d in by_year_month}
            by_year_month_by_form = [
                {"year": r[0], "month": r[1], "form_type": r[2], "item_count": r[3]}
                for r in rows_ym_by_form
                if (r[0], r[1]) in top_ym
            ]

            return {
                "total_item_count": total_item_count,
                "total_document_count": total_document_count,
                "by_channel": by_channel,
                "by_form_type": by_form_type,
                "by_year_month": by_year_month,
                "by_year_month_by_form": by_year_month_by_form,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/by-customer")
async def get_customer_stats(
    limit: int = 100,
    year: Optional[int] = Query(None, description="請求年"),
    month: Optional[int] = Query(None, description="請求月"),
    db=Depends(get_db),
):
    """
    得意先別集計。year/month 指定時はその請求年月で絞り込み。
    """
    ym_clause, _ = _ym_filter_clause(year, month)
    ym_params = _ym_params_list(year, month, 2)
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                WITH non_base_docs AS (
                    SELECT pdf_filename FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                    UNION
                    SELECT pdf_filename FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    """ + ym_clause + """
                ),
                all_items AS (
                    SELECT i.pdf_filename, i.page_number,
                           COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                               i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') AS customer_name
                    FROM items_current i
                    INNER JOIN page_data_current p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN non_base_docs d ON i.pdf_filename = d.pdf_filename
                    UNION ALL
                    SELECT i.pdf_filename, i.page_number,
                           COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                               i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—')
                    FROM items_archive i
                    INNER JOIN page_data_archive p
                      ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number
                      AND p.page_role = 'detail'
                    INNER JOIN non_base_docs d ON i.pdf_filename = d.pdf_filename
                )
                SELECT customer_name,
                       COUNT(DISTINCT pdf_filename) AS document_count,
                       COUNT(DISTINCT (pdf_filename, page_number)) AS page_count,
                       COUNT(*) AS item_count
                FROM all_items
                WHERE customer_name IS NOT NULL AND TRIM(customer_name) != '' AND customer_name != '—'
                GROUP BY customer_name
                ORDER BY item_count DESC
                LIMIT %s
            """, ym_params + (max(1, min(limit, 500)),))
            rows = cursor.fetchall()
            return {
                "customers": [
                    {
                        "customer_name": row[0] or "—",
                        "document_count": row[1],
                        "page_count": row[2],
                        "item_count": row[3],
                    }
                    for row in rows
                ]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ItemCreateRequest(BaseModel):
    """아이템 생성 요청 모델"""
    pdf_filename: str
    page_number: int
    # answer.json 한 행 전체 (예: 請求番号, 得意先, 備考, 税額 등)
    item_data: Dict[str, Any]
    after_item_id: Optional[int] = None  # 특정 행 아래에 추가할 경우 해당 행의 item_id

class ItemUpdateRequest(BaseModel):
    """아이템 업데이트 요청 모델"""
    item_data: Dict[str, Any]  # 아이템 데이터 (得意先, 商品名 등 표준 일본어 키)
    review_status: Optional[Dict[str, Any]] = None  # 검토 상태
    expected_version: int  # 낙관적 락을 위한 예상 버전
    session_id: str  # 세션 ID


class ItemResponse(BaseModel):
    """아이템 응답 모델"""
    item_id: int
    pdf_filename: str
    page_number: int
    item_order: int
    item_data: Dict[str, Any]  # 상품명 등은 item_data['商品名'] 사용
    review_status: Dict[str, Any]
    version: int


@router.get("/{pdf_filename}/pages/{page_number}")
async def get_page_items(
    pdf_filename: str,
    page_number: int,
    db=Depends(get_db)
):
    """
    특정 페이지의 아이템 목록 조회
    
    Args:
        pdf_filename: PDF 파일명
        page_number: 페이지 번호
        db: 데이터베이스 인스턴스
    """
    try:
        items = db.get_items(pdf_filename, page_number)
        
        # 검토 탭 컬럼 순서: 이 문서가 파싱 시 참조한 key_order 우선 (document_metadata.item_data_keys), 없으면 form_type으로 RAG 조회
        item_data_keys: Optional[List[str]] = None
        try:
            doc = db.get_document(pdf_filename)
            if doc:
                form_type = doc.get("form_type")
                doc_meta = doc.get("document_metadata") if isinstance(doc.get("document_metadata"), dict) else None
                if doc_meta and doc_meta.get("item_data_keys"):
                    item_data_keys = doc_meta["item_data_keys"]
                elif form_type:
                    from modules.core.rag_manager import get_rag_manager
                    rag = get_rag_manager()
                    key_order = rag.get_key_order_by_form_type(form_type)
                    if key_order and key_order.get("item_keys"):
                        item_data_keys = key_order["item_keys"]
                    else:
                        print(f"[items API] key_order 없음 또는 item_keys 비어있음 key_order={key_order}")
                else:
                    print(f"[items API] form_type 없음")
            else:
                print(f"[items API] doc 없음")
        except Exception as e:
            print(f"[items API] key_order 조회 예외: {e}")
            pass
        
        # reviewed_by_user_id → display_name 캐시 (증빙용 툴팁)
        user_id_to_name: Dict[int, str] = {}
        for item in items:
            for key in ("first_review", "second_review"):
                rs = (item.get("review_status") or {}).get(key) or {}
                uid = rs.get("reviewed_by_user_id")
                if uid and uid not in user_id_to_name:
                    u = db.get_user_by_id(uid)
                    user_id_to_name[uid] = (
                        (u.get("display_name_ja") or u.get("display_name") or u.get("username") or str(uid))
                        if u else str(uid)
                    )
        
        # 응답 형식 변환
        # db.get_items()는 이미 모든 필드를 평탄화해서 반환하므로,
        # Streamlit 앱과 동일하게 모든 필드를 item_data에 포함
        item_list = []
        for item in items:
            # review_status 구성 (checked, reviewed_at, reviewed_by)
            existing_review_status = item.get("review_status", {})
            fr = existing_review_status.get("first_review") or {}
            sr = existing_review_status.get("second_review") or {}
            review_status = {
                "first_review": {
                    "checked": fr.get("checked", False),
                    "reviewed_at": fr.get("reviewed_at"),
                    "reviewed_by": user_id_to_name.get(fr.get("reviewed_by_user_id")) if fr.get("reviewed_by_user_id") else None,
                },
                "second_review": {
                    "checked": sr.get("checked", False),
                    "reviewed_at": sr.get("reviewed_at"),
                    "reviewed_by": user_id_to_name.get(sr.get("reviewed_by_user_id")) if sr.get("reviewed_by_user_id") else None,
                },
            }
            
            # item_data 추출: Streamlit 앱과 동일하게 메타데이터만 제외
            # Streamlit: display_item = {k: v for k, v in item.items() if k not in ['pdf_filename', 'page_number', 'form_type']}
            # 여기서는 item_data로 분리하되, 모든 데이터 필드를 포함
            item_data = {}
            exclude_keys = {
                'item_id', 'pdf_filename', 'page_number', 'item_order', 
                'version', 'form_type',
                'first_review_checked', 'second_review_checked',
                'first_reviewed_at', 'second_reviewed_at',
                'created_at', 'updated_at', 'review_status'
            }
            
            for key, value in item.items():
                if key not in exclude_keys:
                    item_data[key] = value

            # 商品名이 있으면 unit_price에서 시키리/본부장 자동 매칭 → 그리드에 표시
            if _UNIT_PRICE_CSV.exists():
                product_name = item_data.get("商品名")
                if product_name is not None and str(product_name).strip():
                    try:
                        base_name, capacity = split_name_and_capacity(str(product_name))
                        sub_query = capacity if capacity else None
                        df = find_similar_products(
                            query=base_name,
                            csv_path=_UNIT_PRICE_CSV,
                            col="제품명",
                            top_k=1,
                            min_similarity=0.2,
                            sub_col="제품용량",
                            sub_query=sub_query,
                            sub_min_similarity=0.0,
                        )
                        if not df.empty:
                            row = df.iloc[0]
                            shikiri = row.get("시키리")
                            honbu = row.get("본부장")
                            if shikiri is not None:
                                try:
                                    item_data["仕切"] = float(shikiri) if hasattr(shikiri, "__float__") else shikiri
                                except (TypeError, ValueError):
                                    item_data["仕切"] = shikiri
                            if honbu is not None:
                                try:
                                    item_data["本部長"] = float(honbu) if hasattr(honbu, "__float__") else honbu
                                except (TypeError, ValueError):
                                    item_data["本部長"] = honbu
                    except Exception:
                        pass

            # キー・値 탭에서 JSON 순서 유지: item_data_keys 순으로 item_data 재정렬
            if item_data_keys:
                ordered_item_data: Dict[str, Any] = {}
                for k in item_data_keys:
                    if k in item_data:
                        ordered_item_data[k] = item_data[k]
                for k in item_data:
                    if k not in item_data_keys:
                        ordered_item_data[k] = item_data[k]
                item_data = ordered_item_data

            item_list.append(
                ItemResponse(
                    item_id=item['item_id'],
                    pdf_filename=item['pdf_filename'],
                    page_number=item['page_number'],
                    item_order=item['item_order'],
                    item_data=item_data,
                    review_status=review_status,
                    version=item.get('version', 1),
                )
            )
        return {"items": item_list, "item_data_keys": item_data_keys}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/")
async def create_item(
    item_data: ItemCreateRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    새 아이템 생성

    Args:
        item_data: 생성할 아이템 데이터
        db: 데이터베이스 인스턴스
    """
    try:
        # 문서 존재 확인
        doc = db.get_document(item_data.pdf_filename)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # 페이지 존재 확인 (get_page_result는 느릴 수 있으므로 간단한 확인만 수행)
        # 실제로는 items가 있거나 문서가 있으면 페이지가 존재하는 것으로 간주
        try:
            # 페이지에 아이템이 있는지 간단히 확인
            with db.get_connection() as conn:
                cursor = conn.cursor()
                # current와 archive 모두에서 조회
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM items_current 
                    WHERE pdf_filename = %s AND page_number = %s
                    UNION ALL
                    SELECT COUNT(*) 
                    FROM items_archive 
                    WHERE pdf_filename = %s AND page_number = %s
                """, (item_data.pdf_filename, item_data.page_number, item_data.pdf_filename, item_data.page_number))
                # UNION ALL 결과 합산
                item_count = sum(row[0] for row in cursor.fetchall())
        except Exception:
            pass

        # 아이템 생성
        item_id = db.create_item(
            pdf_filename=item_data.pdf_filename,
            page_number=item_data.page_number,
            item_data=item_data.item_data,
            customer=None,
            after_item_id=item_data.after_item_id
        )

        if item_id == -1:
            error_detail = "Failed to create item"
            if item_data.after_item_id:
                error_detail = f"Failed to create item: after_item_id={item_data.after_item_id} not found"
            raise HTTPException(status_code=500, detail=error_detail)

        activity_log(current_user.get("username"), f"아이템 생성: {item_data.pdf_filename} p.{item_data.page_number}")
        # 생성된 아이템 조회 (응답용)
        items = None
        created_item = None
        
        try:
            items = db.get_items(item_data.pdf_filename, item_data.page_number)
            created_item = next((item for item in items if item.get('item_id') == item_id), None)
        except Exception:
            import traceback
            traceback.print_exc()
            # get_items 실패 시 직접 DB에서 조회 시도
            try:
                from psycopg2.extras import RealDictCursor
                import json
                
                with db.get_connection() as conn:
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    # current와 archive 모두에서 조회
                    cursor.execute("""
                        SELECT item_id, pdf_filename, page_number, item_order, customer,
                               first_review_checked, second_review_checked, item_data, version
                        FROM items_current
                        WHERE item_id = %s
                        UNION ALL
                        SELECT item_id, pdf_filename, page_number, item_order, customer,
                               first_review_checked, second_review_checked, item_data, version
                        FROM items_archive
                        WHERE item_id = %s
                        LIMIT 1
                    """, (item_id, item_id))
                    row = cursor.fetchone()
                    
                    if row:
                        created_item = dict(row)
                        # item_data 파싱
                        if isinstance(created_item.get('item_data'), str):
                            created_item['item_data'] = json.loads(created_item['item_data'])
                        elif not isinstance(created_item.get('item_data'), dict):
                            created_item['item_data'] = {}
                        
                        # review_status 구성
                        created_item['review_status'] = {
                            'first_review': {
                                'checked': created_item.get('first_review_checked', False),
                                'reviewed_at': None
                            },
                            'second_review': {
                                'checked': created_item.get('second_review_checked', False),
                                'reviewed_at': None
                            }
                        }
                        
                        items = [created_item]
                    else:
                        raise HTTPException(status_code=500, detail="Failed to retrieve created item: item not found in database")
            except HTTPException:
                raise
            except Exception as direct_query_error:
                import traceback
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"Failed to retrieve created item: {str(direct_query_error)}")
        
        if not created_item:
            raise HTTPException(status_code=500, detail="Failed to retrieve created item")

        # 응답 형식 변환 (get_page_items와 동일)
        # get_items()는 review_status 객체로 반환하므로, 기존 review_status를 사용하거나 새로 구성
        existing_review_status = created_item.get('review_status', {})
        if existing_review_status:
            review_status = {
                "first_review": {
                    "checked": existing_review_status.get('first_review', {}).get('checked', False)
                },
                "second_review": {
                    "checked": existing_review_status.get('second_review', {}).get('checked', False)
                }
            }
        else:
            # review_status가 없는 경우 (하위 호환성)
            review_status = {
                "first_review": {
                    "checked": created_item.get('first_review_checked', False)
                },
                "second_review": {
                    "checked": created_item.get('second_review_checked', False)
                }
            }

        # item_data 추출
        exclude_keys = {
            'item_id', 'pdf_filename', 'page_number', 'item_order',
            'version', 'form_type',
            'first_review_checked', 'second_review_checked',
            'first_reviewed_at', 'second_reviewed_at',
            'created_at', 'updated_at', 'review_status',
            'customer', '商品名'  # customer는 별도 필드, 商品名은 item_data에만
        }

        response_item_data = {}
        for key, value in created_item.items():
            if key not in exclude_keys:
                response_item_data[key] = value

        # WebSocket 브로드캐스트 (새 아이템 생성 알림)
        await manager.broadcast_item_update(
            pdf_filename=item_data.pdf_filename,
            page_number=item_data.page_number,
            message={
                "type": "item_created",
                "item_id": item_id,
                "item_data": response_item_data
            }
        )

        # 필수 필드 검증
        item_order = created_item.get('item_order')
        if item_order is None:
            raise HTTPException(status_code=500, detail="Missing required field: item_order")
        
        version = created_item.get('version', 1)
        
        try:
            response = ItemResponse(
                item_id=item_id,
                pdf_filename=item_data.pdf_filename,
                page_number=item_data.page_number,
                item_order=item_order,
                item_data=response_item_data,
                review_status=review_status,
                version=version
            )
            return response
        except Exception as validation_error:
            raise HTTPException(status_code=500, detail=f"Failed to create response: {str(validation_error)}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{item_id}")
async def update_item(
    item_id: int,
    update_data: ItemUpdateRequest,
    db=Depends(get_db)
):
    """
    아이템 업데이트 (낙관적 락 적용)
    
    Args:
        item_id: 아이템 ID
        update_data: 업데이트 요청 데이터 (item_data, review_status, expected_version, session_id 포함)
        db: 데이터베이스 인스턴스
    """
    try:
        # update_data에서 필요한 필드 추출
        expected_version = update_data.expected_version
        session_id = update_data.session_id
        
        # 체크 시 "누가/언제" 저장용: 세션에서 현재 사용자 ID 조회
        user_info = db.get_session_user(session_id)
        current_user_id = user_info.get("user_id") if user_info else None
        
        # 아이템 조회
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # current와 archive 모두에서 조회
            cursor.execute("""
                SELECT item_id, pdf_filename, page_number, version
                FROM items_current
                WHERE item_id = %s
                UNION ALL
                SELECT item_id, pdf_filename, page_number, version
                FROM items_archive
                WHERE item_id = %s
                LIMIT 1
            """, (item_id, item_id))
            item = cursor.fetchone()
            
            if not item:
                raise HTTPException(status_code=404, detail="Item not found")
            
            # 버전 확인
            current_version = item[3]
            if current_version != expected_version:
                raise HTTPException(
                    status_code=409,
                    detail="Version conflict. Another user has modified this item."
                )
            
            # 락 확인 (get_items_with_lock_status 사용)
            items_with_locks = db.get_items_with_lock_status(
                pdf_filename=item[1],
                page_number=item[2],
                current_session_id=session_id
            )
            # 현재 아이템의 락 상태 확인
            item_lock_info = next(
                (i for i in items_with_locks if i.get('item_id') == item_id),
                None
            )
            if item_lock_info and item_lock_info.get('is_locked_by_others'):
                locked_by_user_id = item_lock_info.get('locked_by_user_id')
                # user_id가 None인 경우는 만료되었거나 잘못된 락이므로 무시
                if locked_by_user_id is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Item is locked by another user: user_id={locked_by_user_id}"
                    )
            
        # 필드 분리 (_separate_item_fields: 검토 상태/메타만 분리, 得意先 등은 item_data에 유지)
            pdf_filename = item[1]
            doc = db.get_document(pdf_filename)
            form_type = doc.get("form_type") if doc else None
            separated = db._separate_item_fields(update_data.item_data, form_type=form_type)
            
            set_clauses = []
            params = []
            
            # 검토 상태 업데이트 (체크 시 reviewed_at, reviewed_by_user_id 저장)
            if update_data.review_status:
                first_review = update_data.review_status.get('first_review', {})
                second_review = update_data.review_status.get('second_review', {})
                
                if 'checked' in first_review:
                    checked_value = first_review['checked']
                    set_clauses.append("first_review_checked = %s")
                    params.append(bool(checked_value))
                    set_clauses.append("first_reviewed_at = %s")
                    params.append(datetime.now(timezone.utc) if checked_value else None)
                    set_clauses.append("first_reviewed_by_user_id = %s")
                    params.append(current_user_id if checked_value else None)
                
                if 'checked' in second_review:
                    checked_value = second_review['checked']
                    set_clauses.append("second_review_checked = %s")
                    params.append(bool(checked_value))
                    set_clauses.append("second_reviewed_at = %s")
                    params.append(datetime.now(timezone.utc) if checked_value else None)
                    set_clauses.append("second_reviewed_by_user_id = %s")
                    params.append(current_user_id if checked_value else None)
            
            # JSONB 필드 업데이트
            if 'item_data' in separated:
                set_clauses.append("item_data = %s::jsonb")
                import json
                params.append(json.dumps(separated['item_data'], ensure_ascii=False))
            
            # 버전 증가 및 업데이트 시간
            set_clauses.append("version = version + 1")
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            
            # WHERE 조건
            params.append(item_id)
            params.append(expected_version)
            
            if not set_clauses:
                raise HTTPException(status_code=400, detail="No fields to update")
            
            # item_id가 어느 테이블에 있는지 확인
            cursor.execute("""
                SELECT 'current' as table_type FROM items_current WHERE item_id = %s
                UNION ALL
                SELECT 'archive' as table_type FROM items_archive WHERE item_id = %s
                LIMIT 1
            """, (item_id, item_id))
            item_location = cursor.fetchone()
            table_suffix = item_location[0] if item_location else 'current'  # 기본값은 current
            items_table = f"items_{table_suffix}"
            
            sql = f"""
                UPDATE {items_table} 
                SET {', '.join(set_clauses)}
                WHERE item_id = %s
                  AND version = %s
            """
            
            cursor.execute(sql, params)
            
            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=409,
                    detail="Version conflict or item not found"
                )
            
            # document_metadata.item_data_keys 갱신: 편집으로 추가된 키(예: タイプ)가 다음 GET에서 유지되도록
            try:
                doc_meta = doc.get("document_metadata") if isinstance(doc.get("document_metadata"), dict) else {}
                current_keys = list(doc_meta.get("item_data_keys") or [])
                new_keys = list(separated.get("item_data", {}).keys())
                merged = list(dict.fromkeys([*current_keys, *new_keys]))
                if merged:
                    import json as _json
                    meta_json = _json.dumps({**doc_meta, "item_data_keys": merged}, ensure_ascii=False)
                    cursor.execute(
                        "UPDATE documents_current SET document_metadata = %s::jsonb WHERE pdf_filename = %s",
                        (meta_json, pdf_filename),
                    )
            except Exception:
                pass
            
            # 락 해제 (체크박스 업데이트는 락이 없을 수 있으므로 실패해도 계속 진행)
            try:
                db.release_item_lock(item_id, session_id)
            except Exception:
                pass
            
            conn.commit()

            # 검토 체크/해제 활동 로그
            if update_data.review_status:
                first_review = update_data.review_status.get("first_review") or {}
                second_review = update_data.review_status.get("second_review") or {}
                if "checked" in first_review:
                    action = "1차 검토 체크" if first_review["checked"] else "1차 검토 해제"
                    activity_log(user_info.get("username") if user_info else None, f"{action}: {item[1]} p.{item[2]}")
                if "checked" in second_review:
                    action = "2차 검토 체크" if second_review["checked"] else "2차 검토 해제"
                    activity_log(user_info.get("username") if user_info else None, f"{action}: {item[1]} p.{item[2]}")

            # review_status 업데이트 시 WebSocket으로 브로드캐스트
            if update_data.review_status:
                await manager.broadcast_lock_update(
                    pdf_filename=item[1],
                    page_number=item[2],
                    message={
                        "type": "review_status_updated",
                        "item_id": item_id,
                        "review_status": update_data.review_status,
                    }
                )
        
        return {"message": "Item updated successfully", "item_id": item_id}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{item_id}/lock")
async def acquire_item_lock(
    item_id: int,
    session_id: str = Body(..., embed=True),
    db=Depends(get_db)
):
    """
    아이템 락 획득
    
    Args:
        item_id: 아이템 ID
        session_id: 세션 ID (JSON body에 "session_id" 키로 전송)
        db: 데이터베이스 인스턴스
    """
    try:
        # session_id 검증
        if not session_id or not isinstance(session_id, str) or len(session_id.strip()) == 0:
            raise HTTPException(
                status_code=422,
                detail="session_id is required and must be a non-empty string"
            )
        
        # 아이템 존재 확인 및 정보 조회 (브로드캐스트용)
        item_info = None
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                # current와 archive 모두에서 조회
                cursor.execute("""
                    SELECT pdf_filename, page_number
                    FROM items_current
                    WHERE item_id = %s
                    UNION ALL
                    SELECT pdf_filename, page_number
                    FROM items_archive
                    WHERE item_id = %s
                    LIMIT 1
                """, (item_id, item_id))
                item_info = cursor.fetchone()
                
                if not item_info:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Item not found: item_id={item_id}"
                    )
        except HTTPException:
            raise
        except Exception as item_check_error:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to check item: {str(item_check_error)}"
            )
        
        # 락 획득 시도 (만료된 락 강제 정리 포함)
        success, reason = db.acquire_item_lock(item_id=item_id, session_id=session_id, lock_duration_minutes=5, force_cleanup=True)
        
        # 락 획득 성공 시 브로드캐스트
        if success and item_info:
            try:
                await manager.broadcast_lock_update(
                    pdf_filename=item_info[0],
                    page_number=item_info[1],
                    message={
                        "type": "lock_acquired",
                        "item_id": item_id,
                        "session_id": session_id,
                    }
                )
            except Exception:
                pass
        
        if not success:
            # 락 정보 조회
            if item_info:
                try:
                    items_with_locks = db.get_items_with_lock_status(
                        pdf_filename=item_info[0],
                        page_number=item_info[1],
                        current_session_id=session_id
                    )
                    item_lock_info = next(
                        (i for i in items_with_locks if i.get('item_id') == item_id),
                        None
                    )
                    if item_lock_info:
                        locked_by_user_id = item_lock_info.get('locked_by_user_id')
                        is_locked_by_others = item_lock_info.get('is_locked_by_others', False)
                        
                        # user_id가 None이거나 is_locked_by_others가 False인 경우는 잘못된 락이므로 무시하고 재시도
                        if locked_by_user_id is None or not is_locked_by_others:
                            # 만료된 락 강제 정리 후 재시도
                            try:
                                with db.get_connection() as conn:
                                    cursor = conn.cursor()
                                    cursor.execute("""
                                        DELETE FROM item_locks_current WHERE item_id = %s
                                    """, (item_id,))
                                    cursor.execute("""
                                        DELETE FROM item_locks_archive WHERE item_id = %s
                                    """, (item_id,))
                                    conn.commit()
                                # 재시도
                                retry_success, retry_reason = db.acquire_item_lock(item_id=item_id, session_id=session_id, lock_duration_minutes=5, force_cleanup=True)
                                if retry_success:
                                    return {"message": "Lock acquired successfully", "item_id": item_id}
                                else:
                                    reason = retry_reason  # 재시도 실패 원인으로 업데이트
                            except Exception:
                                pass
                        else:
                            raise HTTPException(
                                status_code=409,
                                detail=f"Item is locked by another user: user_id={locked_by_user_id}"
                            )
                except HTTPException:
                    raise
                except Exception:
                    pass
            
            # 실패 원인 메시지 사용 (reason은 위에서 이미 받았으므로 사용 가능)
            error_detail = reason if reason else "Failed to acquire lock"
            raise HTTPException(
                status_code=409,
                detail=error_detail
            )

        return {"message": "Lock acquired successfully", "item_id": item_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{item_id}")
async def delete_item(
    item_id: int,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    """
    아이템 삭제

    Args:
        item_id: 삭제할 아이템 ID
        db: 데이터베이스 인스턴스
    """
    try:
        print(f"🔵 [delete_item] 시작: item_id={item_id}, type={type(item_id)}")
        
        # 아이템 존재 여부 및 정보 조회 (WebSocket 브로드캐스트용)
        # delete_item 메서드 내부에서도 조회하지만, 여기서 먼저 확인
        item_info = None
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                # 먼저 아이템이 존재하는지 확인
                # current와 archive 모두에서 조회
                cursor.execute("""
                    SELECT item_id, pdf_filename, page_number, item_order
                    FROM items_current
                    WHERE item_id = %s
                    UNION ALL
                    SELECT item_id, pdf_filename, page_number, item_order
                    FROM items_archive
                    WHERE item_id = %s
                    LIMIT 1
                """, (item_id, item_id))
                item_info = cursor.fetchone()
                print(f"🔵 [delete_item] DB 쿼리 결과: item_info={item_info}")
                
                if item_info:
                    print(f"✅ [delete_item] 아이템 발견: item_id={item_info[0]}, pdf={item_info[1]}, page={item_info[2]}")
                else:
                    # 디버깅: 전체 아이템 목록 확인
                    cursor.execute("""
                        SELECT item_id, pdf_filename, page_number
                        FROM items_current
                        ORDER BY item_id DESC
                        LIMIT 10
                    """)
                    all_items = cursor.fetchall()
                    print(f"🔍 [delete_item] 최근 10개 아이템: {all_items}")
        except Exception as query_error:
            print(f"❌ [delete_item] 아이템 조회 중 오류: {query_error}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Database query error: {str(query_error)}")

        if not item_info:
            print(f"❌ [delete_item] 아이템을 찾을 수 없음: item_id={item_id}")
            raise HTTPException(status_code=404, detail="Item not found")

        pdf_filename, page_number = item_info[1], item_info[2]
        print(f"✅ [delete_item] 아이템 정보: pdf_filename={pdf_filename}, page_number={page_number}")

        # 아이템 삭제
        print(f"🔵 [delete_item] db.delete_item 호출: item_id={item_id}")
        success = db.delete_item(item_id=item_id)
        print(f"🔵 [delete_item] db.delete_item 결과: success={success}")

        if not success:
            print(f"❌ [delete_item] 아이템 삭제 실패: item_id={item_id}")
            raise HTTPException(status_code=500, detail="Failed to delete item")

        print(f"✅ [delete_item] 아이템 삭제 성공: item_id={item_id}")

        # WebSocket 브로드캐스트 (아이템 삭제 알림)
        try:
            await manager.broadcast_item_update(
                pdf_filename=pdf_filename,
                page_number=page_number,
                message={
                    "type": "item_deleted",
                    "item_id": item_id
                }
            )
            print(f"✅ [delete_item] WebSocket 브로드캐스트 완료")
        except Exception as ws_error:
            print(f"⚠️ [delete_item] WebSocket 브로드캐스트 실패 (무시): {ws_error}")

        activity_log(current_user.get("username"), f"아이템 삭제: {pdf_filename} p.{page_number} (item_id={item_id})")
        return {"message": "Item deleted successfully", "item_id": item_id}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [delete_item] 예외 발생: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{item_id}/lock")
async def release_item_lock(
    item_id: int,
    session_id: str = Body(..., embed=True),
    db=Depends(get_db)
):
    """
    아이템 락 해제
    
    Args:
        item_id: 아이템 ID
        session_id: 세션 ID (JSON body에 "session_id" 키로 전송)
        db: 데이터베이스 인스턴스
    """
    try:
        # 아이템 정보 먼저 조회 (브로드캐스트용) - items_current 또는 items_archive에서 조회
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pdf_filename, page_number
                FROM items_current
                WHERE item_id = %s
                UNION ALL
                SELECT pdf_filename, page_number
                FROM items_archive
                WHERE item_id = %s
                LIMIT 1
            """, (item_id, item_id))
            item_info = cursor.fetchone()
        
        success = db.release_item_lock(item_id=item_id, session_id=session_id)
        
        # 락 해제 성공 시 브로드캐스트
        if success and item_info:
            print(f"🔓 [락 해제] item_id={item_id}, session_id={session_id[:8]}..., pdf={item_info[0]}, page={item_info[1]}")
            await manager.broadcast_lock_update(
                pdf_filename=item_info[0],
                page_number=item_info[1],
                message={
                    "type": "lock_released",
                    "item_id": item_id,
                    "session_id": session_id,
                }
            )
            print(f"✅ [락 해제] 브로드캐스트 호출 완료")
        
        if not success:
            raise HTTPException(
                status_code=422,
                detail="Lock not found or already released"
            )
        
        return {"message": "Lock released successfully", "item_id": item_id}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/locks/session")
async def release_all_locks_by_session(
    session_id: str = Body(..., embed=True),
    db=Depends(get_db)
):
    """
    세션 ID로 잠긴 모든 락 해제 (페이지 언로드 시 사용)
    
    Args:
        session_id: 세션 ID (JSON body에 "session_id" 키로 전송)
        db: 데이터베이스 인스턴스
    """
    try:
        # session_id를 user_id로 변환
        user_info = db.get_session_user(session_id)
        if not user_info:
            return {"message": "Session not found", "released_count": 0}
        
        user_id = user_info['user_id']
        
        # 해제할 락들의 정보 조회 (브로드캐스트용)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT i.pdf_filename, i.page_number, l.item_id
                FROM item_locks_current l
                INNER JOIN items_current i ON l.item_id = i.item_id
                WHERE l.locked_by_user_id = %s
                UNION ALL
                SELECT DISTINCT i.pdf_filename, i.page_number, l.item_id
                FROM item_locks_archive l
                INNER JOIN items_archive i ON l.item_id = i.item_id
                WHERE l.locked_by_user_id = %s
            """, (user_id, user_id))
            locks_info = cursor.fetchall()
        
        # 모든 락 해제
        released_count = db.release_all_locks_by_session(session_id=session_id)
        
        # 각 페이지별로 브로드캐스트
        if released_count > 0:
            # 페이지별로 그룹화
            page_locks: Dict[tuple, List[int]] = {}
            for pdf_filename, page_number, item_id in locks_info:
                key = (pdf_filename, page_number)
                if key not in page_locks:
                    page_locks[key] = []
                page_locks[key].append(item_id)
            
            # 각 페이지에 대해 브로드캐스트
            for (pdf_filename, page_number), item_ids in page_locks.items():
                for item_id in item_ids:
                    await manager.broadcast_lock_update(
                        pdf_filename=pdf_filename,
                        page_number=page_number,
                        message={
                            "type": "lock_released",
                            "item_id": item_id,
                            "session_id": session_id,
                        }
                    )
            print(f"✅ [세션 락 해제] 브로드캐스트 완료: {released_count}개 락 해제")
        
        return {"message": "All locks released successfully", "released_count": released_count}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
