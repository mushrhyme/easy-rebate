"""
성능 진단 API
"""
import time
from typing import Dict, Any
from fastapi import APIRouter, Depends
from database.registry import get_db

router = APIRouter()


def _diagnose_performance_sync(db) -> Dict[str, Any]:
    """성능 진단 전체를 동기로 수행 (run_sync용)."""
    results: Dict[str, Any] = {}
    # 1. 문서 목록 조회
    start = time.time()
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pdf_filename, total_pages, form_type, created_at FROM documents ORDER BY created_at DESC")
            rows = cursor.fetchall()
        results["documents_list"] = {"time_ms": (time.time() - start) * 1000, "count": len(rows), "status": "success"}
    except Exception as e:
        results["documents_list"] = {"time_ms": (time.time() - start) * 1000, "error": str(e), "status": "error"}
    # 2. 검토 통계
    start = time.time()
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pdf_filename, page_number, BOOL_AND(COALESCE(first_review_checked, false)), BOOL_AND(COALESCE(second_review_checked, false)), COUNT(*)
                FROM items GROUP BY pdf_filename, page_number
            """)
            rows = cursor.fetchall()
        results["review_stats"] = {"time_ms": (time.time() - start) * 1000, "count": len(rows), "status": "success"}
    except Exception as e:
        results["review_stats"] = {"time_ms": (time.time() - start) * 1000, "error": str(e), "status": "error"}
    # 3. 페이지 데이터 샘플
    start = time.time()
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pdf_filename, page_number FROM page_data LIMIT 1")
            row = cursor.fetchone()
        if row:
            pdf_filename, page_number = row
            page_result = db.get_page_result(pdf_filename, page_number)
            results["page_result"] = {"time_ms": (time.time() - start) * 1000, "items_count": len(page_result.get('items', [])) if page_result else 0, "status": "success"}
        else:
            results["page_result"] = {"time_ms": (time.time() - start) * 1000, "status": "no_data"}
    except Exception as e:
        results["page_result"] = {"time_ms": (time.time() - start) * 1000, "error": str(e), "status": "error"}
    # 4. get_items 샘플
    start = time.time()
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pdf_filename, page_number FROM items LIMIT 1")
            row = cursor.fetchone()
        if row:
            items = db.get_items(row[0], row[1])
            results["get_items"] = {"time_ms": (time.time() - start) * 1000, "items_count": len(items), "status": "success"}
        else:
            results["get_items"] = {"time_ms": (time.time() - start) * 1000, "status": "no_data"}
    except Exception as e:
        results["get_items"] = {"time_ms": (time.time() - start) * 1000, "error": str(e), "status": "error"}
    # 5. 인덱스
    start = time.time()
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT schemaname, relname, indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
                FROM pg_stat_user_indexes WHERE relname IN ('documents', 'items', 'page_data') ORDER BY relname, indexrelname
            """)
            indexes = cursor.fetchall()
        results["indexes"] = {"time_ms": (time.time() - start) * 1000, "count": len(indexes), "details": [{"table": r[1], "index": r[2], "scans": r[3], "tuples_read": r[4], "tuples_fetched": r[5]} for r in indexes], "status": "success"}
    except Exception as e:
        results["indexes"] = {"time_ms": (time.time() - start) * 1000, "error": str(e), "status": "error"}
    # 6. 테이블 크기
    start = time.time()
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT schemaname, relname, pg_size_pretty(pg_total_relation_size(schemaname||'.'||relname)), pg_total_relation_size(schemaname||'.'||relname), n_live_tup
                FROM pg_stat_user_tables WHERE relname IN ('documents', 'items', 'page_data', 'item_locks') ORDER BY pg_total_relation_size(schemaname||'.'||relname) DESC
            """)
            tables = cursor.fetchall()
        results["table_sizes"] = {"time_ms": (time.time() - start) * 1000, "tables": [{"table": r[1], "size": r[2], "size_bytes": r[3], "row_count": r[4]} for r in tables], "status": "success"}
    except Exception as e:
        results["table_sizes"] = {"time_ms": (time.time() - start) * 1000, "error": str(e), "status": "error"}
    return results


@router.get("/diagnose")
async def diagnose_performance(db=Depends(get_db)) -> Dict[str, Any]:
    """성능 진단: 주요 쿼리 실행 시간 측정 (DB 작업은 스레드 풀에서 실행)."""
    return await db.run_sync(_diagnose_performance_sync, db)
