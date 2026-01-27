"""
성능 진단 API
"""
import time
from typing import Dict, Any
from fastapi import APIRouter, Depends
from database.registry import get_db

router = APIRouter()


@router.get("/diagnose")
async def diagnose_performance(db=Depends(get_db)) -> Dict[str, Any]:
    """
    성능 진단: 주요 쿼리 실행 시간 측정
    
    Returns:
        각 쿼리의 실행 시간 (밀리초)
    """
    results = {}
    
    # 1. 문서 목록 조회 시간
    start = time.time()
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pdf_filename, total_pages, form_type, created_at
                FROM documents
                ORDER BY created_at DESC
            """)
            rows = cursor.fetchall()
        results["documents_list"] = {
            "time_ms": (time.time() - start) * 1000,
            "count": len(rows),
            "status": "success"
        }
    except Exception as e:
        results["documents_list"] = {
            "time_ms": (time.time() - start) * 1000,
            "error": str(e),
            "status": "error"
        }
    
    # 2. 검토 통계 조회 시간
    start = time.time()
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    pdf_filename,
                    page_number,
                    BOOL_AND(COALESCE(first_review_checked, false)) as first_reviewed,
                    BOOL_AND(COALESCE(second_review_checked, false)) as second_reviewed,
                    COUNT(*) as total_count
                FROM items
                GROUP BY pdf_filename, page_number
            """)
            rows = cursor.fetchall()
        results["review_stats"] = {
            "time_ms": (time.time() - start) * 1000,
            "count": len(rows),
            "status": "success"
        }
    except Exception as e:
        results["review_stats"] = {
            "time_ms": (time.time() - start) * 1000,
            "error": str(e),
            "status": "error"
        }
    
    # 3. 페이지 데이터 조회 시간 (샘플)
    start = time.time()
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pdf_filename, page_number
                FROM page_data
                LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                pdf_filename, page_number = row
                page_result = db.get_page_result(pdf_filename, page_number)
                results["page_result"] = {
                    "time_ms": (time.time() - start) * 1000,
                    "items_count": len(page_result.get('items', [])) if page_result else 0,
                    "status": "success"
                }
            else:
                results["page_result"] = {
                    "time_ms": (time.time() - start) * 1000,
                    "status": "no_data"
                }
    except Exception as e:
        results["page_result"] = {
            "time_ms": (time.time() - start) * 1000,
            "error": str(e),
            "status": "error"
        }
    
    # 4. items 조회 시간 (샘플)
    start = time.time()
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT pdf_filename, page_number
                FROM items
                LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                pdf_filename, page_number = row
                items = db.get_items(pdf_filename, page_number)
                results["get_items"] = {
                    "time_ms": (time.time() - start) * 1000,
                    "items_count": len(items),
                    "status": "success"
                }
            else:
                results["get_items"] = {
                    "time_ms": (time.time() - start) * 1000,
                    "status": "no_data"
                }
    except Exception as e:
        results["get_items"] = {
            "time_ms": (time.time() - start) * 1000,
            "error": str(e),
            "status": "error"
        }
    
    # 5. 인덱스 사용 여부 확인 (PostgreSQL 버전 호환성 개선)
    start = time.time()
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # PostgreSQL 버전에 따라 컬럼명이 다를 수 있으므로 별칭 사용
            cursor.execute("""
                SELECT 
                    schemaname,
                    relname as tablename,
                    indexrelname as indexname,
                    idx_scan as index_scans,
                    idx_tup_read as tuples_read,
                    idx_tup_fetch as tuples_fetched
                FROM pg_stat_user_indexes
                WHERE relname IN ('documents', 'items', 'page_data')
                ORDER BY relname, indexrelname
            """)
            indexes = cursor.fetchall()
            results["indexes"] = {
                "time_ms": (time.time() - start) * 1000,
                "count": len(indexes),
                "details": [
                    {
                        "table": row[1],
                        "index": row[2],
                        "scans": row[3],
                        "tuples_read": row[4],
                        "tuples_fetched": row[5]
                    }
                    for row in indexes
                ],
                "status": "success"
            }
    except Exception as e:
        results["indexes"] = {
            "time_ms": (time.time() - start) * 1000,
            "error": str(e),
            "status": "error"
        }
    
    # 6. 테이블 크기 확인 (PostgreSQL 버전 호환성 개선)
    start = time.time()
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            # PostgreSQL 버전에 따라 컬럼명이 다를 수 있으므로 별칭 사용
            cursor.execute("""
                SELECT 
                    schemaname,
                    relname as tablename,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||relname)) AS size,
                    pg_total_relation_size(schemaname||'.'||relname) AS size_bytes,
                    n_live_tup as row_count
                FROM pg_stat_user_tables
                WHERE relname IN ('documents', 'items', 'page_data', 'item_locks')
                ORDER BY pg_total_relation_size(schemaname||'.'||relname) DESC
            """)
            tables = cursor.fetchall()
            results["table_sizes"] = {
                "time_ms": (time.time() - start) * 1000,
                "tables": [
                    {
                        "table": row[1],
                        "size": row[2],
                        "size_bytes": row[3],
                        "row_count": row[4]
                    }
                    for row in tables
                ],
                "status": "success"
            }
    except Exception as e:
        results["table_sizes"] = {
            "time_ms": (time.time() - start) * 1000,
            "error": str(e),
            "status": "error"
        }
    
    return results
