"""
아이템 관리 API
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Body, Query
from pydantic import BaseModel

from database.registry import get_db
from database.db_manager import _similarity_difflib
from modules.utils.retail_resolve import resolve_retail_dist
from backend.api.routes.websocket import manager
from backend.core.auth import get_current_user
from backend.unit_price_lookup import split_name_and_capacity, find_similar_products
from backend.core.activity_log import log as activity_log

router = APIRouter()

# 프로젝트 루트 (items.py: backend/api/routes/items.py -> parent*4 = project_root)
_ITEMS_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_UNIT_PRICE_CSV = _ITEMS_PROJECT_ROOT / "database" / "csv" / "unit_price.csv"


def _resolved_frozen_codes(item_data: Dict[str, Any], customer_fallback: Optional[str] = None) -> tuple:
    """
    1→2→3 순서로 매핑 확정. 이미 item_data에 受注先コード/小売先コード 있으면 사용.
    없으면 resolve_retail_dist(得意先, 得意先コード)로 계산.
    반환: (frozen_retail_code=小売先コード, frozen_dist_code=受注先コード).
    """
    stored_rc = (item_data.get("小売先コード") or item_data.get("小売先CD") or "").strip()
    stored_dc = (item_data.get("受注先コード") or item_data.get("受注先CD") or "").strip()
    if stored_rc and stored_dc:
        return (stored_rc, stored_dc)
    customer_name = (
        (item_data.get("得意先") or customer_fallback or item_data.get("得意先名")
        or item_data.get("得意先様") or item_data.get("取引先"))
    )
    customer_name = str(customer_name).strip() if customer_name else ""
    customer_code = (item_data.get("得意先コード") or item_data.get("得意先コード") or "").strip() or None
    retail_code, dist_code = resolve_retail_dist(customer_name, customer_code)
    return (retail_code, dist_code)


# 통계 API는 반드시 동적 경로보다 먼저 정의해야 함
def _get_review_stats_sync(db):
    """검토 상태 통계 조회 (동기, run_sync용)."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                pdf_filename, page_number,
                BOOL_AND(COALESCE(first_review_checked, false)) as first_reviewed,
                BOOL_AND(COALESCE(second_review_checked, false)) as second_reviewed,
                COUNT(*) as total_count,
                COUNT(*) FILTER (WHERE first_review_checked = true) as first_checked_count,
                COUNT(*) FILTER (WHERE second_review_checked = true) as second_checked_count
            FROM (
                SELECT pdf_filename, page_number, first_review_checked, second_review_checked FROM items_current
                UNION ALL
                SELECT pdf_filename, page_number, first_review_checked, second_review_checked FROM items_archive
            ) AS all_items
            GROUP BY pdf_filename, page_number
            ORDER BY pdf_filename, page_number
        """)
        rows = cursor.fetchall()
    page_stats = []
    first_reviewed_count = first_not_reviewed_count = second_reviewed_count = second_not_reviewed_count = 0
    for row in rows:
        pdf_filename, page_number, first_reviewed, second_reviewed, total_count, first_checked, second_checked = row
        first_reviewed = bool(first_reviewed) if first_reviewed is not None else False
        second_reviewed = bool(second_reviewed) if second_reviewed is not None else False
        first_review_rate = round((first_checked / total_count) * 100) if total_count > 0 else 0
        second_review_rate = round((second_checked / total_count) * 100) if total_count > 0 else 0
        page_stats.append({
            "pdf_filename": pdf_filename, "page_number": page_number,
            "first_reviewed": first_reviewed, "second_reviewed": second_reviewed,
            "first_review_rate": first_review_rate, "second_review_rate": second_review_rate,
            "total_items": total_count, "first_checked_count": first_checked, "second_checked_count": second_checked
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
        "first_reviewed_count": first_reviewed_count, "first_not_reviewed_count": first_not_reviewed_count,
        "second_reviewed_count": second_reviewed_count, "second_not_reviewed_count": second_not_reviewed_count,
        "total_pages": len(page_stats), "page_stats": page_stats
    }


@router.get("/stats/review")
async def get_review_stats(db=Depends(get_db)):
    """검토 상태 통계 조회 (최적화: 인덱스 활용 및 쿼리 최적화)."""
    try:
        return await db.run_sync(_get_review_stats_sync, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _get_available_year_months_sync(db):
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
        return [{"year": r[0], "month": r[1]} for r in cursor.fetchall()]


@router.get("/stats/available-year-months")
async def get_available_year_months(db=Depends(get_db)):
    """現況フィルタ用。請求年月が設定されている文書の distinct (data_year, data_month) 一覧。"""
    try:
        year_months = await db.run_sync(_get_available_year_months_sync, db)
        return {"year_months": year_months}
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


def _excluded_docs_cte() -> str:
    """검토/현황 집계에서 제외할 문서 CTE: 정답지 + 벡터 DB 학습(병합) 완료 문서."""
    return """
                excluded_docs AS (
                    SELECT pdf_filename FROM documents_current WHERE COALESCE(is_answer_key_document, FALSE) = TRUE
                    UNION
                    SELECT pdf_filename FROM documents_archive WHERE COALESCE(is_answer_key_document, FALSE) = TRUE
                    UNION
                    SELECT pdf_filename FROM rag_learning_status_current WHERE status = 'merged'
                ),"""


def _get_review_stats_by_items_sync(db, ym_clause: str, ym_params: tuple):
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            WITH """ + _excluded_docs_cte().strip() + """
            non_base_docs AS (
                SELECT pdf_filename FROM documents_current
                WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
                """ + ym_clause + """
                UNION
                SELECT pdf_filename FROM documents_archive
                WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
                """ + ym_clause + """
            ),
            detail_items AS (
                SELECT i.pdf_filename, i.first_review_checked, i.second_review_checked
                FROM items_current i
                INNER JOIN page_data_current p ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number AND p.page_role = 'detail'
                INNER JOIN non_base_docs d ON i.pdf_filename = d.pdf_filename
                WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先', i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                  AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先', i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                UNION ALL
                SELECT i.pdf_filename, i.first_review_checked, i.second_review_checked
                FROM items_archive i
                INNER JOIN page_data_archive p ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number AND p.page_role = 'detail'
                INNER JOIN non_base_docs d ON i.pdf_filename = d.pdf_filename
                WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先', i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                  AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先', i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
            )
            SELECT COUNT(*) AS total_item_count, COUNT(DISTINCT pdf_filename) AS total_document_count,
                   COUNT(*) FILTER (WHERE first_review_checked = true) AS first_checked_count,
                   COUNT(*) FILTER (WHERE second_review_checked = true) AS second_checked_count
            FROM detail_items
        """, ym_params)
        row = cursor.fetchone()
    total, total_docs = row[0] or 0, row[1] or 0
    first_checked, second_checked = row[2] or 0, row[3] or 0
    return {"total_item_count": total, "total_document_count": total_docs, "first_checked_count": first_checked,
            "first_not_checked_count": total - first_checked, "second_checked_count": second_checked,
            "second_not_checked_count": total - second_checked}


