"""
항목 데이터 저장/조회 Mixin

항목(items) 관련 데이터베이스 작업을 담당합니다.
"""
import time
import json
from typing import Dict, Any, List, Optional
from psycopg2.extras import RealDictCursor, Json
from pathlib import Path
from database.table_selector import get_table_name, get_table_suffix
from modules.utils.config import get_project_root


class ItemsMixin:
    """항목 데이터 저장/조회 Mixin"""
    
    def _separate_item_fields(self, item_dict: dict, form_type: Optional[str] = None) -> dict:
        """
        item을 저장할 때 공통 필드와 양식지별 필드로 분리.

        현재 스키마에서는 answer.json 내부 컬럼명을
        양식지와 무관하게 다음과 같이 통일해서 사용한다.
        - 청구번호: 請求番号
        - 거래처명: 得意先
        - 비고: 備考
        - 세액/세액합계: 税額

        따라서 양식지별 form_field_mapping 기반 매핑은 더 이상 사용하지 않고,
        표준화된 일본어 키를 그대로 item_data에 둔다.
        DB 공통 컬럼(customer)은 더 이상 사용하지 않으며, 필요한 모든 정보는
        item_data 내부의 표준 일본어 키(특히 得意先)에서만 읽는다.

        Args:
            item_dict: 원본 item 딕셔너리 (answer.json 한 행)
            form_type: 양식지 코드 (01, 02, ...). 현재 로직에서는 사용하지 않음(호환성용).
            
        Returns:
            {
                "first_review_checked": False,
                "second_review_checked": False,
                "first_reviewed_at": None,
                "second_reviewed_at": None,
                "item_data": {...}  # 양식지별 필드 (JSONB)
            }
        """
        # 공통 필드 (DB 컬럼용)는 더 이상 사용하지 않는다.
        # 모든 비즈니스 로직은 item_data 내부의 표준 일본어 키(예: 得意先)를 직접 참조한다.
        common_fields: Dict[str, Any] = {}

        # 양식지별 필드 추출
        # - 이제는 별도의 양식지별 매핑 없이 answer.json 의 키를 그대로 저장한다.
        # - review_status 관련 필드만 일반 컬럼으로 빼고 나머지는 모두 item_data 에 둔다.
        item_data: Dict[str, Any] = {}
        for key, value in item_dict.items():
            if not key.startswith("review_"):
                item_data[key] = value
        
        # 검토 상태 필드 추출 (일반 컬럼으로 저장)
        review_status = item_dict.get("review_status", {})
        review_fields = {
            "first_review_checked": review_status.get("first_review", {}).get("checked", False) if isinstance(review_status, dict) else False,
            "second_review_checked": review_status.get("second_review", {}).get("checked", False) if isinstance(review_status, dict) else False,
            "first_reviewed_at": review_status.get("first_review", {}).get("reviewed_at") if isinstance(review_status, dict) and isinstance(review_status.get("first_review"), dict) else None,
            "second_reviewed_at": review_status.get("second_review", {}).get("reviewed_at") if isinstance(review_status, dict) and isinstance(review_status.get("second_review"), dict) else None,
        }
        
        return {
            **common_fields,
            **review_fields,
            "item_data": item_data
        }
    
    def save_document_data(
        self,
        pdf_filename: str,
        page_results: List[Dict[str, Any]],
        image_data_list: Optional[List[bytes]] = None,
        form_type: Optional[str] = None,
        upload_channel: Optional[str] = None,
        notes: Optional[str] = None,
        user_id: Optional[int] = None,
        data_year: Optional[int] = None,
        data_month: Optional[int] = None
    ) -> bool:
        """
        문서 데이터 저장 (새 스키마: page_data는 메타데이터만, items는 행 단위로 저장)
        
        Args:
            pdf_filename: PDF 파일명
            page_results: 페이지별 파싱 결과 리스트 (RAG 탭 결과물 그대로)
            image_data_list: 이미지 데이터(bytes) 리스트 (선택)
            form_type: 양식지 번호 (01, 02, 03, 04, 05) - 선택
            notes: 메모 (선택)
            
        Returns:
            저장 성공 여부
        """
        if not page_results:
            raise ValueError("page_results가 비어있습니다.")
        
        # 이 문서가 파싱할 때 사용한 RAG 예제의 키 순서 저장 (표시 시 form_type이 아닌 이 문서 기준으로 key_order 사용)
        document_metadata = {}
        first_page_with_items = next((p for p in page_results if p.get("items") and len(p["items"]) > 0), None)
        if first_page_with_items and isinstance(first_page_with_items["items"][0], dict):
            item_data_keys = list(first_page_with_items["items"][0].keys())
            if item_data_keys:
                document_metadata["item_data_keys"] = item_data_keys
        
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                doc_meta_json = json.dumps(document_metadata, ensure_ascii=False) if document_metadata else None
                
                # 1. 문서 생성 (항상 documents_current에 저장 - 현재 연월이므로)
                total_pages = len(page_results)
                # 지정한 년월이 있으면 created_at을 해당 년월 1일로 설정
                from datetime import datetime
                if data_year and data_month:
                    created_at = datetime(data_year, data_month, 1)
                    cursor.execute("""
                        INSERT INTO documents_current (pdf_filename, total_pages, form_type, upload_channel, notes, created_by_user_id, updated_by_user_id, created_at, data_year, data_month, document_metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (pdf_filename) DO UPDATE SET
                            total_pages = EXCLUDED.total_pages,
                            form_type = COALESCE(EXCLUDED.form_type, documents_current.form_type),
                            upload_channel = COALESCE(EXCLUDED.upload_channel, documents_current.upload_channel),
                            notes = EXCLUDED.notes,
                            updated_by_user_id = EXCLUDED.updated_by_user_id,
                            updated_at = CURRENT_TIMESTAMP,
                            created_at = EXCLUDED.created_at,
                            data_year = EXCLUDED.data_year,
                            data_month = EXCLUDED.data_month,
                            document_metadata = COALESCE(EXCLUDED.document_metadata, documents_current.document_metadata)
                    """, (pdf_filename, total_pages, form_type, upload_channel, notes, user_id, user_id, created_at, data_year, data_month, doc_meta_json))
                else:
                    cursor.execute("""
                        INSERT INTO documents_current (pdf_filename, total_pages, form_type, upload_channel, notes, created_by_user_id, updated_by_user_id, document_metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (pdf_filename) DO UPDATE SET
                            total_pages = EXCLUDED.total_pages,
                            form_type = COALESCE(EXCLUDED.form_type, documents_current.form_type),
                            upload_channel = COALESCE(EXCLUDED.upload_channel, documents_current.upload_channel),
                            notes = EXCLUDED.notes,
                            updated_by_user_id = EXCLUDED.updated_by_user_id,
                            updated_at = CURRENT_TIMESTAMP,
                            document_metadata = COALESCE(EXCLUDED.document_metadata, documents_current.document_metadata)
                    """, (pdf_filename, total_pages, form_type, upload_channel, notes, user_id, user_id, doc_meta_json))
                
                # 2. 기존 데이터 삭제 (재파싱 시) - current 테이블에서만
                cursor.execute("""
                    DELETE FROM items_current WHERE pdf_filename = %s
                """, (pdf_filename,))
                cursor.execute("""
                    DELETE FROM page_data_current WHERE pdf_filename = %s
                """, (pdf_filename,))
                cursor.execute("""
                    DELETE FROM page_images_current WHERE pdf_filename = %s
                """, (pdf_filename,))
                
                # 3. 페이지별 데이터 저장 (page_data: 메타데이터만, items: 행 단위)
                for page_idx, page_json in enumerate(page_results):
                    page_number = page_idx + 1
                    
                    # page_json이 딕셔너리인지 확인
                    if not isinstance(page_json, dict):
                        if isinstance(page_json, list):
                            page_json = {"items": page_json, "page_role": "detail", "error": "잘못된 형식: 리스트가 전달됨"}
                        else:
                            page_json = {"error": f"잘못된 형식: {type(page_json)}", "items": [], "page_role": "detail"}
                    
                    # items 추출
                    items = page_json.get("items", [])
                    if not isinstance(items, list):
                        items = []
                    
                    # page_meta 구성 (items 제외)
                    page_meta = {}
                    for key, value in page_json.items():
                        if key not in ["items", "page_role", "page_number"]:
                            page_meta[key] = value
                    
                    # page_data 저장 (메타데이터만)
                    page_role = page_json.get("page_role")
                    page_meta_json = json.dumps(page_meta, ensure_ascii=False) if page_meta else None
                    
                    cursor.execute("""
                        INSERT INTO page_data_current (pdf_filename, page_number, page_role, page_meta)
                        VALUES (%s, %s, %s, %s::jsonb)
                        ON CONFLICT (pdf_filename, page_number)
                        DO UPDATE SET
                            page_role = EXCLUDED.page_role,
                            page_meta = EXCLUDED.page_meta,
                            updated_at = CURRENT_TIMESTAMP
                    """, (pdf_filename, page_number, page_role, page_meta_json))
                    
                    # items 저장 (행 단위)
                    for item_order, item_dict in enumerate(items, 1):
                        if not isinstance(item_dict, dict):
                            continue
                        
                    # 공통 필드와 item_data 분리 (표준 키: 得意先 등은 item_data에만 유지)
                        separated = self._separate_item_fields(item_dict, form_type=form_type)
                        
                        cursor.execute("""
                            INSERT INTO items_current (
                                pdf_filename, page_number, item_order,
                                first_review_checked, second_review_checked,
                                first_reviewed_at, second_reviewed_at,
                                item_data
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        """, (
                            pdf_filename,
                            page_number,
                            item_order,
                            separated.get("first_review_checked", False),
                            separated.get("second_review_checked", False),
                            separated.get("first_reviewed_at"),
                            separated.get("second_reviewed_at"),
                            json.dumps(separated.get("item_data", {}), ensure_ascii=False)
                        ))
                
                # 4. 이미지 저장 (파일 시스템에 저장하고 DB에는 경로만 저장)
                if image_data_list:
                    images_to_save = []
                    for page_idx, image_data in enumerate(image_data_list):
                        if image_data:
                            page_number = page_idx + 1
                            # 파일 시스템에 이미지 저장
                            try:
                                image_path = self.save_image_to_file(pdf_filename, page_number, image_data)
                                images_to_save.append((pdf_filename, page_number, image_path, len(image_data)))
                            except Exception:
                                continue

                    if images_to_save:
                        for pdf_fn, page_num, img_path, img_size in images_to_save:
                            cursor.execute("""
                                INSERT INTO page_images_current
                                (pdf_filename, page_number, image_path, image_format, image_size)
                                VALUES (%s, %s, %s, %s, %s)
                                ON CONFLICT (pdf_filename, page_number)
                                DO UPDATE SET
                                    image_path = EXCLUDED.image_path,
                                    image_format = EXCLUDED.image_format,
                                    image_size = EXCLUDED.image_size,
                                    created_at = CURRENT_TIMESTAMP
                            """, (pdf_fn, page_num, img_path, 'JPEG', img_size))
                
                return True
                
        except Exception:
            return False
    
    def get_items(
        self,
        pdf_filename: str,
        page_number: Optional[int] = None,
        form_type: Optional[str] = None,
        item_key_order: Optional[List[str]] = None,
        year: Optional[int] = None,
        month: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        항목 목록 조회 (items_current/archive 테이블에서 직접 조회)
        
        Args:
            pdf_filename: PDF 파일명
            page_number: 페이지 번호 (선택, 없으면 전체)
            form_type: 양식지 타입 (선택, 미제공 시 자동 조회)
            item_key_order: 아이템 키 순서 (선택, 미제공 시 자동 조회)
            year: 연도 (선택사항, 없으면 current와 archive 모두에서 찾기)
            month: 월 (선택사항)
            
        Returns:
            항목 리스트 (공통 필드 + item_data 병합)
        """
        query_start = time.perf_counter()  # 쿼리 시간 측정 시작
        # print(f"🔍 [get_items] 시작: pdf_filename={pdf_filename}, page_number={page_number}")
        
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                # 연월에 따라 테이블 선택 및 조회
                rows = []
                if year is not None and month is not None:
                    # 특정 연월 테이블 조회
                    items_table = get_table_name('items', year, month)
                    if page_number:
                        cursor.execute(f"""
                            SELECT 
                                item_id,
                                pdf_filename,
                                page_number,
                                item_order,
                                first_review_checked,
                                second_review_checked,
                                first_reviewed_at,
                                second_reviewed_at,
                                first_reviewed_by_user_id,
                                second_reviewed_by_user_id,
                                item_data,
                                version
                            FROM {items_table}
                            WHERE pdf_filename = %s AND page_number = %s
                            ORDER BY item_order
                        """, (pdf_filename, page_number))
                    else:
                        cursor.execute(f"""
                            SELECT 
                                item_id,
                                pdf_filename,
                                page_number,
                                item_order,
                                first_review_checked,
                                second_review_checked,
                                first_reviewed_at,
                                second_reviewed_at,
                                first_reviewed_by_user_id,
                                second_reviewed_by_user_id,
                                item_data,
                                version
                            FROM {items_table}
                            WHERE pdf_filename = %s
                            ORDER BY page_number, item_order
                        """, (pdf_filename,))
                    rows = cursor.fetchall()
                else:
                    # 성능 최적화: current에서 먼저 조회, 없으면 archive 조회
                    # UNION ALL 대신 순차 조회로 변경하여 인덱스 활용 최대화
                    if page_number:
                        # current에서 먼저 조회
                        cursor.execute("""
                            SELECT 
                                item_id,
                                pdf_filename,
                                page_number,
                                item_order,
                                first_review_checked,
                                second_review_checked,
                                first_reviewed_at,
                                second_reviewed_at,
                                first_reviewed_by_user_id,
                                second_reviewed_by_user_id,
                                item_data,
                                version
                            FROM items_current
                            WHERE pdf_filename = %s AND page_number = %s
                            ORDER BY item_order
                        """, (pdf_filename, page_number))
                        
                        rows = cursor.fetchall()
                        if not rows:
                            # current에 없으면 archive에서 조회
                            cursor.execute("""
                                SELECT 
                                    item_id,
                                    pdf_filename,
                                    page_number,
                                    item_order,
                                    first_review_checked,
                                    second_review_checked,
                                    first_reviewed_at,
                                    second_reviewed_at,
                                    first_reviewed_by_user_id,
                                    second_reviewed_by_user_id,
                                    item_data,
                                    version
                                FROM items_archive
                                WHERE pdf_filename = %s AND page_number = %s
                                ORDER BY item_order
                            """, (pdf_filename, page_number))
                            rows = cursor.fetchall()
                    else:
                        # 전체 페이지 조회: current와 archive 모두 조회 (UNION ALL 사용)
                        cursor.execute("""
                            SELECT 
                                item_id,
                                pdf_filename,
                                page_number,
                                item_order,
                                first_review_checked,
                                second_review_checked,
                                first_reviewed_at,
                                second_reviewed_at,
                                first_reviewed_by_user_id,
                                second_reviewed_by_user_id,
                                item_data,
                                version
                            FROM items_current
                            WHERE pdf_filename = %s
                            UNION ALL
                            SELECT 
                                item_id,
                                pdf_filename,
                                page_number,
                                item_order,
                                first_review_checked,
                                second_review_checked,
                                first_reviewed_at,
                                second_reviewed_at,
                                first_reviewed_by_user_id,
                                second_reviewed_by_user_id,
                                item_data,
                                version
                            FROM items_archive
                            WHERE pdf_filename = %s
                            ORDER BY page_number, item_order
                        """, (pdf_filename, pdf_filename))
                        rows = cursor.fetchall()
                
                # form_type·키 순서: 이 문서가 파싱할 때 사용한 key_order 우선 (document_metadata.item_data_keys), 없으면 form_type으로 RAG 조회
                if form_type is None or item_key_order is None:
                    try:
                        doc_info = self.get_document(pdf_filename)
                        if doc_info:
                            if form_type is None:
                                form_type = doc_info.get("form_type")
                            # 이 문서가 파싱 시 참조한 RAG 예제의 키 순서 (4번 양식지 등 다른 문서 key_order 사용 방지)
                            if item_key_order is None:
                                doc_meta = doc_info.get("document_metadata")
                                if isinstance(doc_meta, dict) and doc_meta.get("item_data_keys"):
                                    item_key_order = doc_meta["item_data_keys"]
                    except Exception:
                        pass
                
                if item_key_order is None and form_type:
                    try:
                        from modules.core.rag_manager import get_rag_manager
                        rag_manager = get_rag_manager()
                        key_order = rag_manager.get_key_order_by_form_type(form_type)
                        if key_order:
                            item_key_order = key_order.get("item_keys")
                            print(f"[db_items get_items] form_type={form_type} RAG key_order 적용 개수={len(item_key_order) if item_key_order else 0} 순서={item_key_order}")
                        else:
                            print(f"[db_items get_items] form_type={form_type} key_order 없음 -> 재정렬 안 함")
                    except Exception as e:
                        print(f"[db_items get_items] key_order 조회 예외: {e}")
                        pass
                elif item_key_order is None:
                    print(f"[db_items get_items] form_type 없음 -> 재정렬 안 함")
                
                results = []
                for row in rows:
                    row_dict = dict(row)
                    
                    # item_data 파싱 (성능 최적화: JSONB는 이미 파싱된 상태)
                    # PostgreSQL의 JSONB 타입은 Python에서 dict로 자동 변환되므로
                    # 불필요한 json.loads() 호출 최소화
                    item_data = row_dict.get('item_data', {})
                    if isinstance(item_data, str):
                        # 문자열인 경우에만 파싱 (드물게 발생)
                        try:
                            item_data = json.loads(item_data)
                        except Exception:
                            item_data = {}
                    elif not isinstance(item_data, dict):
                        # dict가 아닌 경우만 변환 시도
                        try:
                            item_data = json.loads(str(item_data)) if item_data else {}
                        except Exception:
                            item_data = {}
                    # dict인 경우 그대로 사용 (대부분의 경우)
                    
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
                    
                    # 검토 상태 추가 (증빙용: 누가/언제 체크했는지)
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
                            before_keys = list(merged_item.keys())[:10]  # 처음 10개만 로그
                            reordered_item = {}
                            for item_key in item_key_order:
                                if item_key in merged_item:
                                    reordered_item[item_key] = merged_item[item_key]
                            for item_key in merged_item.keys():
                                if item_key not in item_key_order:
                                    reordered_item[item_key] = merged_item[item_key]
                            merged_item = reordered_item
                            if len(results) == 0:  # 첫 행만 로그
                                after_keys = list(merged_item.keys())[:10]
                        except Exception as e:
                            print(f"[db_items get_items] 재정렬 예외: {e}")
                            pass
                    
                    results.append(merged_item)
                
                return results
        except Exception:
            return []
    
    def get_page_result(
        self,
        pdf_filename: str,
        page_num: int
    ) -> Optional[Dict[str, Any]]:
        """
        특정 페이지의 파싱 결과 조회 (page_data + items 병합)
        
        Args:
            pdf_filename: PDF 파일명
            page_num: 페이지 번호 (1부터 시작)
            
        Returns:
            페이지 파싱 결과 딕셔너리 또는 None
        """
        total_start = time.perf_counter()  # 전체 메서드 시간 측정 시작
        
        try:
            # 1. 먼저 문서 정보 조회 (테이블 선택 및 form_type 확인용)
            query_start = time.perf_counter()  # get_document 시간 측정 시작
            doc_info = self.get_document(pdf_filename)
            
            form_type = None
            data_year = None
            data_month = None
            if doc_info:
                form_type = doc_info.get("form_type")
                data_year = doc_info.get("data_year")
                data_month = doc_info.get("data_month")
            
            # 2. page_data 조회 (메타데이터) - 연월에 따라 테이블 선택
            query_start = time.perf_counter()  # page_data 쿼리 시간 측정 시작
            page_row = None
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                if data_year is not None and data_month is not None:
                    # 특정 연월 테이블 조회
                    table_suffix = get_table_suffix(data_year, data_month)
                    page_data_table = f"page_data_{table_suffix}"
                    cursor.execute(f"""
                        SELECT page_role, page_meta
                        FROM {page_data_table}
                        WHERE pdf_filename = %s AND page_number = %s
                    """, (pdf_filename, page_num))
                    page_row = cursor.fetchone()
                else:
                    # current에서 먼저 찾고, 없으면 archive에서 찾기
                    cursor.execute("""
                        SELECT page_role, page_meta
                        FROM page_data_current
                        WHERE pdf_filename = %s AND page_number = %s
                        LIMIT 1
                    """, (pdf_filename, page_num))
                    page_row = cursor.fetchone()
                    
                    if not page_row:
                        cursor.execute("""
                            SELECT page_role, page_meta
                            FROM page_data_archive
                            WHERE pdf_filename = %s AND page_number = %s
                            LIMIT 1
                        """, (pdf_filename, page_num))
                        page_row = cursor.fetchone()
            
                    
            # 3. 키 순서: 이 문서가 파싱 시 참조한 key_order 우선 (document_metadata.item_data_keys), 없으면 form_type으로 RAG 조회
            item_key_order = None
            if doc_info:
                doc_meta = doc_info.get("document_metadata")
                if isinstance(doc_meta, dict) and doc_meta.get("item_data_keys"):
                    item_key_order = doc_meta["item_data_keys"]
            if item_key_order is None and form_type:
                try:
                    from modules.core.rag_manager import get_rag_manager
                    rag_manager = get_rag_manager()
                    key_order = rag_manager.get_key_order_by_form_type(form_type)
                    if key_order:
                        item_key_order = key_order.get("item_keys")
                except Exception:
                    pass
            
            # 4. items 조회 (form_type과 키 순서를 전달하여 중복 조회 방지)
            query_start = time.perf_counter()  # get_items 시간 측정 시작
            items = self.get_items(pdf_filename, page_num, form_type=form_type, item_key_order=item_key_order, year=data_year, month=data_month)
            
            # 5. 페이지 이미지 확인 (성능 최적화: 경로만 확인, 실제 파일 읽기 생략)
            # 프로젝트 루트 기준 경로로 확인 (실행 디렉터리 무관)
            has_image = False
            try:
                image_path = self.get_page_image_path(pdf_filename, page_num)
                if image_path:
                    full_path = Path(image_path) if Path(image_path).is_absolute() else get_project_root() / image_path
                    has_image = full_path.exists()
            except Exception:
                pass  # 이미지 확인 실패는 무시
                
            # page_data도 없고 items도 없고 이미지도 없으면 페이지가 존재하지 않음
            if not page_row and not items and not has_image:
                return None
            
            # 6. page_meta 파싱
            page_meta = {}
            if page_row and page_row.get('page_meta'):
                page_meta_data = page_row.get('page_meta')
                if isinstance(page_meta_data, str):
                    page_meta = json.loads(page_meta_data)
                elif isinstance(page_meta_data, dict):
                    page_meta = page_meta_data
                else:
                    try:
                        page_meta = json.loads(str(page_meta_data)) if page_meta_data else {}
                    except Exception:
                        page_meta = {}
            
            # 8. 페이지별 JSON 구조 생성 (page_data + items 병합)
            page_json = {
                'page_number': page_num,
                'page_role': page_row.get('page_role') if page_row else 'detail',
                **page_meta,  # page_meta의 모든 필드 추가
                'items': items  # 빈 리스트일 수 있음
            }
            
            # 원본 answer.json 파일 기준으로 키 순서 재정렬 (이미 조회한 키 순서 재사용)
            # item_key_order가 None이 아니면 이미 조회한 것이므로 재사용
            if item_key_order and form_type:
                # 키 순서가 이미 있으면 바로 재정렬 (RAG Manager 재접근 방지)
                try:
                    key_order = {
                        "page_keys": [],  # 페이지 키는 필요시 추가
                        "item_keys": item_key_order
                    }
                    page_json = self._reorder_by_key_order(page_json, key_order)
                except Exception:
                    # 재정렬 실패 시 기존 방식 사용
                    page_json = self._reorder_by_original_file(pdf_filename, page_num, page_json, is_page=True, form_type=form_type)
            else:
                # 키 순서가 없으면 기존 방식 사용 (하위 호환성)
                page_json = self._reorder_by_original_file(pdf_filename, page_num, page_json, is_page=True, form_type=form_type)
            
            return page_json
        except Exception:
            return None
    
    def get_page_results(
        self,
        pdf_filename: str
    ) -> List[Dict[str, Any]]:
        """
        페이지별 파싱 결과 조회 (전체 페이지, 성능 최적화: 배치 조회)
        
        Args:
            pdf_filename: PDF 파일명
            
        Returns:
            페이지별 파싱 결과 리스트
        """
        try:
            # 성능 최적화: N+1 쿼리 문제 해결
            # 각 페이지마다 get_page_result()를 호출하는 대신,
            # 필요한 경우 배치 조회를 고려할 수 있으나,
            # 현재 구조상 get_page_result()가 복잡한 로직을 포함하므로
            # 일단 기존 방식 유지하되, page_data 조회는 배치로 최적화
            
            # 먼저 문서 정보 조회 (테이블 선택용)
            doc_info = self.get_document(pdf_filename)
            data_year = doc_info.get("data_year") if doc_info else None
            data_month = doc_info.get("data_month") if doc_info else None
            
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                # 1. 모든 페이지 번호와 메타데이터를 한 번에 조회 (배치 조회)
                if data_year is not None and data_month is not None:
                    # 특정 연월 테이블 조회
                    table_suffix = get_table_suffix(data_year, data_month)
                    page_data_table = f"page_data_{table_suffix}"
                    cursor.execute(f"""
                        SELECT DISTINCT page_number, page_role, page_meta
                        FROM {page_data_table}
                        WHERE pdf_filename = %s
                        ORDER BY page_number
                    """, (pdf_filename,))
                else:
                    # current와 archive 모두 조회
                    cursor.execute("""
                        SELECT DISTINCT page_number, page_role, page_meta
                        FROM page_data_current
                        WHERE pdf_filename = %s
                        UNION ALL
                        SELECT DISTINCT page_number, page_role, page_meta
                        FROM page_data_archive
                        WHERE pdf_filename = %s
                        ORDER BY page_number
                    """, (pdf_filename, pdf_filename))
                
                page_data_rows = cursor.fetchall()
                page_numbers = [row['page_number'] for row in page_data_rows]
                
                # 2. 각 페이지별로 get_page_result() 호출
                # (내부적으로 이미 조회한 page_data를 재사용할 수 있도록 개선 가능)
                results = []
                for page_num in page_numbers:
                    page_result = self.get_page_result(pdf_filename, page_num)
                    if page_result:
                        results.append(page_result)
                
                return results
        except Exception as e:
            return []

    def create_item(
        self,
        pdf_filename: str,
        page_number: int,
        item_data: Dict[str, Any],
        customer: Optional[str] = None,
        after_item_id: Optional[int] = None
    ) -> int:
        """
        새 아이템 생성

        Args:
            pdf_filename: PDF 파일명
            page_number: 페이지 번호
            item_data: 아이템 데이터 (양식지별 필드들, 상품명은 商品名 키 사용)
            customer: 거래처명
            after_item_id: 특정 행 아래에 추가할 경우 해당 행의 item_id (None이면 맨 아래에 추가)

        Returns:
            생성된 아이템의 item_id
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                if after_item_id:
                    # 특정 행 아래에 추가: 해당 행의 item_order 조회
                    # current와 archive 테이블 모두에서 조회
                    cursor.execute("""
                        SELECT item_order
                        FROM items_current
                        WHERE item_id = %s AND pdf_filename = %s AND page_number = %s
                        UNION ALL
                        SELECT item_order
                        FROM items_archive
                        WHERE item_id = %s AND pdf_filename = %s AND page_number = %s
                        LIMIT 1
                    """, (after_item_id, pdf_filename, page_number, after_item_id, pdf_filename, page_number))
                    
                    after_item = cursor.fetchone()
                    if not after_item:
                        print(f"❌ [create_item] after_item_id={after_item_id}인 아이템을 찾을 수 없음: pdf={pdf_filename}, page={page_number}")
                        # 디버깅: 해당 페이지의 모든 item_id 확인
                        # current와 archive 테이블 모두에서 조회
                        cursor.execute("""
                            SELECT item_id, item_order
                            FROM items_current
                            WHERE pdf_filename = %s AND page_number = %s
                            UNION ALL
                            SELECT item_id, item_order
                            FROM items_archive
                            WHERE pdf_filename = %s AND page_number = %s
                            ORDER BY item_order
                        """, (pdf_filename, page_number, pdf_filename, page_number))
                        all_items = cursor.fetchall()
                        print(f"🔍 [create_item] 해당 페이지의 모든 아이템: {all_items}")
                        return -1
                    
                    target_item_order = after_item[0]
                    next_item_order = target_item_order + 1
                    
                    # target_item_order 이후의 모든 행의 item_order를 +1 증가
                    # current 테이블에서만 업데이트 (신규 데이터는 항상 current에 저장)
                    cursor.execute("""
                        UPDATE items_current
                        SET item_order = item_order + 1
                        WHERE pdf_filename = %s
                          AND page_number = %s
                          AND item_order >= %s
                    """, (pdf_filename, page_number, next_item_order))
                    
                    print(f"🔵 [create_item] 특정 행 아래에 추가: after_item_id={after_item_id}, target_order={target_item_order}, next_order={next_item_order}, updated_rows={cursor.rowcount}")
                else:
                    # 맨 아래에 추가: 최대 item_order + 1
                    # current 테이블에서만 조회 (신규 데이터는 항상 current에 저장)
                    cursor.execute("""
                        SELECT COALESCE(MAX(item_order), 0) + 1
                        FROM items_current
                        WHERE pdf_filename = %s AND page_number = %s
                    """, (pdf_filename, page_number))
                    next_item_order = cursor.fetchone()[0]
                    print(f"🔵 [create_item] 맨 아래에 추가: next_order={next_item_order}")

                # 새 아이템 삽입 (항상 items_current에 저장)
                cursor.execute("""
                    INSERT INTO items_current (
                        pdf_filename, page_number, item_order,
                        customer, item_data,
                        first_review_checked, second_review_checked,
                        version, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING item_id
                """, (
                    pdf_filename, page_number, next_item_order,
                    customer, Json(item_data),
                    False, False, 1
                ))

                item_id = cursor.fetchone()[0]
                print(f"✅ [create_item] 새 아이템 생성: item_id={item_id}, pdf={pdf_filename}, page={page_number}, order={next_item_order}")

                return item_id

        except Exception as e:
            print(f"❌ [create_item] 아이템 생성 실패: {e}")
            import traceback
            traceback.print_exc()
            return -1

    def delete_item(self, item_id: int) -> bool:
        """
        아이템 삭제

        Args:
            item_id: 삭제할 아이템 ID

        Returns:
            삭제 성공 여부
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 아이템 존재 확인 및 정보 조회 (로깅용)
                # current와 archive 모두에서 조회
                cursor.execute("""
                    SELECT pdf_filename, page_number, item_order
                    FROM items_current
                    WHERE item_id = %s
                    UNION ALL
                    SELECT pdf_filename, page_number, item_order
                    FROM items_archive
                    WHERE item_id = %s
                    LIMIT 1
                """, (item_id, item_id))

                item_info = cursor.fetchone()
                if not item_info:
                    print(f"⚠️ [delete_item] 아이템을 찾을 수 없음: item_id={item_id}")
                    return False

                pdf_filename, page_number, item_order = item_info

                # 아이템 삭제
                # current에서 먼저 삭제 시도
                cursor.execute("DELETE FROM items_current WHERE item_id = %s", (item_id,))
                deleted_current = cursor.rowcount
                
                # current에서 삭제되지 않았으면 archive에서 삭제
                if deleted_current == 0:
                    cursor.execute("DELETE FROM items_archive WHERE item_id = %s", (item_id,))
                    deleted_archive = cursor.rowcount
                else:
                    deleted_archive = 0

                # 삭제된 행이 1개 이상인지 확인 (current 또는 archive에서 삭제됨)
                total_deleted = deleted_current + deleted_archive
                if total_deleted > 0:
                    # 같은 페이지의 이후 아이템들의 item_order 재정렬
                    # 삭제된 테이블에 따라 재정렬
                    if deleted_current > 0:
                        cursor.execute("""
                            UPDATE items_current
                            SET item_order = item_order - 1
                            WHERE pdf_filename = %s AND page_number = %s AND item_order > %s
                        """, (pdf_filename, page_number, item_order))
                    elif deleted_archive > 0:
                        cursor.execute("""
                            UPDATE items_archive
                            SET item_order = item_order - 1
                            WHERE pdf_filename = %s AND page_number = %s AND item_order > %s
                        """, (pdf_filename, page_number, item_order))

                    print(f"✅ [delete_item] 아이템 삭제 및 순서 재정렬: item_id={item_id}, pdf={pdf_filename}, page={page_number}")
                    return True
                else:
                    print(f"⚠️ [delete_item] 아이템 삭제 실패: item_id={item_id}")
                    return False

        except Exception as e:
            print(f"❌ [delete_item] 아이템 삭제 실패: {e}")
            import traceback
            traceback.print_exc()
            return False
