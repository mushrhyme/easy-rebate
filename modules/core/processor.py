"""
PDF 처리 모듈

PDF 처리 로직을 중앙화하여 관리합니다.
"""

import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Callable, List

# PdfRegistry 제거됨 - DB와 st.session_state로 대체


class PdfProcessor:
    """
    PDF 처리 클래스
    
    PDF 파일을 OCR 분석하고 결과를 저장하는 로직을 중앙화합니다.
    """
    
    DEFAULT_DPI = 200
    
    @staticmethod
    def process_pdf(
        pdf_name: str,
        pdf_path: Optional[str] = None,
        dpi: int = DEFAULT_DPI,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        form_type: Optional[str] = None,
        upload_channel: Optional[str] = None,
        user_id: Optional[int] = None,
        data_year: Optional[int] = None,
        data_month: Optional[int] = None,
        include_bbox: bool = False,
        page_numbers: Optional[list] = None,  # 지정 시 해당 페이지만 분석 (1-based). None=전체
        convert_all_images: bool = False,  # True면 전체 이미지 변환 후 page_numbers만 분석 (구 레거시)
        on_document_ready: Optional[Callable[[int, Any], None]] = None,  # (total_pages, pil_images) 문서·이미지 선저장용
        on_page_complete: Optional[Callable[[int, Dict[str, Any]], None]] = None,  # (page_number, page_json) 페이지별 완료 시
    ) -> Tuple[bool, int, Optional[str], float]:
        """
        저장된 PDF 파일 처리
        
        Args:
            pdf_name: PDF 파일명 (확장자 제외)
            pdf_path: PDF 파일 경로 (None이면 자동으로 찾음)
            dpi: PDF 변환 해상도 (기본값: 200)
            progress_callback: 진행률 콜백 함수 (page_num, total_pages, message)
            form_type: 양식지 번호 (01, 02, 03, 04, 05). None이면 자동 추출 시도
            
        Returns:
            (성공 여부, 페이지 수, 에러 메시지, 소요 시간) 튜플
        """
        start_time = time.time()
        
        try:
            # 순환 import 방지를 위해 함수 내부에서 import
            from modules.utils.session_manager import SessionManager
            from modules.utils.pdf_utils import find_pdf_path
            
            # 1. PDF 파일 경로 확인
            if pdf_path is None:
                pdf_path = find_pdf_path(pdf_name)
                if pdf_path is None:
                    return False, 0, f"PDF 파일을 찾을 수 없습니다: {pdf_name}", 0.0
            
            # 2. 상태는 st.session_state로 관리 (PdfRegistry 제거됨)
            
            # 3. PDF 파싱 (DB 우선 사용, 없으면 RAG 기반 분석)
            # RAG 기반 파싱만 사용 (무조건 RAG 사용)
            from modules.core.extractors.rag_pages_extractor import extract_pages_with_rag
            from modules.utils.config import rag_config
            
            # form_type이 없으면 DB에서 가져오기 시도
            if not form_type:
                try:
                    from database.registry import get_db
                    db_manager = get_db()
                    pdf_filename = f"{pdf_name}.pdf"
                    doc = db_manager.get_document(pdf_filename)
                    if doc and doc.get('form_type'):
                        form_type = doc['form_type']
                except Exception:
                    pass
            
            config = rag_config
            try:
                page_results, image_paths, pil_images = extract_pages_with_rag(
                    pdf_path=pdf_path,
                    openai_model=config.openai_model,
                    dpi=dpi if dpi else config.dpi,
                    save_images=False,
                    question=config.question,
                    top_k=config.top_k,
                    similarity_threshold=config.similarity_threshold,
                    progress_callback=progress_callback,
                    form_type=form_type,
                    upload_channel=upload_channel,
                    debug_dir_name="debug2",
                    include_bbox=include_bbox,
                    page_numbers=page_numbers,
                    convert_all_images=convert_all_images,
                    on_document_ready=on_document_ready,
                    on_page_complete=on_page_complete,
                )
            except Exception as parse_error:
                raise RuntimeError(f"PDF 파싱 실패: {parse_error}") from parse_error
            
            # page_results가 None이거나 빈 리스트인지 확인
            if page_results is None or len(page_results) == 0:
                raise ValueError("파싱 결과가 없습니다")

            # 3.1. form_type을 RAG에서 사용한 참조 예제의 form_type으로 재설정
            # 각 페이지의 _rag_reference.form_type 중 유효한 값을 모아 가장 많이 등장하는 값으로 결정
            pdf_filename_for_log = f"{pdf_name}.pdf"
            print(f"[form_type] processor 입력 form_type={form_type!r}, 페이지 수={len(page_results)}")
            try:
                rag_form_types = []
                for page_json in page_results:
                    if isinstance(page_json, dict):
                        ref = page_json.get("_rag_reference") or {}
                        ref_form_type = ref.get("form_type")
                        if isinstance(ref_form_type, str) and ref_form_type.strip():
                            rag_form_types.append(ref_form_type.strip())
                print(f"[form_type] RAG 참조 수집: rag_form_types={rag_form_types!r} (len={len(rag_form_types)})")
                if rag_form_types:
                    # 가장 많이 등장한 form_type 선택
                    from collections import Counter
                    most_common_form_type, _ = Counter(rag_form_types).most_common(1)[0]
                    if most_common_form_type and most_common_form_type != form_type:
                        print(f"📋 RAG 참조 예제 기준 form_type 재설정: {form_type!r} → {most_common_form_type!r}")
                        form_type = most_common_form_type
                    else:
                        print(f"[form_type] RAG most_common={most_common_form_type!r}, 유지 form_type={form_type!r}")
                else:
                    print(f"[form_type] 경고: _rag_reference.form_type 없음 → 기존 form_type 유지={form_type!r}")
            except Exception as _e:
                # form_type 추론 실패 시에는 기존 form_type 그대로 사용
                print(f"[form_type] RAG form_type 추론 예외: {_e!r} → form_type 유지={form_type!r}")
                pass
            print(f"[form_type] save_document_data 호출 직전: pdf_filename={pdf_filename_for_log!r}, form_type={form_type!r}")
            
            # 3.4a. 상동기호(//, 11 등) → null (프롬프트로 해결 안 된 경우, 빈값 채우기 직전)
            try:
                from modules.utils.fill_empty_values_utils import normalize_ditto_like_values_in_page_results
                page_results = normalize_ditto_like_values_in_page_results(page_results)
            except Exception:
                pass
            # 3.5. 빈값 채우기 (직전 페이지에서 관리번호/거래처명/摘要, 다음 페이지에서 세액 + 商品名等 이전 행)
            try:
                from modules.utils.fill_empty_values_utils import fill_empty_values_in_page_results
                page_results = fill_empty_values_in_page_results(page_results, form_type=form_type)
            except Exception:
                pass

            # 3.6. 양식지 2번: 最終金額 = 金額+金額2（金額2 空は 0、金額·金額2は上書きしない）
            try:
                from modules.utils.form2_rebate_utils import normalize_form2_rebate_conditions
                page_results = normalize_form2_rebate_conditions(page_results, form_type=form_type)
            except Exception:
                pass
            
            # 4. PIL Image 객체를 bytes로 변환하여 DB에 저장
            try:
                from database.registry import get_db
                import io

                # 전역 DB 인스턴스 사용
                db_manager = get_db()

                # PDF 파일명 (확장자 포함)
                pdf_filename = f"{pdf_name}.pdf"

                # PIL Image 객체를 bytes로 변환
                image_data_list = None
                if pil_images:
                    image_data_list = []
                    for img in pil_images:
                        if img:
                            # PIL Image를 JPEG bytes로 변환
                            img_bytes = io.BytesIO()
                            # RGB 모드로 변환 (JPEG는 RGB만 지원)
                            if img.mode != 'RGB':
                                img = img.convert('RGB')
                            img.save(img_bytes, format='JPEG', quality=95, optimize=True)
                            image_data_list.append(img_bytes.getvalue())
                        else:
                            image_data_list.append(None)

                # 분석 직후·DB 저장 전: 1(RAG)→2→3→4 매핑 선적용 (受注先コード/小売先コード/商品コード를 page_results에 넣어서 저장)
                try:
                    from modules.utils.retail_resolve import resolve_retail_dist
                    from modules.utils.config import get_project_root
                    from backend.unit_price_lookup import resolve_product_and_prices
                    _unit_price_csv = get_project_root() / "database" / "csv" / "unit_price.csv"
                    for page_json in page_results:
                        if not isinstance(page_json, dict):
                            continue
                        for item_dict in page_json.get("items") or []:
                            if not isinstance(item_dict, dict):
                                continue
                            customer_name = (
                                item_dict.get("得意先")
                                or item_dict.get("得意先名")
                                or item_dict.get("得意先様")
                                or item_dict.get("取引先")
                            )
                            customer_code = item_dict.get("得意先コード")
                            retail_code, dist_code = resolve_retail_dist(customer_name, customer_code)
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
                            from modules.utils.finet01_cs_utils import apply_finet01_cs_irisu
                            apply_finet01_cs_irisu(item_dict, form_type, upload_channel)  # FINET 01 + 数量単位=CS → 仕切・本部長 *= 入数
                except Exception:
                    pass

                # DB에 저장 (이미지 데이터 직접 전달)
                # convert_all_images(업로드) 또는 page_numbers 사용 시 total_pages는 PDF 전체 페이지 수
                try:
                    total_pages_override = None
                    if page_numbers or convert_all_images:
                        import fitz
                        with fitz.open(pdf_path) as doc:
                            total_pages_override = len(doc)
                    print(f"[DEBUG] save_document_data 호출: pdf_filename={pdf_filename!r}, pages={len(page_results)}, images={len(image_data_list or [])}")
                    success = db_manager.save_document_data(
                        pdf_filename=pdf_filename,
                        page_results=page_results,
                        image_data_list=image_data_list,
                        form_type=form_type,
                        upload_channel=upload_channel,
                        notes="RAG 기반 분석",
                        user_id=user_id,
                        data_year=data_year,
                        data_month=data_month,
                        total_pages_override=total_pages_override,
                    )
                    print(f"[DEBUG] save_document_data 결과: success={success}")
                    if not success:
                        print("[DEBUG] 문서 저장 실패 (success=False) -> RuntimeError 발생")
                        raise RuntimeError("문서 저장에 실패했습니다.")
                    
                except Exception as save_error:
                    import traceback
                    traceback.print_exc()
                    raise
            except Exception as db_error:
                # DB 저장 실패 시 에러 반환
                raise RuntimeError(f"DB 저장 실패: {db_error}")
            
            # 5. 진행률 업데이트
            for page_num, page_json in enumerate(page_results, 1):
                if progress_callback:
                    progress_callback(page_num, len(page_results), f"ページ {page_num}/{len(page_results)} 処理完了")
                
            # 7. 처리 완료
            elapsed_time = time.time() - start_time
            
            return True, len(page_results), None, elapsed_time
            
        except Exception as e:
            error_msg = str(e)
            elapsed_time = time.time() - start_time
            
            # 에러 상태는 st.session_state로 관리 (PdfRegistry 제거됨)
            
            return False, 0, error_msg, elapsed_time
    
    @staticmethod
    def process_uploaded_pdf(
        uploaded_file,
        pdf_name: str,
        dpi: int = DEFAULT_DPI,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        form_type: Optional[str] = None
    ) -> Tuple[bool, int, Optional[str], float]:
        """
        업로드된 PDF 파일 처리
        
        Args:
            uploaded_file: Streamlit UploadedFile 객체
            pdf_name: PDF 파일명 (확장자 제외)
            dpi: PDF 변환 해상도 (기본값: 200)
            progress_callback: 진행률 콜백 함수
            form_type: 양식지 번호 (01, 02, 03, 04, 05). None이면 자동 추출 시도
            
        Returns:
            (성공 여부, 페이지 수, 에러 메시지, 소요 시간) 튜플
        """
        # 순환 import 방지를 위해 함수 내부에서 import
        from modules.utils.session_manager import SessionManager
        
        # 1. PDF 파일 저장
        pdf_path = SessionManager.save_pdf_file(uploaded_file, pdf_name)
        
        # 2. 상태는 st.session_state로 관리 (PdfRegistry 제거됨)
        
        # 3. 처리 실행
        return PdfProcessor.process_pdf(
            pdf_name=pdf_name,
            pdf_path=pdf_path,
            dpi=dpi,
            progress_callback=progress_callback,
            form_type=form_type
        )
    
    @staticmethod
    def can_process_pdf(pdf_name: str) -> bool:
        """
        PDF를 처리할 수 있는지 확인 (PdfRegistry 제거됨 - 항상 True 반환)
        
        Args:
            pdf_name: PDF 파일명 (확장자 제외)
            
        Returns:
            처리 가능 여부 (항상 True)
        """
        # PdfRegistry 제거됨 - 항상 처리 가능
        return True
    
    @staticmethod
    def get_processing_status(pdf_name: str) -> Dict[str, Any]:
        """
        PDF 처리 상태 조회 (PdfRegistry 제거됨 - DB에서 조회)
        
        Args:
            pdf_name: PDF 파일명 (확장자 제외)
            
        Returns:
            상태 딕셔너리
        """
        # DB에서 페이지 수 확인
        try:
            from database.registry import get_db
            db_manager = get_db()
            pdf_filename = f"{pdf_name}.pdf"
            page_results = db_manager.get_page_results(pdf_filename=pdf_filename)
            pages = len(page_results) if page_results else 0
            status = "completed" if pages > 0 else "pending"
        except Exception:
            pages = 0
            status = "pending"
        
        return {
            "status": status,
            "pages": pages,
            "error": None,
            "last_updated": None,
            "pdf_name": pdf_name
        }