@router.get("/stats/review-by-items")
async def get_review_stats_by_items(
    year: Optional[int] = Query(None, description="請求年"),
    month: Optional[int] = Query(None, description="請求月"),
    db=Depends(get_db),
):
    """検討状況をアイテム数基準で集計。detail ページ・得意先ありのアイテムのみ対象。"""
    ym_clause, _ = _ym_filter_clause(year, month)
    ym_params = _ym_params_list(year, month, 2)
    try:
        return await db.run_sync(_get_review_stats_by_items_sync, db, ym_clause, ym_params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _get_review_stats_by_user_sync(db, ym_clause: str, ym_params: tuple):
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            WITH """ + _excluded_docs_cte().strip() + """
            non_base_docs AS (
                SELECT pdf_filename FROM documents_current
                WHERE data_year IS NOT NULL AND data_month IS NOT NULL AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
                """ + ym_clause + """
                UNION
                SELECT pdf_filename FROM documents_archive
                WHERE data_year IS NOT NULL AND data_month IS NOT NULL AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
                """ + ym_clause + """
            ),
            detail_items AS (
                SELECT i.first_reviewed_by_user_id, i.second_reviewed_by_user_id
                FROM items_current i
                INNER JOIN page_data_current p ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number AND p.page_role = 'detail'
                INNER JOIN non_base_docs d ON i.pdf_filename = d.pdf_filename
                WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先', i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                  AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先', i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
                UNION ALL
                SELECT i.first_reviewed_by_user_id, i.second_reviewed_by_user_id
                FROM items_archive i
                INNER JOIN page_data_archive p ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number AND p.page_role = 'detail'
                INNER JOIN non_base_docs d ON i.pdf_filename = d.pdf_filename
                WHERE NULLIF(TRIM(COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先', i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '')), '') IS NOT NULL
                  AND COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先', i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') != '—'
            ),
            first_agg AS (SELECT first_reviewed_by_user_id AS user_id, COUNT(*) AS first_checked_count FROM detail_items WHERE first_reviewed_by_user_id IS NOT NULL GROUP BY first_reviewed_by_user_id),
            second_agg AS (SELECT second_reviewed_by_user_id AS user_id, COUNT(*) AS second_checked_count FROM detail_items WHERE second_reviewed_by_user_id IS NOT NULL GROUP BY second_reviewed_by_user_id)
            SELECT u.user_id, COALESCE(u.display_name_ja, u.display_name, u.username) AS display_name,
                   COALESCE(f.first_checked_count, 0) AS first_checked_count, COALESCE(s.second_checked_count, 0) AS second_checked_count
            FROM users u
            LEFT JOIN first_agg f ON u.user_id = f.user_id
            LEFT JOIN second_agg s ON u.user_id = s.user_id
            WHERE f.user_id IS NOT NULL OR s.user_id IS NOT NULL
            ORDER BY (COALESCE(f.first_checked_count, 0) + COALESCE(s.second_checked_count, 0)) DESC
        """, ym_params)
        rows = cursor.fetchall()
    return {"by_user": [{"user_id": r[0], "display_name": r[1] or str(r[0]), "first_checked_count": int(r[2] or 0), "second_checked_count": int(r[3] or 0)} for r in rows]}


@router.get("/stats/review-by-user")
async def get_review_stats_by_user(
    year: Optional[int] = Query(None, description="請求年"),
    month: Optional[int] = Query(None, description="請求月"),
    db=Depends(get_db),
):
    """検討チェックを誰が何件したか。year/month 指定時はその請求年月で絞り込み。"""
    ym_clause, _ = _ym_filter_clause(year, month)
    ym_params = _ym_params_list(year, month, 2)
    try:
        return await db.run_sync(_get_review_stats_by_user_sync, db, ym_clause, ym_params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _get_detail_summary_sync(db, ym_clause: str, ym_params: tuple):
    with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                WITH """ + _excluded_docs_cte().strip() + """
                doc_info AS (
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
                    """ + ym_clause + """
                    UNION ALL
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
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
                WITH """ + _excluded_docs_cte().strip() + """
                doc_info AS (
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
                    """ + ym_clause + """
                    UNION ALL
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
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
                WITH """ + _excluded_docs_cte().strip() + """
                doc_info AS (
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
                    """ + ym_clause + """
                    UNION ALL
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
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
                WITH """ + _excluded_docs_cte().strip() + """
                doc_info AS (
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
                    """ + ym_clause + """
                    UNION ALL
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
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
                WITH """ + _excluded_docs_cte().strip() + """
                doc_info AS (
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_current
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
                    """ + ym_clause + """
                    UNION ALL
                    SELECT pdf_filename, form_type, upload_channel, data_year, data_month
                    FROM documents_archive
                    WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                    AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
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


@router.get("/stats/detail-summary")
async def get_detail_summary(
    year: Optional[int] = Query(None, description="請求年"),
    month: Optional[int] = Query(None, description="請求月"),
    db=Depends(get_db),
):
    """detail ページのみ・得意先ありのアイテム数で集計。year/month 指定時はその請求年月で絞り込み。"""
    ym_clause, _ = _ym_filter_clause(year, month)
    ym_params = _ym_params_list(year, month, 2)
    try:
        return await db.run_sync(_get_detail_summary_sync, db, ym_clause, ym_params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _get_customer_stats_sync(db, ym_clause: str, ym_params: tuple, limit: int):
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            WITH """ + _excluded_docs_cte().strip() + """
            non_base_docs AS (
                SELECT pdf_filename FROM documents_current
                WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
                """ + ym_clause + """
                UNION
                SELECT pdf_filename FROM documents_archive
                WHERE data_year IS NOT NULL AND data_month IS NOT NULL
                AND pdf_filename NOT IN (SELECT pdf_filename FROM excluded_docs)
                """ + ym_clause + """
            ),
            all_items AS (
                SELECT i.pdf_filename, i.page_number,
                       COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先',
                           i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—') AS customer_name
                FROM items_current i
                INNER JOIN page_data_current p ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number AND p.page_role = 'detail'
                INNER JOIN non_base_docs d ON i.pdf_filename = d.pdf_filename
                UNION ALL
                SELECT i.pdf_filename, i.page_number,
                       COALESCE(NULLIF(TRIM(i.customer), ''), i.item_data->>'得意先', i.item_data->>'得意先名', i.item_data->>'得意先様', i.item_data->>'取引先', '—')
                FROM items_archive i
                INNER JOIN page_data_archive p ON i.pdf_filename = p.pdf_filename AND i.page_number = p.page_number AND p.page_role = 'detail'
                INNER JOIN non_base_docs d ON i.pdf_filename = d.pdf_filename
            )
            SELECT customer_name, COUNT(DISTINCT pdf_filename) AS document_count,
                   COUNT(DISTINCT (pdf_filename, page_number)) AS page_count, COUNT(*) AS item_count
            FROM all_items
            WHERE customer_name IS NOT NULL AND TRIM(customer_name) != '' AND customer_name != '—'
            GROUP BY customer_name
            ORDER BY item_count DESC
            LIMIT %s
        """, ym_params + (max(1, min(limit, 500)),))
        rows = cursor.fetchall()
    return {"customers": [{"customer_name": row[0] or "—", "document_count": row[1], "page_count": row[2], "item_count": row[3]} for row in rows]}


@router.get("/stats/by-customer")
async def get_customer_stats(
    limit: int = 100,
    year: Optional[int] = Query(None, description="請求年"),
    month: Optional[int] = Query(None, description="請求月"),
    db=Depends(get_db),
):
    """得意先別集計。year/month 指定時はその請求年月で絞り込み。"""
    ym_clause, _ = _ym_filter_clause(year, month)
    ym_params = _ym_params_list(year, month, 2)
    try:
        return await db.run_sync(_get_customer_stats_sync, db, ym_clause, ym_params, limit)
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
    # 검토 탭 frozen 컬럼: 소매처명→retail_user→소매처코드, dist_retail→판매처코드, 商品名→unit_price→商品コード
    frozen_retail_code: Optional[str] = None   # 소매처코드
    frozen_dist_code: Optional[str] = None     # 판매처코드
    frozen_product_code: Optional[str] = None  # 商品コード(단가리스트 매칭)


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
        items = await db.run_sync(db.get_items, pdf_filename, page_number)
        
        # 검토 탭 컬럼 순서: form_type 있으면 RAG 정답 순서 우선, 없으면 document_metadata.item_data_keys
        item_data_keys: Optional[List[str]] = None
        form_type: Optional[str] = None
        upload_channel: Optional[str] = None
        try:
            doc = await db.run_sync(db.get_document, pdf_filename)
            if doc:
                form_type = doc.get("form_type")
                upload_channel = doc.get("upload_channel")
                if form_type:
                    from modules.core.rag_manager import get_rag_manager
                    rag = get_rag_manager()
                    key_order = rag.get_key_order_by_form_type(form_type)
                    if key_order and key_order.get("item_keys"):
                        item_data_keys = key_order["item_keys"]
                if item_data_keys is None:
                    doc_meta = doc.get("document_metadata") if isinstance(doc.get("document_metadata"), dict) else None
                    if doc_meta and doc_meta.get("item_data_keys"):
                        item_data_keys = doc_meta["item_data_keys"]
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
                    u = await db.run_sync(db.get_user_by_id, uid)
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

            # 商品コード: 저장된 값 우선, 없으면 商品名으로 unit_price 매칭
            frozen_product_code: Optional[str] = None
            if (item_data.get("商品コード") or item_data.get("商品CD")) is not None and str(item_data.get("商品コード") or item_data.get("商品CD") or "").strip():
                frozen_product_code = str((item_data.get("商品コード") or item_data.get("商品CD"))).strip() or None
            elif _UNIT_PRICE_CSV.exists():
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
                            pc = row.get("제품코드")  # unit_price CSV 컬럼명
                            if pc is not None:
                                frozen_product_code = str(pc).strip() or None
                                item_data["商品コード"] = frozen_product_code
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

            # frozen 컬럼: 1→2→3 순서 매핑 (저장된 受注先コード/小売先コード 우선, 없으면 resolve)
            stored_rc = (item_data.get("小売先コード") or item_data.get("小売先CD") or "").strip()
            stored_dc = (item_data.get("受注先コード") or item_data.get("受注先CD") or "").strip()
            frozen_retail_code, frozen_dist_code = _resolved_frozen_codes(item_data, item.get("customer"))
            # 최초 조회 시 비어 있으면 매핑 결과를 DB에 바로 저장 (다음부터는 DB 값 조회)
            if (frozen_retail_code or frozen_dist_code) and (not stored_rc or not stored_dc):
                try:
                    db.update_item_retail_codes(
                        item["item_id"],
                        dist_code=frozen_dist_code,
                        retail_code=frozen_retail_code,
                    )
                except Exception:
                    pass

            item_list.append(
                ItemResponse(
                    item_id=item['item_id'],
                    pdf_filename=item['pdf_filename'],
                    page_number=item['page_number'],
                    item_order=item['item_order'],
                    item_data=item_data,
                    review_status=review_status,
                    version=item.get('version', 1),
                    frozen_retail_code=frozen_retail_code,
                    frozen_dist_code=frozen_dist_code,
                    frozen_product_code=frozen_product_code,
                )
            )
        return {
            "items": item_list,
            "item_data_keys": item_data_keys,
            "form_type": form_type,
            "upload_channel": upload_channel,
        }

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
        # 문서 존재 확인 — 스레드 풀에서 실행
        doc = await db.run_sync(db.get_document, item_data.pdf_filename)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # 페이지 존재 확인 (간단한 확인만)
        try:
            def _count_items():
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT COUNT(*) FROM items_current WHERE pdf_filename = %s AND page_number = %s
                        UNION ALL SELECT COUNT(*) FROM items_archive WHERE pdf_filename = %s AND page_number = %s
                    """, (item_data.pdf_filename, item_data.page_number, item_data.pdf_filename, item_data.page_number))
                    return sum(row[0] for row in cursor.fetchall())
            await db.run_sync(_count_items)
        except Exception:
            pass

        # 1→2→3 매핑 확정값을 item_data에 넣어 DB 저장
        payload_item_data = dict(item_data.item_data or {})
        retail_code, dist_code = resolve_retail_dist(
            payload_item_data.get("得意先"),
            payload_item_data.get("得意先コード"),
        )
        if retail_code:
            payload_item_data["小売先コード"] = retail_code
        if dist_code:
            payload_item_data["受注先コード"] = dist_code

        # 아이템 생성 — 스레드 풀에서 실행
        item_id = await db.run_sync(
            lambda: db.create_item(
                pdf_filename=item_data.pdf_filename,
                page_number=item_data.page_number,
                item_data=payload_item_data,
                customer=None,
                after_item_id=item_data.after_item_id
            )
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
            items = await db.run_sync(db.get_items, item_data.pdf_filename, item_data.page_number)
            created_item = next((item for item in items if item.get('item_id') == item_id), None)
        except Exception:
            import traceback
            traceback.print_exc()
            # get_items 실패 시 직접 DB에서 조회 시도
            try:
                from psycopg2.extras import RealDictCursor
                import json

                def _fetch_created_item():
                    with db.get_connection() as conn:
                        cursor = conn.cursor(cursor_factory=RealDictCursor)
                        cursor.execute("""
                            SELECT item_id, pdf_filename, page_number, item_order, customer,
                                   first_review_checked, second_review_checked, item_data, version
                            FROM items_current WHERE item_id = %s
                            UNION ALL
                            SELECT item_id, pdf_filename, page_number, item_order, customer,
                                   first_review_checked, second_review_checked, item_data, version
                            FROM items_archive WHERE item_id = %s LIMIT 1
                        """, (item_id, item_id))
                        row = cursor.fetchone()
                    if not row:
                        raise HTTPException(status_code=500, detail="Failed to retrieve created item: item not found in database")
                    created_item = dict(row)
                    if isinstance(created_item.get('item_data'), str):
                        created_item['item_data'] = json.loads(created_item['item_data'])
                    elif not isinstance(created_item.get('item_data'), dict):
                        created_item['item_data'] = {}
                    created_item['review_status'] = {
                        'first_review': {'checked': created_item.get('first_review_checked', False), 'reviewed_at': None},
                        'second_review': {'checked': created_item.get('second_review_checked', False), 'reviewed_at': None}
                    }
                    return created_item
                created_item = await db.run_sync(_fetch_created_item)
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


def _update_item_sync(db, item_id, update_data, current_user_id, user_info):
    """
    아이템 업데이트 DB 작업 (run_sync용 동기 함수).
    반환: (True, pdf_filename, page_number, review_status) 성공 시,
          (False, status_code, detail) 실패 시.
    """
    import json as _json_mod
    expected_version = update_data.expected_version
    session_id = update_data.session_id
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT item_id, pdf_filename, page_number, version
            FROM items_current WHERE item_id = %s
            UNION ALL
            SELECT item_id, pdf_filename, page_number, version
            FROM items_archive WHERE item_id = %s
            LIMIT 1
        """, (item_id, item_id))
        item = cursor.fetchone()
        if not item:
            return (False, 404, "Item not found")
        if item[3] != expected_version:
            return (False, 409, "Version conflict. Another user has modified this item.")
        items_with_locks = db.get_items_with_lock_status(
            pdf_filename=item[1], page_number=item[2], current_session_id=session_id
        )
        item_lock_info = next((i for i in items_with_locks if i.get("item_id") == item_id), None)
        if item_lock_info and item_lock_info.get("is_locked_by_others"):
            uid = item_lock_info.get("locked_by_user_id")
            if uid is not None:
                return (False, 409, f"Item is locked by another user: user_id={uid}")
        pdf_filename = item[1]
        doc = db.get_document(pdf_filename)
        form_type = doc.get("form_type") if doc else None
        payload_item_data = dict(update_data.item_data or {})
        retail_code, dist_code = resolve_retail_dist(
            payload_item_data.get("得意先"), payload_item_data.get("得意先コード"),
        )
        if retail_code:
            payload_item_data["小売先コード"] = retail_code
        if dist_code:
            payload_item_data["受注先コード"] = dist_code
        separated = db._separate_item_fields(payload_item_data, form_type=form_type)
        set_clauses, params = [], []
        if update_data.review_status:
            fr = update_data.review_status.get("first_review") or {}
            sr = update_data.review_status.get("second_review") or {}
            if "checked" in fr:
                cv = fr["checked"]
                set_clauses.append("first_review_checked = %s")
                params.append(bool(cv))
                set_clauses.append("first_reviewed_at = %s")
                params.append(datetime.now(timezone.utc) if cv else None)
                set_clauses.append("first_reviewed_by_user_id = %s")
                params.append(current_user_id if cv else None)
            if "checked" in sr:
                cv = sr["checked"]
                set_clauses.append("second_review_checked = %s")
                params.append(bool(cv))
                set_clauses.append("second_reviewed_at = %s")
                params.append(datetime.now(timezone.utc) if cv else None)
                set_clauses.append("second_reviewed_by_user_id = %s")
                params.append(current_user_id if cv else None)
        if "item_data" in separated:
            set_clauses.append("item_data = %s::jsonb")
            params.append(_json_mod.dumps(separated["item_data"], ensure_ascii=False))
        set_clauses.append("version = version + 1")
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        params.append(item_id)
        params.append(expected_version)
        if not set_clauses:
            return (False, 400, "No fields to update")
        cursor.execute("""
            SELECT 'current' FROM items_current WHERE item_id = %s
            UNION ALL SELECT 'archive' FROM items_archive WHERE item_id = %s LIMIT 1
        """, (item_id, item_id))
        row = cursor.fetchone()
        table_suffix = row[0] if row else "current"
        items_table = f"items_{table_suffix}"
        cursor.execute(
            f"UPDATE {items_table} SET {', '.join(set_clauses)} WHERE item_id = %s AND version = %s",
            params,
        )
        if cursor.rowcount == 0:
            return (False, 409, "Version conflict or item not found")
        try:
            doc_meta = doc.get("document_metadata") if isinstance(doc.get("document_metadata"), dict) else {}
            current_keys = list(doc_meta.get("item_data_keys") or [])
            new_keys = list(separated.get("item_data", {}).keys())
            merged = list(dict.fromkeys([*current_keys, *new_keys]))
            if merged:
                meta_json = _json_mod.dumps({**doc_meta, "item_data_keys": merged}, ensure_ascii=False)
                cursor.execute(
                    "UPDATE documents_current SET document_metadata = %s::jsonb WHERE pdf_filename = %s",
                    (meta_json, pdf_filename),
                )
        except Exception:
            pass
        try:
            db.release_item_lock(item_id, session_id)
        except Exception:
            pass
        conn.commit()
    if update_data.review_status:
        fr = update_data.review_status.get("first_review") or {}
        sr = update_data.review_status.get("second_review") or {}
        if "checked" in fr:
            action = "1차 검토 체크" if fr["checked"] else "1차 검토 해제"
            activity_log(user_info.get("username") if user_info else None, f"{action}: {pdf_filename} p.{item[2]}")
        if "checked" in sr:
            action = "2차 검토 체크" if sr["checked"] else "2차 검토 해제"
            activity_log(user_info.get("username") if user_info else None, f"{action}: {pdf_filename} p.{item[2]}")
    return (True, pdf_filename, item[2], update_data.review_status if update_data.review_status else None)


