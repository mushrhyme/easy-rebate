"""
PDF 처리 모듈

PDF 처리 로직을 중앙화하여 관리합니다.
"""

import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Callable
from PIL import Image

# PdfRegistry 제거됨 - DB와 st.session_state로 대체
from .storage import PageStorage


class PdfProcessor:
    """
    PDF 처리 클래스
    
    PDF 파일을 OCR 분석하고 결과를 저장하는 로직을 중앙화합니다.
    """
    
    DEFAULT_DPI = 300
    
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
    ) -> Tuple[bool, int, Optional[str], float]:
        """
        저장된 PDF 파일 처리
        
        Args:
            pdf_name: PDF 파일명 (확장자 제외)
            pdf_path: PDF 파일 경로 (None이면 자동으로 찾음)
            dpi: PDF 변환 해상도 (기본값: 300)
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
            
            # 3.5. 빈값 채우기 (직전 페이지에서 관리번호/거래처명/摘要, 다음 페이지에서 세액)
            # form_type 별 config 매핑이 있으면 해당 필드만 채움. 없으면(get→None) 스킵.
            try:
                from modules.utils.fill_empty_values_utils import fill_empty_values_in_page_results
                page_results = fill_empty_values_in_page_results(page_results, form_type=form_type)
            except Exception:
                pass

            # 3.6. 양식지 2번 전용 후처리: 計算条件（適用人数）가 納価条件인 행은
            # 金額 + 金額2 → 金額에 합산, 金額2 키 삭제 (DB 저장·검토 탭 동일)
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

                # 분석 직후·DB 저장 전: 1→2→3 매핑 선적용 (受注先CD/小売先CD/商品CD를 page_results에 넣어서 저장)
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
                            customer_code = item_dict.get("得意先CD")
                            retail_code, dist_code = resolve_retail_dist(customer_name, customer_code)
                            if retail_code:
                                item_dict["小売先CD"] = retail_code
                            if dist_code:
                                item_dict["受注先CD"] = dist_code
                            product_result = resolve_product_and_prices(item_dict.get("商品名"), _unit_price_csv)
                            if product_result:
                                code, shikiri, honbu = product_result
                                if code:
                                    item_dict["商品CD"] = code
                                if shikiri is not None:
                                    item_dict["仕切"] = shikiri
                                if honbu is not None:
                                    item_dict["本部長"] = honbu
                except Exception:
                    pass

                # DB에 저장 (이미지 데이터 직접 전달)
                try:
                    success = db_manager.save_document_data(
                        pdf_filename=pdf_filename,
                        page_results=page_results,
                        image_data_list=image_data_list,
                        form_type=form_type,
                        upload_channel=upload_channel,
                        notes="RAG 기반 분석",
                        user_id=user_id,
                        data_year=data_year,
                        data_month=data_month
                    )
                    
                    if not success:
                        raise RuntimeError("문서 저장에 실패했습니다.")
                    
                    # 6. 자동으로 img 폴더에 학습 데이터 저장 (설정 활성화 시)
                    try:
                        from modules.utils.config import rag_config
                        if getattr(rag_config, 'auto_save_to_training_folder', True):  # 기본값: True (자동 저장 활성화)
                            from modules.core.training_manager import TrainingManager
                            
                            # PDF 바이트 데이터 준비 (이미 메모리에 있으면 재사용)
                            pdf_bytes = None
                            if pdf_path and os.path.exists(pdf_path):
                                with open(pdf_path, 'rb') as f:
                                    pdf_bytes = f.read()
                            
                            success, message = TrainingManager.save_to_training_folder(
                                pdf_name=pdf_name,
                                pdf_path=Path(pdf_path) if pdf_path else None,
                                form_type=form_type,
                                upload_channel=upload_channel,
                                data_year=data_year,
                                data_month=data_month,
                                pdf_bytes=pdf_bytes
                            )
                    except Exception:
                        pass
                    
                except Exception as save_error:
                    import traceback
                    traceback.print_exc()
                    raise
            except Exception as db_error:
                # DB 저장 실패 시 에러 반환
                raise RuntimeError(f"DB 저장 실패: {db_error}")
            
            # 5. 진행률 업데이트 및 썸네일 생성
            for page_num, page_json in enumerate(page_results, 1):
                if page_json:
                    # 썸네일 생성 (선택적) - PIL Image에서 직접 생성
                    try:
                        if pil_images and page_num <= len(pil_images) and pil_images[page_num - 1]:
                            image = pil_images[page_num - 1]
                            # 썸네일 생성 (200x200)
                            thumbnail = image.copy()
                            thumbnail.thumbnail((200, 200), Image.Resampling.LANCZOS)
                            SessionManager.save_thumbnail(pdf_name, page_num, thumbnail)
                    except Exception:
                        pass  # 썸네일 생성 실패해도 계속 진행
                
                # 진행률 콜백 호출
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
            dpi: PDF 변환 해상도 (기본값: 300)
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
            page_results = db_manager.get_page_results(
                pdf_filename=pdf_filename,
                session_id=None,
                is_latest=True
            )
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

