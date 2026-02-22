"""
PostgreSQL 데이터베이스 관리 모듈

JSON 파싱 결과를 PostgreSQL에 저장하고 조회하는 기능을 제공합니다.
스키마: documents + items (JSONB)
"""

import psycopg2
import time
from psycopg2.extras import execute_values, RealDictCursor, Json
from psycopg2.pool import SimpleConnectionPool
from typing import Dict, Any, List, Optional
import json
from contextlib import contextmanager
from pathlib import Path
from database.table_selector import get_table_name, get_table_suffix
from modules.utils.config import get_project_root
from database.db_items import ItemsMixin
from database.db_locks import LocksMixin
from database.db_users import UsersMixin

class DatabaseManager(ItemsMixin, LocksMixin, UsersMixin):
    """PostgreSQL 데이터베이스 관리 클래스 (새 스키마: documents + items JSONB)"""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "rebate_db",
        user: str = "postgres",
        password: str = "",
        min_conn: int = 1,
        max_conn: int = 10
    ):
        """
        데이터베이스 연결 풀 초기화
        
        Args:
            host: 데이터베이스 호스트
            port: 데이터베이스 포트
            database: 데이터베이스 이름
            user: 사용자 이름
            password: 비밀번호
            min_conn: 최소 연결 수
            max_conn: 최대 연결 수
        """
        self.db_config = {
            'host': host,
            'port': port,
            'database': database,
            'user': user,
            'password': password
        }
        self.pool = SimpleConnectionPool(
            min_conn, max_conn, **self.db_config
        )
    
    def close(self):
        """
        데이터베이스 연결 풀 닫기
        
        애플리케이션 종료 시 호출하여 모든 연결을 정리합니다.
        """
        if self.pool:
            self.pool.closeall()
            self.pool = None
    
    @contextmanager
    def get_connection(self):
        """데이터베이스 연결 컨텍스트 매니저"""
        conn = self.pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.pool.putconn(conn)
    
    # ============================================
    # 문서 관리 메서드
    # ============================================
    
    def get_document(self, pdf_filename: str, year: Optional[int] = None, month: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        문서 정보 조회 (current/archive 테이블 사용)
        
        Args:
            pdf_filename: PDF 파일명
            year: 연도 (선택사항, 없으면 current와 archive 모두에서 찾기)
            month: 월 (선택사항)
            
        Returns:
            문서 정보 딕셔너리 또는 None
        """
        query_start = time.perf_counter()  # 쿼리 시간 측정 시작
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                if year is not None and month is not None:
                    # 특정 연월 조회
                    table_name = get_table_name('documents', year, month)
                    cursor.execute(f"""
                        SELECT *
                        FROM {table_name}
                        WHERE pdf_filename = %s
                    """, (pdf_filename,))
                else:
                    # current에서 먼저 찾고, 없으면 archive에서 찾기
                    cursor.execute("""
                        SELECT * FROM documents_current
                        WHERE pdf_filename = %s
                        UNION ALL
                        SELECT * FROM documents_archive
                        WHERE pdf_filename = %s
                        LIMIT 1
                    """, (pdf_filename, pdf_filename))
                
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            return None
    
    def has_document(self, pdf_filename: str, year: Optional[int] = None, month: Optional[int] = None) -> bool:
        """
        문서 존재 여부 확인 (current/archive 테이블 사용)
        
        Args:
            pdf_filename: PDF 파일명
            year: 연도 (선택사항)
            month: 월 (선택사항)
            
        Returns:
            존재 여부
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                if year is not None and month is not None:
                    table_name = get_table_name('documents', year, month)
                    cursor.execute(f"""
                        SELECT COUNT(*) FROM {table_name} WHERE pdf_filename = %s
                    """, (pdf_filename,))
                else:
                    cursor.execute("""
                        SELECT COUNT(*) FROM documents_current WHERE pdf_filename = %s
                        UNION ALL
                        SELECT COUNT(*) FROM documents_archive WHERE pdf_filename = %s
                    """, (pdf_filename, pdf_filename))
                    # UNION ALL 결과 합산
                    result = sum(row[0] for row in cursor.fetchall())
                    return result > 0
                
                return cursor.fetchone()[0] > 0
        except Exception:
            return False
    
    def check_document_exists(self, pdf_filename: str, year: Optional[int] = None, month: Optional[int] = None) -> Dict[str, Any]:
        """
        문서 존재 여부 확인 (current/archive 테이블 사용)
        
        Args:
            pdf_filename: PDF 파일명
            year: 연도 (선택사항)
            month: 월 (선택사항)
            
        Returns:
            {
                'exists': 존재 여부,
                'total_pages': 총 페이지 수 (존재하는 경우),
                'form_type': 양식지 번호 (존재하는 경우)
            }
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                if year is not None and month is not None:
                    table_name = get_table_name('documents', year, month)
                    cursor.execute(f"""
                        SELECT total_pages, form_type
                        FROM {table_name}
                        WHERE pdf_filename = %s
                    """, (pdf_filename,))
                else:
                    # current에서 먼저 찾고, 없으면 archive에서 찾기
                    cursor.execute("""
                        SELECT total_pages, form_type FROM documents_current WHERE pdf_filename = %s
                        UNION ALL
                        SELECT total_pages, form_type FROM documents_archive WHERE pdf_filename = %s
                        LIMIT 1
                    """, (pdf_filename, pdf_filename))
                
                row = cursor.fetchone()
                if row:
                    result = {
                        'exists': True,
                        'total_pages': row.get('total_pages', 0) if isinstance(row, dict) else row[0],
                        'form_type': row.get('form_type') if isinstance(row, dict) else row[1]
                    }
                else:
                    result = {
                        'exists': False,
                        'total_pages': 0,
                        'form_type': None
                    }
                return result
        except Exception:
            return {
                'exists': False,
                'total_pages': 0,
                'form_type': None
            }
    
    # ============================================
    # JSONB 검색 메서드
    # ============================================
    
    def search_items_by_customer(
        self,
        customer_name: str,
        pdf_filename: Optional[str] = None,
        exact_match: bool = False,
        form_type: Optional[str] = None,
        super_names: Optional[List[str]] = None,
        min_similarity: float = 0.9
    ) -> List[Dict[str, Any]]:
        """
        거래처명으로 항목 검색 (items 테이블에서 직접 조회)
        
        Args:
            customer_name: 거래처명 (부분 일치 검색 가능)
            pdf_filename: PDF 파일명 (None이면 전체 DB에서 검색)
            exact_match: True면 정확히 일치, False면 부분 일치 (ILIKE 검색)
            form_type: 양식지 번호 (01, 02, 03, 04, 05). None이면 모든 양식지
            super_names: 로그인 사용자 담당 슈퍼명 목록. 있으면 유사도(min_similarity) 이상만 반환
            min_similarity: 슈퍼명 유사도 최소 기준 (0~1, 기본 0.9)
            
        Returns:
            검색된 항목 리스트 (공통 필드 + item_data 병합)
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                # 검색 값 준비 (거래처는 得意先로 통일, 양식 무관)
                search_value = customer_name if exact_match else f'%{customer_name}%'
                operator = "=" if exact_match else "ILIKE"
                cust_expr = self._item_customer_expr()
                # 得意先 필드로 매칭되거나, item_data 전체 텍스트에 검색어가 있으면 히트 (키 이름/저장 방식 차이 대비)
                condition = (
                    f"((({cust_expr}) <> '' AND ({cust_expr}) {operator} %s) "
                    f"OR (i.item_data IS NOT NULL AND i.item_data::text {operator} %s))"
                )
                params: List[Any] = [search_value, search_value]
                
                # pdf_filename / form_type 필터
                conditions = [condition]
                if pdf_filename:
                    conditions.append("i.pdf_filename = %s")
                    params.append(pdf_filename)
                if form_type:
                    conditions.append("d.form_type = %s")
                    params.append(form_type)
                # 내 담당만: 슈퍼명 유사도 90% 이상 (pg_trgm). detail 得意先와 동일한 값으로 비교
                if super_names and len(super_names) > 0:
                    cust_expr = self._item_customer_expr()
                    conditions.append(
                        f"({cust_expr}) <> '' "
                        f"AND EXISTS (SELECT 1 FROM unnest(%s::text[]) AS sn WHERE similarity({cust_expr}, sn) >= %s))"
                    )
                    params.extend([super_names, min_similarity])
                where_clause = " AND ".join(conditions)
                
                # SQL 쿼리 구성 (items_current와 items_archive 모두 조회)
                # WHERE 절이 두 번 들어가므로 placeholder가 2배 → params도 2배로 전달
                execute_params = params * 2
                if form_type or pdf_filename:
                    sql = """
                        SELECT 
                            i.item_id,
                            i.pdf_filename,
                            i.page_number,
                            i.item_order,
                            i.first_review_checked,
                            i.second_review_checked,
                            i.first_reviewed_at,
                            i.second_reviewed_at,
                            i.first_reviewed_by_user_id,
                            i.second_reviewed_by_user_id,
                            i.item_data,
                            i.version,
                            d.form_type
                        FROM items_current i
                        INNER JOIN documents_current d ON i.pdf_filename = d.pdf_filename
                        WHERE """ + where_clause + """
                        UNION ALL
                        SELECT 
                            i.item_id,
                            i.pdf_filename,
                            i.page_number,
                            i.item_order,
                            i.first_review_checked,
                            i.second_review_checked,
                            i.first_reviewed_at,
                            i.second_reviewed_at,
                            i.first_reviewed_by_user_id,
                            i.second_reviewed_by_user_id,
                            i.item_data,
                            i.version,
                            d.form_type
                        FROM items_archive i
                        INNER JOIN documents_archive d ON i.pdf_filename = d.pdf_filename
                        WHERE """ + where_clause + """
                        ORDER BY pdf_filename, page_number, item_order
                    """
                else:
                    sql = """
                        SELECT 
                            i.item_id,
                            i.pdf_filename,
                            i.page_number,
                            i.item_order,
                            i.first_review_checked,
                            i.second_review_checked,
                            i.first_reviewed_at,
                            i.second_reviewed_at,
                            i.first_reviewed_by_user_id,
                            i.second_reviewed_by_user_id,
                            i.item_data,
                            i.version,
                            d.form_type
                        FROM items_current i
                        LEFT JOIN documents_current d ON i.pdf_filename = d.pdf_filename
                        WHERE """ + where_clause + """
                        UNION ALL
                        SELECT 
                            i.item_id,
                            i.pdf_filename,
                            i.page_number,
                            i.item_order,
                            i.first_review_checked,
                            i.second_review_checked,
                            i.first_reviewed_at,
                            i.second_reviewed_at,
                            i.first_reviewed_by_user_id,
                            i.second_reviewed_by_user_id,
                            i.item_data,
                            i.version,
                            d.form_type
                        FROM items_archive i
                        LEFT JOIN documents_archive d ON i.pdf_filename = d.pdf_filename
                        WHERE """ + where_clause + """
                        ORDER BY pdf_filename, page_number, item_order
                    """
                
                cursor.execute(sql, execute_params)
                fetched_rows = cursor.fetchall()
                
                # 키 순서 조회 (form_type별)
                item_key_order = None
                result_form_type = form_type
                if not result_form_type and fetched_rows:
                    first_row = dict(fetched_rows[0])
                    if 'form_type' in first_row and first_row['form_type']:
                        result_form_type = first_row['form_type']
                
                if result_form_type:
                    try:
                        from modules.core.rag_manager import get_rag_manager
                        rag_manager = get_rag_manager()
                        key_order = rag_manager.get_key_order_by_form_type(result_form_type)
                        if key_order:
                            item_key_order = key_order.get("item_keys")
                    except Exception:
                        pass
                
                results = []
                for row in fetched_rows:
                    row_dict = dict(row)
                    
                    # item_data 파싱
                    item_data = row_dict.get('item_data', {})
                    if isinstance(item_data, str):
                        item_data = json.loads(item_data)
                    elif not isinstance(item_data, dict):
                        try:
                            item_data = json.loads(str(item_data)) if item_data else {}
                        except Exception:
                            item_data = {}
                    
                    # 공통 필드와 item_data 병합
                    merged_item = {
                        **item_data,  # 양식지별 필드
                        'pdf_filename': row_dict['pdf_filename'],
                        'page_number': row_dict['page_number'],
                        'item_order': row_dict['item_order'],
                        'item_id': row_dict['item_id'],
                        'version': row_dict['version'],
                    }
                    
                    # 공통 필드: item_data의 표준 키(得意先)를 사용한다.
                    customer_value = item_data.get('得意先')
                    if customer_value is not None:
                        merged_item['得意先'] = customer_value
                    # 상품명: item_data 내 商品名만 사용 (DB 컬럼 product_name 제거됨)
                    if item_data.get('商品名') is not None:
                        merged_item['商品名'] = item_data['商品名']
                    
                    # 검토 상태 추가 (증빙용: 누가/언제)
                    merged_item['review_status'] = {
                        'first_review': {
                            'checked': row_dict.get('first_review_checked', False),
                            'reviewed_at': row_dict.get('first_reviewed_at'),
                            'reviewed_by_user_id': row_dict.get('first_reviewed_by_user_id'),
                        },
                        'second_review': {
                            'checked': row_dict.get('second_review_checked', False),
                            'reviewed_at': row_dict.get('second_reviewed_at'),
                            'reviewed_by_user_id': row_dict.get('second_reviewed_by_user_id'),
                        },
                    }
                    
                    # 키 순서 정렬
                    if item_key_order:
                        try:
                            reordered_item = {}
                            for item_key in item_key_order:
                                if item_key in merged_item:
                                    reordered_item[item_key] = merged_item[item_key]
                            for item_key in merged_item.keys():
                                if item_key not in item_key_order:
                                    reordered_item[item_key] = merged_item[item_key]
                            merged_item = reordered_item
                        except Exception:
                            pass
                    
                    if 'form_type' in row_dict:
                        merged_item['form_type'] = row_dict['form_type']
                    results.append(merged_item)
                
                return results
        except Exception:
            return []

    def search_pages_by_customer_in_page_meta(
        self,
        customer_name: str
    ) -> List[Dict[str, Any]]:
        """
        page_data의 page_meta(JSON) 텍스트에서 거래처명 부분 일치 검색.
        items 검색 결과가 0일 때 폴백으로 사용 (page_meta에 거래처가 포함된 페이지 찾기).
        """
        if not customer_name or not customer_name.strip():
            return []
        search_pattern = f"%{customer_name.strip()}%"
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("""
                    SELECT p.pdf_filename, p.page_number, d.form_type
                    FROM page_data_current p
                    LEFT JOIN documents_current d ON p.pdf_filename = d.pdf_filename
                    WHERE p.page_meta::text ILIKE %s
                    UNION
                    SELECT p.pdf_filename, p.page_number, d.form_type
                    FROM page_data_archive p
                    LEFT JOIN documents_archive d ON p.pdf_filename = d.pdf_filename
                    WHERE p.page_meta::text ILIKE %s
                    ORDER BY pdf_filename, page_number
                """, (search_pattern, search_pattern))
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def get_page_keys_by_super_names(
        self,
        super_names: List[str],
        form_type: Optional[str] = None,
        min_similarity: float = 0.9,
    ) -> List[Dict[str, Any]]:
        """
        담당 슈퍼명 목록과 유사도 이상인 거래처가 있는 페이지 목록 반환.
        super_import.csv 기반 목록을 인자로 받음 (DB 테이블 미사용).

        Args:
            super_names: 슈퍼명 목록 (CSV에서 username별로 조회한 값)
            form_type: 양식지 번호. None이면 전체
            min_similarity: 슈퍼명 유사도 최소 기준 (0~1)

        Returns:
            [{ pdf_filename, page_number, form_type }, ...]
        """
        names_trimmed = [n.strip() for n in super_names if n and n.strip()]
        if not names_trimmed:
            return []
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cust_expr = self._item_customer_expr()
                base_cond = (
                    f"({cust_expr}) <> '' "
                    f"AND EXISTS (SELECT 1 FROM unnest(%s::text[]) AS sn "
                    f"WHERE similarity({cust_expr}, sn) >= %s)"
                )
                conditions = [base_cond]
                params: List[Any] = [names_trimmed, min_similarity]
                if form_type:
                    conditions.append("d.form_type = %s")
                    params.append(form_type)
                where_clause = " AND ".join(conditions)
                sql = """
                    SELECT DISTINCT i.pdf_filename, i.page_number, d.form_type
                    FROM items_current i
                    INNER JOIN documents_current d ON i.pdf_filename = d.pdf_filename
                    WHERE """ + where_clause + """
                    UNION
                    SELECT DISTINCT i.pdf_filename, i.page_number, d.form_type
                    FROM items_archive i
                    INNER JOIN documents_archive d ON i.pdf_filename = d.pdf_filename
                    WHERE """ + where_clause + """
                    ORDER BY pdf_filename, page_number
                """
                cursor.execute(sql, params * 2)
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            print(f"⚠️ get_page_keys_by_super_names 실패: {e}")
            return []

    def _item_customer_expr(self) -> str:
        """거래처는 得意先로 통일 (양식 무관). item_data->>'得意先' 없으면 customer 컬럼."""
        return """COALESCE(
            NULLIF(trim(i.item_data->>'得意先'), ''),
            NULLIF(trim(i.customer), ''),
            ''
        )"""

    def get_page_keys_by_customer_names(
        self,
        customer_names: List[str],
        form_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        detail 페이지 得意先와 동일한 값이 주어진 목록에 포함된 항목이 있는 페이지 목록 반환 (완전 일치).
        item_data 得意先/得意先名 등 + customer 컬럼 반영.

        Returns:
            [{ pdf_filename, page_number, form_type }, ...]
        """
        names_trimmed = [n.strip() for n in customer_names if n and n.strip()]
        if not names_trimmed:
            return []
        cust_expr = self._item_customer_expr()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                placeholders = ", ".join(["%s"] * len(names_trimmed))
                cond = f"({cust_expr}) IN ({placeholders})"
                conditions = [cond]
                params: List[Any] = list(names_trimmed)
                if form_type:
                    conditions.append("d.form_type = %s")
                    params.append(form_type)
                where_clause = " AND ".join(conditions)
                sql = f"""
                    SELECT DISTINCT i.pdf_filename, i.page_number, d.form_type
                    FROM items_current i
                    INNER JOIN documents_current d ON i.pdf_filename = d.pdf_filename
                    WHERE {where_clause}
                    UNION
                    SELECT DISTINCT i.pdf_filename, i.page_number, d.form_type
                    FROM items_archive i
                    INNER JOIN documents_archive d ON i.pdf_filename = d.pdf_filename
                    WHERE {where_clause}
                    ORDER BY pdf_filename, page_number
                """
                cursor.execute(sql, params * 2)
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            print(f"⚠️ get_page_keys_by_customer_names 실패: {e}")
            return []

    # ============================================
    # 이미지 관리 메서드
    # ============================================

    def _get_image_path(self, pdf_filename: str, page_number: int) -> str:
        """
        이미지 파일 경로 반환 (프로젝트 루트 기준 상대 경로).
        실행 디렉터리(cwd)에 무관하게 동일한 상대 경로를 반환합니다.
        """
        image_dir = Path("static/images") / pdf_filename
        return str(image_dir / f"page_{page_number}.jpg")

    def save_image_to_file(
        self,
        pdf_filename: str,
        page_number: int,
        image_data: bytes
    ) -> str:
        """
        이미지를 파일 시스템에 저장 (프로젝트 루트 기준 경로에 저장).
        Returns:
            DB 저장용 상대 경로 (static/images/...)
        """
        relative_path = self._get_image_path(pdf_filename, page_number)
        full_path = get_project_root() / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, 'wb') as f:
            f.write(image_data)
        return relative_path

    def get_page_image_path(
        self,
        pdf_filename: str,
        page_number: int
    ) -> Optional[str]:
        """
        페이지 이미지 파일 경로 조회 (성능 최적화: current 먼저 조회)

        Args:
            pdf_filename: PDF 파일명
            page_number: 페이지 번호 (1부터 시작)

        Returns:
            이미지 파일 경로 또는 None
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # 성능 최적화: current에서 먼저 조회, 없으면 archive 조회
                # UNION ALL 대신 순차 조회로 변경하여 인덱스 활용 최대화
                cursor.execute("""
                    SELECT image_path FROM page_images_current
                    WHERE pdf_filename = %s AND page_number = %s
                    LIMIT 1
                """, (pdf_filename, page_number))
                
                result = cursor.fetchone()
                if result and result[0]:
                    return result[0]
                
                # current에 없으면 archive에서 조회
                cursor.execute("""
                    SELECT image_path FROM page_images_archive
                    WHERE pdf_filename = %s AND page_number = %s
                    LIMIT 1
                """, (pdf_filename, page_number))
                
                result = cursor.fetchone()
                if result and result[0]:
                    return result[0]

                return None
        except Exception:
            return None
    
    # ============================================
    # 유틸리티 메서드
    # ============================================
    
    def _reorder_by_key_order(self, json_data: Dict[str, Any], key_order: Dict[str, Any]) -> Dict[str, Any]:
        """
        메타데이터의 키 순서를 사용하여 JSON 재정렬
        
        Args:
            json_data: 재정렬할 JSON 딕셔너리
            key_order: {
                "page_keys": ["page_number", "page_role", ...],
                "item_keys": ["照会番号", "management_id", ...]
            }
            
        Returns:
            키 순서가 재정렬된 JSON 딕셔너리
        """
        if not key_order:
            return json_data
        
        reordered = {}
        page_keys = key_order.get("page_keys", [])
        item_keys = key_order.get("item_keys", [])
        
        # 페이지 레벨 키 순서대로 추가
        for key in page_keys:
            if key in json_data:
                if key == "items" and isinstance(json_data[key], list) and item_keys:
                    # items 배열 내부 객체들도 재정렬
                    reordered_items = []
                    for item in json_data[key]:
                        if isinstance(item, dict):
                            reordered_item = {}
                            # 정의된 키 순서대로 추가
                            for item_key in item_keys:
                                if item_key in item:
                                    reordered_item[item_key] = item[item_key]
                            # 정의에 없지만 결과에 있는 키 추가 (순서는 뒤로)
                            for item_key in item.keys():
                                if item_key not in item_keys:
                                    reordered_item[item_key] = item[item_key]
                            reordered_items.append(reordered_item)
                        else:
                            reordered_items.append(item)
                    reordered[key] = reordered_items
                else:
                    reordered[key] = json_data[key]
        
        # 정의에 없지만 결과에 있는 키 추가 (순서는 뒤로)
        for key in json_data.keys():
            if key not in page_keys:
                reordered[key] = json_data[key]
        
        return reordered
    
    def _reorder_by_original_file(
        self,
        pdf_filename: str,
        page_num: int,
        page_json: Dict[str, Any],
        is_page: bool = True,
        form_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        벡터 DB 메타데이터의 키 순서를 사용하여 재정렬 (최적화: form_type 파라미터로 중복 조회 방지)
        
        Args:
            pdf_filename: PDF 파일명 (예: "xxx.pdf")
            page_num: 페이지 번호
            page_json: 재정렬할 JSON 데이터
            is_page: True면 페이지 전체, False면 item만
            form_type: 양식지 타입 (선택, 미제공 시 자동 조회)
            
        Returns:
            키 순서가 재정렬된 JSON
        """
        try:
            # form_type 조회 (DB에서, 미제공 시에만)
            if form_type is None:
                try:
                    doc_info = self.get_document(pdf_filename)
                    if doc_info:
                        form_type = doc_info.get("form_type")
                except Exception:
                    pass
            
            # 벡터 DB에서 키 순서 가져오기
            if form_type:
                try:
                    from modules.core.rag_manager import get_rag_manager
                    rag_manager = get_rag_manager()
                    key_order = rag_manager.get_key_order_by_form_type(form_type)
                    
                    if key_order:
                        reordered = self._reorder_by_key_order(page_json, key_order)
                        return reordered
                except Exception:
                    pass
            
            return page_json
                
        except Exception:
            return page_json
    
    def get_all_pdf_filenames(self) -> List[str]:
        """
        모든 PDF 파일명 목록 반환 (documents_current + documents_archive)
        
        Returns:
            PDF 파일명 리스트
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT pdf_filename
                    FROM (
                        SELECT pdf_filename FROM documents_current
                        UNION ALL
                        SELECT pdf_filename FROM documents_archive
                    ) t
                    ORDER BY pdf_filename
                """)
                return [row[0] for row in cursor.fetchall()]
        except Exception:
            return []

    def get_review_tab_pdf_filenames(
        self,
        in_vector_pdf_filenames: List[str],
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> List[str]:
        """
        검토 탭에 해당하는 PDF 파일명 목록 (정답지 제외, 벡터 인덱스 제외).
        data_year/data_month 가 있는 문서만 포함.

        Args:
            in_vector_pdf_filenames: 벡터 인덱스에 포함된 pdf_filename 목록 (제외 대상)
            year: 연도 (None이면 전체)
            month: 월 (None이면 전체)

        Returns:
            검토 탭 PDF 파일명 리스트
        """
        in_vector_set = set(f.strip().lower() for f in (in_vector_pdf_filenames or []) if f)
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if year is not None and month is not None:
                    cursor.execute(
                        """
                        SELECT DISTINCT pdf_filename
                        FROM (
                            SELECT pdf_filename FROM documents_current
                            WHERE (is_answer_key_document IS NULL OR is_answer_key_document = FALSE)
                              AND data_year IS NOT NULL AND data_month IS NOT NULL
                              AND data_year = %s AND data_month = %s
                            UNION ALL
                            SELECT pdf_filename FROM documents_archive
                            WHERE (is_answer_key_document IS NULL OR is_answer_key_document = FALSE)
                              AND data_year IS NOT NULL AND data_month IS NOT NULL
                              AND data_year = %s AND data_month = %s
                        ) t
                        ORDER BY pdf_filename
                        """,
                        (year, month, year, month),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT DISTINCT pdf_filename
                        FROM (
                            SELECT pdf_filename FROM documents_current
                            WHERE (is_answer_key_document IS NULL OR is_answer_key_document = FALSE)
                              AND data_year IS NOT NULL AND data_month IS NOT NULL
                            UNION ALL
                            SELECT pdf_filename FROM documents_archive
                            WHERE (is_answer_key_document IS NULL OR is_answer_key_document = FALSE)
                              AND data_year IS NOT NULL AND data_month IS NOT NULL
                        ) t
                        ORDER BY pdf_filename
                        """
                    )
                rows = cursor.fetchall()
                pdfs = [row[0] for row in rows if row[0]]
                return [p for p in pdfs if (p or "").strip().lower() not in in_vector_set]
        except Exception as e:
            print(f"⚠️ get_review_tab_pdf_filenames 실패: {e}")
            return []

    def get_distinct_customer_names_for_pdfs(self, pdf_filenames: List[str]) -> List[str]:
        """
        지정한 PDF 목록에 등장하는 거래처명(得意先/customer) 중복 제거 목록.

        Args:
            pdf_filenames: PDF 파일명 리스트

        Returns:
            거래처명 리스트 (빈 문자열 제외, 정렬)
        """
        if not pdf_filenames:
            return []
        cust_expr = self._item_customer_expr()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ", ".join(["%s"] * len(pdf_filenames))
                sql = f"""
                    SELECT DISTINCT {cust_expr} AS name
                    FROM items_current i
                    WHERE i.pdf_filename IN ({placeholders})
                    UNION
                    SELECT DISTINCT {cust_expr} AS name
                    FROM items_archive i
                    WHERE i.pdf_filename IN ({placeholders})
                """
                cursor.execute(sql, pdf_filenames + pdf_filenames)
                rows = cursor.fetchall()
                names = [r[0].strip() for r in rows if r and r[0] and str(r[0]).strip()]
                return sorted(set(names))
        except Exception as e:
            print(f"⚠️ get_distinct_customer_names_for_pdfs 실패: {e}")
            return []