@router.put("/{item_id}")
async def update_item(
    item_id: int,
    update_data: ItemUpdateRequest,
    db=Depends(get_db)
):
    """
    아이템 업데이트 (낙관적 락 적용). DB 작업은 스레드 풀에서 실행해 이벤트 루프 블로킹 방지.
    """
    try:
        user_info = await db.run_sync(db.get_session_user, update_data.session_id)
        current_user_id = user_info.get("user_id") if user_info else None
        result = await db.run_sync(
            _update_item_sync, db, item_id, update_data, current_user_id, user_info
        )
        if not result[0]:
            raise HTTPException(status_code=result[1], detail=result[2])
        _success, pdf_filename, page_number, review_status = result
        if review_status:
            try:
                await manager.broadcast_lock_update(
                    pdf_filename=pdf_filename,
                    page_number=page_number,
                    message={
                        "type": "review_status_updated",
                        "item_id": item_id,
                        "review_status": review_status,
                    },
                )
            except Exception:
                pass
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
        
        # 아이템 존재 확인 및 정보 조회 (브로드캐스트용) — 스레드 풀에서 실행
        def _fetch_item_info():
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT pdf_filename, page_number FROM items_current WHERE item_id = %s
                    UNION ALL SELECT pdf_filename, page_number FROM items_archive WHERE item_id = %s LIMIT 1
                """, (item_id, item_id))
                return cursor.fetchone()
        item_info = await db.run_sync(_fetch_item_info)
        if not item_info:
            raise HTTPException(status_code=404, detail=f"Item not found: item_id={item_id}")
        
        # 락 획득 시도 (만료된 락 강제 정리 포함) — 스레드 풀에서 실행
        success, reason = await db.run_sync(
            lambda: db.acquire_item_lock(item_id=item_id, session_id=session_id, lock_duration_minutes=5, force_cleanup=True)
        )
        
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
                    items_with_locks = await db.run_sync(
                        db.get_items_with_lock_status,
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
                            # 만료된 락 강제 정리 후 재시도 (스레드 풀에서 실행)
                            try:
                                def _clear_and_retry():
                                    with db.get_connection() as conn:
                                        cursor = conn.cursor()
                                        cursor.execute("DELETE FROM item_locks_current WHERE item_id = %s", (item_id,))
                                        cursor.execute("DELETE FROM item_locks_archive WHERE item_id = %s", (item_id,))
                                        conn.commit()
                                    return db.acquire_item_lock(item_id=item_id, session_id=session_id, lock_duration_minutes=5, force_cleanup=True)
                                retry_success, retry_reason = await db.run_sync(_clear_and_retry)
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
        
        # 아이템 존재 여부 및 정보 조회 (WebSocket 브로드캐스트용) — 스레드 풀에서 실행
        def _fetch_item_info_for_delete():
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT item_id, pdf_filename, page_number, item_order FROM items_current WHERE item_id = %s
                    UNION ALL SELECT item_id, pdf_filename, page_number, item_order FROM items_archive WHERE item_id = %s LIMIT 1
                """, (item_id, item_id))
                return cursor.fetchone()
        try:
            item_info = await db.run_sync(_fetch_item_info_for_delete)
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

        # 아이템 삭제 — 스레드 풀에서 실행
        print(f"🔵 [delete_item] db.delete_item 호출: item_id={item_id}")
        success = await db.run_sync(db.delete_item, item_id)
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
        def _release_lock_and_fetch_info():
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT pdf_filename, page_number FROM items_current WHERE item_id = %s
                    UNION ALL SELECT pdf_filename, page_number FROM items_archive WHERE item_id = %s LIMIT 1
                """, (item_id, item_id))
                item_info = cursor.fetchone()
            success = db.release_item_lock(item_id=item_id, session_id=session_id)
            return success, item_info
        success, item_info = await db.run_sync(_release_lock_and_fetch_info)
        
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
        # session_id를 user_id로 변환 — 스레드 풀에서 실행
        user_info = await db.run_sync(db.get_session_user, session_id)
        if not user_info:
            return {"message": "Session not found", "released_count": 0}
        
        user_id = user_info['user_id']
        
        # 해제할 락 정보 조회 + 모든 락 해제 — 스레드 풀에서 실행
        def _fetch_locks_and_release():
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT i.pdf_filename, i.page_number, l.item_id
                    FROM item_locks_current l INNER JOIN items_current i ON l.item_id = i.item_id WHERE l.locked_by_user_id = %s
                    UNION ALL
                    SELECT DISTINCT i.pdf_filename, i.page_number, l.item_id
                    FROM item_locks_archive l INNER JOIN items_archive i ON l.item_id = i.item_id WHERE l.locked_by_user_id = %s
                """, (user_id, user_id))
                locks_info = cursor.fetchall()
            released_count = db.release_all_locks_by_session(session_id=session_id)
            return locks_info, released_count
        locks_info, released_count = await db.run_sync(_fetch_locks_and_release)
        
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
