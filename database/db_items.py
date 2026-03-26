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
from modules.utils.master_display_enrich import enrich_master_fields_from_codes
from modules.utils.retail_resolve import resolve_retail_dist
from modules.utils.finet01_cs_utils import apply_finet01_cs_irisu
from modules.utils.form04_mishu_utils import apply_form04_mishu_decimal
from backend.unit_price_lookup import resolve_product_and_prices


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
                "item_data": {...}  # 양식지별 필드 (JSON, 키 순서 유지)
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
        data_month: Optional[int] = None,
        total_pages_override: Optional[int] = None,  # page_numbers 사용 시 실제 PDF 전체 페이지 수
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
        total_pages = total_pages_override if total_pages_override is not None else len(page_results)

        print(f"[form_type] save_document_data 진입: pdf_filename={pdf_filename!r}, form_type={form_type!r} (type={type(form_type).__name__})")
        
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
                # 지정한 년월이 있으면 created_at을 해당 년월 1일로 설정
                from datetime import datetime
                if data_year and data_month:
                    created_at = datetime(data_year, data_month, 1)
                    cursor.execute("""
                        INSERT INTO documents_current (pdf_filename, total_pages, form_type, upload_channel, notes, created_by_user_id, updated_by_user_id, created_at, data_year, data_month, document_metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::json)
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
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::json)
                        ON CONFLICT (pdf_filename) DO UPDATE SET
                            total_pages = EXCLUDED.total_pages,
                            form_type = COALESCE(EXCLUDED.form_type, documents_current.form_type),
                            upload_channel = COALESCE(EXCLUDED.upload_channel, documents_current.upload_channel),
                            notes = EXCLUDED.notes,
                            updated_by_user_id = EXCLUDED.updated_by_user_id,
                            updated_at = CURRENT_TIMESTAMP,
                            document_metadata = COALESCE(EXCLUDED.document_metadata, documents_current.document_metadata)
                    """, (pdf_filename, total_pages, form_type, upload_channel, notes, user_id, user_id, doc_meta_json))
                cursor.execute("SELECT form_type FROM documents_current WHERE pdf_filename = %s LIMIT 1", (pdf_filename,))
                row = cursor.fetchone()
                print(f"[form_type] save_document_data: documents_current 반영 완료, 전달 form_type={form_type!r}, DB 저장값={repr(row[0]) if row else None}")
                
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
                    # page_numbers 사용 시 page_json에 실제 페이지 번호 있음
                    page_number = int(page_json.get("page_number", page_idx + 1))
                    
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
                    
                    # page_meta 구성 (items, RAG 내부 메타 제외 — 정답지에 불필요). ocr_text는 별도 컬럼으로도 저장
                    page_meta = {}
                    for key, value in page_json.items():
                        if key not in ["items", "page_role", "page_number", "_rag_reference", "ocr_text"]:
                            page_meta[key] = value
                    
                    page_role = page_json.get("page_role")
                    page_meta_json = json.dumps(page_meta, ensure_ascii=False) if page_meta else None
                    ocr_text_val = page_json.get("ocr_text") or (page_meta.get("_ocr_text") if isinstance(page_meta.get("_ocr_text"), str) else None)
                    if ocr_text_val and not str(ocr_text_val).strip():
                        ocr_text_val = None
                    try:
                        cursor.execute("""
                            INSERT INTO page_data_current (pdf_filename, page_number, page_role, page_meta, ocr_text)
                            VALUES (%s, %s, %s, %s::json, %s)
                            ON CONFLICT (pdf_filename, page_number)
                            DO UPDATE SET
                                page_role = EXCLUDED.page_role,
                                page_meta = EXCLUDED.page_meta,
                                ocr_text = COALESCE(EXCLUDED.ocr_text, page_data_current.ocr_text),
                                updated_at = CURRENT_TIMESTAMP
                        """, (pdf_filename, page_number, page_role, page_meta_json, ocr_text_val))
                    except Exception:
                        cursor.execute("""
                            INSERT INTO page_data_current (pdf_filename, page_number, page_role, page_meta)
                            VALUES (%s, %s, %s, %s::json)
                            ON CONFLICT (pdf_filename, page_number)
                            DO UPDATE SET
                                page_role = EXCLUDED.page_role,
                                page_meta = EXCLUDED.page_meta,
                                updated_at = CURRENT_TIMESTAMP
                        """, (pdf_filename, page_number, page_role, page_meta_json))
                    
                    # items 저장 (행 단위). 1(RAG)→2→3→4 매핑 확정값을 넣어 DB에 受注先コード/小売先コード/商品コード 저장
                    _unit_price_csv = get_project_root() / "database" / "csv" / "unit_price.csv"
                    for item_order, item_dict in enumerate(items, 1):
                        if not isinstance(item_dict, dict):
                            continue
                        honbu = None  # product_result 없을 때 UnboundLocalError 방지
                        customer_name = (
                            item_dict.get("得意先")
                            or item_dict.get("得意先名")
                            or item_dict.get("得意先様")
                            or item_dict.get("取引先")
                        )
                        retail_code, dist_code = resolve_retail_dist(
                            customer_name,
                            item_dict.get("得意先コード"),
                        )
                        if retail_code:
                            item_dict["小売先コード"] = retail_code
                        if dist_code:
                            item_dict["受注先コード"] = dist_code
                        product_result = resolve_product_and_prices(item_dict.get("商品名"), _unit_price_csv)
                        if product_result:
                            code, shikiri, honbu = product_result
                            if code:
                                item_dict["商品コード"] = code
                            if shikiri is not None:
                                item_dict["仕切"] = shikiri
                            if honbu is not None:
                                item_dict["本部長"] = honbu
                        enrich_master_fields_from_codes(item_dict, _unit_price_csv)
                        apply_finet01_cs_irisu(item_dict, form_type, upload_channel)
                        apply_form04_mishu_decimal(item_dict, form_type)
                        # 최초 분석: LLM이 タイプ를 null로 뱉어도 무조건 条件으로 DB 저장
                        _typ = item_dict.get("タイプ")
                        if _typ is None or (isinstance(_typ, str) and not (_typ or "").strip()):
                            item_dict["タイプ"] = "条件"
                        # 공통 필드와 item_data 분리 (표준 키: 得意先 등은 item_data에만 유지)
                        separated = self._separate_item_fields(item_dict, form_type=form_type)
                        
                        cursor.execute("""
                            INSERT INTO items_current (
                                pdf_filename, page_number, item_order,
                                first_review_checked, second_review_checked,
                                first_reviewed_at, second_reviewed_at,
                                item_data
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::json)
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
                
        except Exception as e:
            import traceback
            print("[DEBUG] save_document_data 실패:", type(e).__name__, str(e))
            traceback.print_exc()
            return False

    def create_document_with_images(
        self,
        pdf_filename: str,
        total_pages: int,
        image_data_list: List[bytes],
        upload_channel: Optional[str] = None,
        user_id: Optional[int] = None,
        data_year: Optional[int] = None,
        data_month: Optional[int] = None,
    ) -> bool:
        """
        업로드 초기: 문서 행 생성 + 전체 페이지 이미지 저장 (분석 전 검토 탭에서 문서 노출용).
        page_data/items는 건드리지 않음.
        """
        try:
            from datetime import datetime
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if data_year and data_month:
                    created_at = datetime(data_year, data_month, 1)
                    cursor.execute("""
                        INSERT INTO documents_current (pdf_filename, total_pages, form_type, upload_channel, notes, created_by_user_id, updated_by_user_id, created_at, data_year, data_month)
                        VALUES (%s, %s, NULL, %s, NULL, %s, %s, %s, %s, %s)
                        ON CONFLICT (pdf_filename) DO UPDATE SET
                            total_pages = EXCLUDED.total_pages,
                            upload_channel = COALESCE(EXCLUDED.upload_channel, documents_current.upload_channel),
                            updated_by_user_id = EXCLUDED.updated_by_user_id,
                            updated_at = CURRENT_TIMESTAMP
                    """, (pdf_filename, total_pages, upload_channel, user_id, user_id, created_at, data_year, data_month))
                else:
                    cursor.execute("""
                        INSERT INTO documents_current (pdf_filename, total_pages, form_type, upload_channel, notes, created_by_user_id, updated_by_user_id)
                        VALUES (%s, %s, NULL, %s, NULL, %s, %s)
                        ON CONFLICT (pdf_filename) DO UPDATE SET
                            total_pages = EXCLUDED.total_pages,
                            upload_channel = COALESCE(EXCLUDED.upload_channel, documents_current.upload_channel),
                            updated_by_user_id = EXCLUDED.updated_by_user_id,
                            updated_at = CURRENT_TIMESTAMP
                    """, (pdf_filename, total_pages, upload_channel, user_id, user_id))
                for page_idx, image_data in enumerate(image_data_list):
                    if not image_data:
                        continue
                    page_number = page_idx + 1
                    try:
                        image_path = self.save_image_to_file(pdf_filename, page_number, image_data)
                        cursor.execute("""
                            INSERT INTO page_images_current (pdf_filename, page_number, image_path, image_format, image_size)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (pdf_filename, page_number)
                            DO UPDATE SET image_path = EXCLUDED.image_path, image_format = EXCLUDED.image_format, image_size = EXCLUDED.image_size, created_at = CURRENT_TIMESTAMP
                        """, (pdf_filename, page_number, image_path, 'JPEG', len(image_data)))
                    except Exception:
                        continue
                return True
        except Exception as e:
            import traceback
            print("[DEBUG] create_document_with_images 실패:", type(e).__name__, str(e))
            traceback.print_exc()
            return False

    def save_single_page_data(
        self,
        pdf_filename: str,
        page_json: Dict[str, Any],
        form_type: Optional[str] = None,
        upload_channel: Optional[str] = None,
        image_data: Optional[bytes] = None,
    ) -> bool:
        """
        단일 페이지만 upsert (다른 페이지 데이터는 삭제하지 않음). Phase 1 단일 페이지 분석/저장용.
        """
        page_number = int(page_json.get("page_number", 1))
        page_role = (page_json.get("page_role") or "detail").strip() or "detail"
        if page_role not in ("cover", "detail", "summary", "reply"):
            page_role = "detail"
        items = page_json.get("items") or []
        if not isinstance(items, list):
            items = []
        if not items and page_role == "detail":
            page_role = "cover" if page_number == 1 else "summary"
        page_meta = {k: v for k, v in page_json.items() if k not in ("items", "page_role", "page_number", "_rag_reference", "ocr_text", "analyzed_vector_version", "last_analyzed_at")}
        page_meta_json = json.dumps(page_meta, ensure_ascii=False) if page_meta else None
        ocr_text_val = page_json.get("ocr_text") or (page_meta.get("_ocr_text") if isinstance(page_meta.get("_ocr_text"), str) else None)
        if ocr_text_val and not str(ocr_text_val).strip():
            ocr_text_val = None
        _unit_price_csv = get_project_root() / "database" / "csv" / "unit_price.csv"
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # 재분석 시 기존 검토 상태 보존: DELETE 전에 item_order별 1차/2차 검토 상태 조회
                # current에 없으면 archive에서 조회 (과거 연월 문서는 archive에 있을 수 있음)
                review_by_order: Dict[int, Dict[str, Any]] = {}
                def _fill_review_from_table(table: str) -> None:
                    cursor.execute(f"""
                        SELECT item_order, first_review_checked, second_review_checked,
                               first_reviewed_at, second_reviewed_at,
                               first_reviewed_by_user_id, second_reviewed_by_user_id
                        FROM {table}
                        WHERE pdf_filename = %s AND page_number = %s
                        ORDER BY item_order
                    """, (pdf_filename, page_number))
                    for row in cursor.fetchall():
                        review_by_order[int(row[0])] = {
                            "first_review_checked": bool(row[1]) if row[1] is not None else False,
                            "second_review_checked": bool(row[2]) if row[2] is not None else False,
                            "first_reviewed_at": row[3],
                            "second_reviewed_at": row[4],
                            "first_reviewed_by_user_id": row[5],
                            "second_reviewed_by_user_id": row[6],
                        }
                try:
                    _fill_review_from_table("items_current")
                    if not review_by_order:
                        _fill_review_from_table("items_archive")
                except Exception:
                    pass
                current_vector_version = 1
                try:
                    cursor.execute("SELECT current_vector_version FROM documents_current WHERE pdf_filename = %s LIMIT 1", (pdf_filename,))
                    row = cursor.fetchone()
                    if row and row[0] is not None:
                        current_vector_version = int(row[0])
                except Exception:
                    pass
                cursor.execute(
                    "DELETE FROM items_current WHERE pdf_filename = %s AND page_number = %s",
                    (pdf_filename, page_number),
                )
                try:
                    cursor.execute("""
                        INSERT INTO page_data_current (pdf_filename, page_number, page_role, page_meta, ocr_text, analyzed_vector_version, last_analyzed_at)
                        VALUES (%s, %s, %s, %s::json, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (pdf_filename, page_number)
                        DO UPDATE SET page_role = EXCLUDED.page_role, page_meta = EXCLUDED.page_meta,
                            ocr_text = COALESCE(EXCLUDED.ocr_text, page_data_current.ocr_text),
                            analyzed_vector_version = EXCLUDED.analyzed_vector_version,
                            last_analyzed_at = EXCLUDED.last_analyzed_at,
                            updated_at = CURRENT_TIMESTAMP
                    """, (pdf_filename, page_number, page_role, page_meta_json, ocr_text_val, current_vector_version))
                except Exception:
                    cursor.execute("""
                        INSERT INTO page_data_current (pdf_filename, page_number, page_role, page_meta)
                        VALUES (%s, %s, %s, %s::json)
                        ON CONFLICT (pdf_filename, page_number)
                        DO UPDATE SET page_role = EXCLUDED.page_role, page_meta = EXCLUDED.page_meta, updated_at = CURRENT_TIMESTAMP
                    """, (pdf_filename, page_number, page_role, page_meta_json))
                for item_order, item_dict in enumerate(items, 1):
                    if not isinstance(item_dict, dict):
                        continue
                    retail_code, dist_code = resolve_retail_dist(
                        item_dict.get("得意先"), item_dict.get("得意先コード")
                    )
                    if retail_code:
                        item_dict["小売先コード"] = retail_code
                    if dist_code:
                        item_dict["受注先コード"] = dist_code
                    product_result = resolve_product_and_prices(item_dict.get("商品名"), _unit_price_csv)
                    if product_result:
                        code, shikiri, honbu = product_result
                        if code:
                            item_dict["商品コード"] = code
                        if shikiri is not None:
                            item_dict["仕切"] = shikiri
                        if honbu is not None:
                            item_dict["本部長"] = honbu
                    enrich_master_fields_from_codes(item_dict, _unit_price_csv)
                    apply_finet01_cs_irisu(item_dict, form_type, upload_channel)
                    apply_form04_mishu_decimal(item_dict, form_type)
                    # 최초 분석: LLM이 タイプ를 null로 뱉어도 무조건 条件으로 DB 저장
                    _typ = item_dict.get("タイプ")
                    if _typ is None or (isinstance(_typ, str) and not (_typ or "").strip()):
                        item_dict["タイプ"] = "条件"
                    separated = self._separate_item_fields(item_dict, form_type=form_type)
                    prev = review_by_order.get(item_order, {})
                    cursor.execute("""
                        INSERT INTO items_current (
                            pdf_filename, page_number, item_order,
                            first_review_checked, second_review_checked,
                            first_reviewed_at, second_reviewed_at,
                            first_reviewed_by_user_id, second_reviewed_by_user_id,
                            item_data
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::json)
                    """, (
                        pdf_filename, page_number, item_order,
                        prev.get("first_review_checked", False),
                        prev.get("second_review_checked", False),
                        prev.get("first_reviewed_at"),
                        prev.get("second_reviewed_at"),
                        prev.get("first_reviewed_by_user_id"),
                        prev.get("second_reviewed_by_user_id"),
                        json.dumps(separated.get("item_data") or {}, ensure_ascii=False),
                    ))
                # 문서에 item_data_keys가 없을 때만 LLM 결과 순서를 한 번 기록 (최초 저장 시)
                if items and isinstance(items[0], dict):
                    cursor.execute("SELECT document_metadata FROM documents_current WHERE pdf_filename = %s LIMIT 1", (pdf_filename,))
                    row = cursor.fetchone()
                    doc_meta = (row[0] or {}) if row and row[0] else {}
                    existing_keys = doc_meta.get("item_data_keys") if isinstance(doc_meta, dict) else None
                    if not existing_keys or (isinstance(existing_keys, list) and len(existing_keys) == 0):
                        keys = list(items[0].keys())
                        if keys:
                            if not isinstance(doc_meta, dict):
                                doc_meta = {}
                            doc_meta["item_data_keys"] = keys
                            cursor.execute(
                                "UPDATE documents_current SET document_metadata = %s::json WHERE pdf_filename = %s",
                                (json.dumps(doc_meta, ensure_ascii=False), pdf_filename),
                            )
                if image_data:
                    try:
                        image_path = self.save_image_to_file(pdf_filename, page_number, image_data)
                        cursor.execute("""
                            INSERT INTO page_images_current (pdf_filename, page_number, image_path, image_format, image_size)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (pdf_filename, page_number)
                            DO UPDATE SET image_path = EXCLUDED.image_path, image_format = EXCLUDED.image_format, image_size = EXCLUDED.image_size, created_at = CURRENT_TIMESTAMP
                        """, (pdf_filename, page_number, image_path, "JPEG", len(image_data)))
                    except Exception:
                        pass
                conn.commit()
                return True
        except Exception as e:
            import traceback
            traceback.print_exc()
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
                
                # item_data JSON·병합 순서 유지 (RAG/document_metadata.item_data_keys로 재정렬하지 않음)
                # — 검토 그리드 열 순을 파싱·저장 순과 맞추기 위함 (merge된 메타 키 순이 덮어쓰던 문제 제거)
                if form_type is None:
                    try:
                        doc_info = self.get_document(pdf_filename)
                        if doc_info:
                            form_type = doc_info.get("form_type")
                    except Exception:
                        pass

                results = []
                for row in rows:
                    row_dict = dict(row)
                    
                    # item_data 파싱 (JSON 컬럼은 드라이버에 따라 dict 또는 str로 반환)
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
                    # 검토 탭 그리드 row에 タイプ 항상 포함 (없으면 null → 저장 시 条件 반영용)
                    if 'タイプ' not in merged_item:
                        merged_item['タイプ'] = item_data.get('タイプ')
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
            
            # 2. page_data 조회 (메타데이터) — 저장은 항상 current에만 되므로 current 우선 조회 후, 없으면 archive
            query_start = time.perf_counter()  # page_data 쿼리 시간 측정 시작
            page_row = None
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                try:
                    cursor.execute("""
                        SELECT page_role, page_meta, last_edited_at, is_rag_candidate, ocr_text, analyzed_vector_version, last_analyzed_at
                        FROM page_data_current
                        WHERE pdf_filename = %s AND page_number = %s
                        LIMIT 1
                    """, (pdf_filename, page_num))
                    page_row = cursor.fetchone()
                except Exception:
                    cursor.execute("""
                        SELECT page_role, page_meta, last_edited_at, is_rag_candidate
                        FROM page_data_current
                        WHERE pdf_filename = %s AND page_number = %s
                        LIMIT 1
                    """, (pdf_filename, page_num))
                    page_row = cursor.fetchone()
                if not page_row:
                    try:
                        cursor.execute("""
                            SELECT page_role, page_meta, last_edited_at, is_rag_candidate, ocr_text, analyzed_vector_version, last_analyzed_at
                            FROM page_data_archive
                            WHERE pdf_filename = %s AND page_number = %s
                            LIMIT 1
                        """, (pdf_filename, page_num))
                        page_row = cursor.fetchone()
                    except Exception:
                        cursor.execute("""
                            SELECT page_role, page_meta, last_edited_at, is_rag_candidate
                            FROM page_data_archive
                            WHERE pdf_filename = %s AND page_number = %s
                            LIMIT 1
                        """, (pdf_filename, page_num))
                        page_row = cursor.fetchone()
            
                    
            # 3. 키 순서: form_type 있으면 RAG 정답 순서 우선, 없으면 document_metadata.item_data_keys
            item_key_order = None
            if form_type:
                try:
                    from modules.core.rag_manager import get_rag_manager
                    rag_manager = get_rag_manager()
                    key_order = rag_manager.get_key_order_by_form_type(form_type)
                    if key_order and key_order.get("item_keys"):
                        item_key_order = key_order.get("item_keys")
                except Exception:
                    pass
            if item_key_order is None and doc_info:
                doc_meta = doc_info.get("document_metadata")
                if isinstance(doc_meta, dict) and doc_meta.get("item_data_keys"):
                    item_key_order = doc_meta["item_data_keys"]
            
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
            
            # 8. 페이지별 JSON 구조 생성 (page_data + items 병합). Phase 3: 히스토리 표시용. Phase 1: ocr_text는 컬럼 우선, 없으면 page_meta._ocr_text
            ocr_text = (page_row or {}).get('ocr_text') if page_row else None
            if not (ocr_text and str(ocr_text).strip()) and isinstance(page_meta.get('_ocr_text'), str):
                ocr_text = page_meta.get('_ocr_text', '').strip() or None
            page_json = {
                'page_number': page_num,
                'page_role': page_row.get('page_role') if page_row else 'detail',
                **page_meta,  # page_meta의 모든 필드 추가
                'items': items,  # 빈 리스트일 수 있음
                'last_edited_at': page_row.get('last_edited_at') if page_row else None,
                'is_rag_candidate': page_row.get('is_rag_candidate') if page_row else False,
            }
            if ocr_text is not None:
                page_json['ocr_text'] = ocr_text
            if page_row and 'analyzed_vector_version' in page_row:
                page_json['analyzed_vector_version'] = page_row.get('analyzed_vector_version')
            if page_row and 'last_analyzed_at' in page_row:
                page_json['last_analyzed_at'] = page_row.get('last_analyzed_at')
            
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
            # 페이지 목록은 항상 current + archive UNION으로 조회 (저장은 항상 current만 사용하므로 화면에 바로 반영되도록)
            with self.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                # 1. 모든 페이지 번호와 메타데이터를 한 번에 조회 (배치 조회)
                # 저장은 항상 page_data_current에만 되므로, current를 항상 포함해 조회해야 방금 저장한 결과가 화면에 보임
                cursor.execute("""
                    SELECT DISTINCT page_number, page_role, page_meta
                    FROM page_data_current
                    WHERE pdf_filename = %s
                    UNION
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

    def update_item_retail_codes(
        self,
        item_id: int,
        dist_code: Optional[str] = None,
        retail_code: Optional[str] = None,
    ) -> bool:
        """
        item_data에 受注先コード·小売先コード를 병합 저장. (검토 탭 최초 조회 시 매핑 결과 반영용)
        JSON 키 순서 유지: 현재 행 조회 → 앱에서 머지 → 전체 UPDATE.
        """
        if not dist_code and not retail_code:
            return False
        patch = {}
        if dist_code is not None and str(dist_code).strip():
            patch["受注先コード"] = str(dist_code).strip()
        if retail_code is not None and str(retail_code).strip():
            patch["小売先コード"] = str(retail_code).strip()
        if not patch:
            return False
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # 1) item_id로 pdf_filename 및 item_data 조회 (current 우선)
                cursor.execute(
                    "SELECT pdf_filename, item_data FROM items_current WHERE item_id = %s",
                    (item_id,),
                )
                row = cursor.fetchone()
                table_suffix = "current"
                if not row:
                    cursor.execute(
                        "SELECT pdf_filename, item_data FROM items_archive WHERE item_id = %s",
                        (item_id,),
                    )
                    row = cursor.fetchone()
                    table_suffix = "archive"
                if not row:
                    return False
                pdf_filename, item_data_raw = row[0], row[1]
                if isinstance(item_data_raw, dict):
                    item_data = dict(item_data_raw)
                elif isinstance(item_data_raw, str):
                    try:
                        item_data = json.loads(item_data_raw)
                    except (TypeError, ValueError):
                        item_data = {}
                else:
                    item_data = {}
                # 2) 문서의 item_data_keys 조회 (순서 유지용, current/archive 동일 키)
                doc_table = "documents_current" if table_suffix == "current" else "documents_archive"
                cursor.execute(
                    f"SELECT document_metadata FROM {doc_table} WHERE pdf_filename = %s LIMIT 1",
                    (pdf_filename,),
                )
                doc_row = cursor.fetchone()
                doc_meta = (doc_row[0] or {}) if doc_row and doc_row[0] else {}
                item_data_keys = doc_meta.get("item_data_keys") if isinstance(doc_meta, dict) else None
                if not item_data_keys or not isinstance(item_data_keys, list):
                    item_data_keys = list(item_data.keys())
                # 3) patch 반영 후 item_data_keys 순으로 정렬
                item_data.update(patch)
                ordered = {k: item_data[k] for k in item_data_keys if k in item_data}
                ordered.update({k: item_data[k] for k in item_data if k not in item_data_keys})
                full_json = json.dumps(ordered, ensure_ascii=False)
                # 4) 전체 교체 UPDATE
                items_table = f"items_{table_suffix}"
                cursor.execute(
                    f"UPDATE {items_table} SET item_data = %s::json WHERE item_id = %s",
                    (full_json, item_id),
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"⚠️ [update_item_retail_codes] 실패: item_id={item_id}, e={e}")
            return False

    def update_item_data_patch(self, item_id: int, patch: Dict[str, Any]) -> bool:
        """
        item_data에 임의 키 병합 저장 (마스터 명칭 등). 키 순서는 update_item_retail_codes와 동일.
        """
        if not patch:
            return False
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT pdf_filename, item_data FROM items_current WHERE item_id = %s",
                    (item_id,),
                )
                row = cursor.fetchone()
                table_suffix = "current"
                if not row:
                    cursor.execute(
                        "SELECT pdf_filename, item_data FROM items_archive WHERE item_id = %s",
                        (item_id,),
                    )
                    row = cursor.fetchone()
                    table_suffix = "archive"
                if not row:
                    return False
                pdf_filename, item_data_raw = row[0], row[1]
                if isinstance(item_data_raw, dict):
                    item_data = dict(item_data_raw)
                elif isinstance(item_data_raw, str):
                    try:
                        item_data = json.loads(item_data_raw)
                    except (TypeError, ValueError):
                        item_data = {}
                else:
                    item_data = {}
                doc_table = "documents_current" if table_suffix == "current" else "documents_archive"
                cursor.execute(
                    f"SELECT document_metadata FROM {doc_table} WHERE pdf_filename = %s LIMIT 1",
                    (pdf_filename,),
                )
                doc_row = cursor.fetchone()
                doc_meta = (doc_row[0] or {}) if doc_row and doc_row[0] else {}
                item_data_keys = doc_meta.get("item_data_keys") if isinstance(doc_meta, dict) else None
                if not item_data_keys or not isinstance(item_data_keys, list):
                    item_data_keys = list(item_data.keys())
                item_data.update(patch)
                ordered = {k: item_data[k] for k in item_data_keys if k in item_data}
                ordered.update({k: item_data[k] for k in item_data if k not in item_data_keys})
                full_json = json.dumps(ordered, ensure_ascii=False)
                items_table = f"items_{table_suffix}"
                cursor.execute(
                    f"UPDATE {items_table} SET item_data = %s::json WHERE item_id = %s",
                    (full_json, item_id),
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"⚠️ [update_item_data_patch] 실패: item_id={item_id}, e={e}")
            return False
