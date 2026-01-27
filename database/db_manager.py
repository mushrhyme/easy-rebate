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
                query_time = time.perf_counter() - query_start  # 쿼리 시간 측정 종료
                if row:
                    print(f"⏱️ [DB 성능] get_document: {query_time:.3f}초")
                return dict(row) if row else None
        except Exception as e:
            print(f"⚠️ 문서 조회 실패: {e}")
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
        except Exception as e:
            print(f"⚠️ 문서 확인 실패: {e}")
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
        form_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        거래처명으로 항목 검색 (items 테이블에서 직접 조회)
        
        Args:
            customer_name: 거래처명 (부분 일치 검색 가능)
            pdf_filename: PDF 파일명 (None이면 전체 DB에서 검색)
            exact_match: True면 정확히 일치, False면 부분 일치 (ILIKE 검색)
            form_type: 양식지 번호 (01, 02, 03, 04, 05). None이면 모든 양식지
            
        Returns:
            검색된 항목 리스트 (공통 필드 + item_data 병합)
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                # 검색 값 준비
                search_value = customer_name if exact_match else f'%{customer_name}%'
                operator = "=" if exact_match else "ILIKE"
                
                # WHERE 조건 구성
                conditions = ["i.customer IS NOT NULL", f"i.customer {operator} %s"]
                params = [search_value]
                
                # pdf_filename 필터
                if pdf_filename:
                    conditions.append("i.pdf_filename = %s")
                    params.append(pdf_filename)
                
                # form_type 필터
                if form_type:
                    conditions.append("d.form_type = %s")
                    params.append(form_type)
                
                # SQL 쿼리 구성 (items_current와 items_archive 모두 조회)
                if form_type or pdf_filename:
                    sql = """
                        SELECT 
                            i.item_id,
                            i.pdf_filename,
                            i.page_number,
                            i.item_order,
                            i.customer,
                            i.product_name,
                            i.first_review_checked,
                            i.second_review_checked,
                            i.first_reviewed_at,
                            i.second_reviewed_at,
                            i.item_data,
                            i.version,
                            d.form_type
                        FROM items_current i
                        INNER JOIN documents_current d ON i.pdf_filename = d.pdf_filename
                        WHERE """ + " AND ".join(conditions) + """
                        UNION ALL
                        SELECT 
                            i.item_id,
                            i.pdf_filename,
                            i.page_number,
                            i.item_order,
                            i.customer,
                            i.product_name,
                            i.first_review_checked,
                            i.second_review_checked,
                            i.first_reviewed_at,
                            i.second_reviewed_at,
                            i.item_data,
                            i.version,
                            d.form_type
                        FROM items_archive i
                        INNER JOIN documents_archive d ON i.pdf_filename = d.pdf_filename
                        WHERE """ + " AND ".join(conditions) + """
                        ORDER BY pdf_filename, page_number, item_order
                    """
                else:
                    sql = """
                        SELECT 
                            i.item_id,
                            i.pdf_filename,
                            i.page_number,
                            i.item_order,
                            i.customer,
                            i.product_name,
                            i.first_review_checked,
                            i.second_review_checked,
                            i.first_reviewed_at,
                            i.second_reviewed_at,
                            i.item_data,
                            i.version,
                            d.form_type
                        FROM items_current i
                        LEFT JOIN documents_current d ON i.pdf_filename = d.pdf_filename
                        WHERE """ + " AND ".join(conditions) + """
                        UNION ALL
                        SELECT 
                            i.item_id,
                            i.pdf_filename,
                            i.page_number,
                            i.item_order,
                            i.customer,
                            i.product_name,
                            i.first_review_checked,
                            i.second_review_checked,
                            i.first_reviewed_at,
                            i.second_reviewed_at,
                            i.item_data,
                            i.version,
                            d.form_type
                        FROM items_archive i
                        LEFT JOIN documents_archive d ON i.pdf_filename = d.pdf_filename
                        WHERE """ + " AND ".join(conditions) + """
                        ORDER BY pdf_filename, page_number, item_order
                    """
                
                cursor.execute(sql, params)
                fetched_rows = cursor.fetchall()
                print(f"🔍 [search_items_by_customer] 검색 결과: {len(fetched_rows)}개 항목")
                
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
                    
                    # 공통 필드 추가 (원본 필드명 유지)
                    if row_dict.get('customer'):
                        if result_form_type:
                            from modules.utils.config import rag_config
                            customer_fields = rag_config.form_field_mapping.get("customer", {}) if rag_config.form_field_mapping else {}
                            customer_field_name = customer_fields.get(result_form_type, "customer")
                        else:
                            customer_field_name = "customer"
                        merged_item[customer_field_name] = row_dict['customer']
                    
                    if row_dict.get('product_name'):
                        merged_item["商品名"] = row_dict['product_name']
                    
                    # 검토 상태 추가
                    merged_item['review_status'] = {
                        'first_review': {
                            'checked': row_dict.get('first_review_checked', False),
                            'reviewed_at': row_dict.get('first_reviewed_at')
                        },
                        'second_review': {
                            'checked': row_dict.get('second_review_checked', False),
                            'reviewed_at': row_dict.get('second_reviewed_at')
                        }
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
        except Exception as e:
            print(f"⚠️ 거래처명 검색 실패: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    # ============================================
    # 이미지 관리 메서드
    # ============================================

    def _get_image_path(self, pdf_filename: str, page_number: int) -> str:
        """
        이미지 파일 경로 반환

        Args:
            pdf_filename: PDF 파일명
            page_number: 페이지 번호

        Returns:
            이미지 파일 경로
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
        이미지를 파일 시스템에 저장

        Args:
            pdf_filename: PDF 파일명
            page_number: 페이지 번호
            image_data: 이미지 바이너리 데이터

        Returns:
            저장된 파일 경로
        """
        image_path = Path(self._get_image_path(pdf_filename, page_number))
        image_path.parent.mkdir(parents=True, exist_ok=True)

        with open(image_path, 'wb') as f:
            f.write(image_data)

        return str(image_path)

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
        except Exception as e:
            print(f"⚠️ 이미지 경로 조회 실패: {e}")
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
                except Exception as e:
                    print(f"  ⚠️ [키 순서 재정렬] form_type 조회 실패: {e}")
            
            # 벡터 DB에서 키 순서 가져오기
            if form_type:
                try:
                    from modules.core.rag_manager import get_rag_manager
                    rag_manager = get_rag_manager()
                    key_order = rag_manager.get_key_order_by_form_type(form_type)
                    
                    if key_order:
                        reordered = self._reorder_by_key_order(page_json, key_order)
                        print(f"  ✅ [키 순서 재정렬] form_type={form_type} 기준으로 재정렬 완료 (벡터 DB 메타데이터 사용)")
                        return reordered
                    else:
                        print(f"  ⚠️ [키 순서 재정렬] 벡터 DB에서 키 순서를 찾을 수 없음 (원본 그대로 반환)")
                except Exception as e:
                    print(f"  ⚠️ [키 순서 재정렬] 벡터 DB 조회 실패: {e}")
            
            return page_json
                
        except Exception as e:
            print(f"  ⚠️ [키 순서 재정렬] 실패: {e}")
            return page_json
    
    def get_all_pdf_filenames(self) -> List[str]:
        """
        모든 PDF 파일명 목록 반환
        
        Returns:
            PDF 파일명 리스트
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT pdf_filename
                    FROM documents
                    ORDER BY pdf_filename
                """)
                
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            print(f"⚠️ PDF 파일명 목록 조회 실패: {e}")
            return []

