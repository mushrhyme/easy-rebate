"""
RAG 기반 페이지 추출 모듈

OCR 텍스트를 추출한 후 벡터 DB에서 유사한 예제를 검색하고,
RAG를 사용하여 JSON을 추출합니다.
"""

import os
import time
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from modules.core.extractors.rag_extractor import extract_json_with_rag
from modules.utils.pdf_utils import PdfTextExtractor
from modules.utils.text_normalizer import normalize_ocr_text


def extract_pages_with_rag(
    pdf_path: str,
    openai_api_key: Optional[str] = None,
    openai_model: Optional[str] = None,
    dpi: Optional[int] = None,
    save_images: bool = False,
    image_output_dir: Optional[str] = None,
    question: Optional[str] = None,
    top_k: Optional[int] = None,
    similarity_threshold: Optional[float] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    form_type: Optional[str] = None,
    upload_channel: Optional[str] = None,  # finet | mail. mail일 때 Azure OCR(표 복원) 사용
    debug_dir_name: str = "debug",  # 디버깅 폴더명
    include_bbox: bool = False,  # True일 때만 03/04에서 단어 좌표 추출·LLM _word_indices·_bbox 부여 (새 탭 전용)
    page_numbers: Optional[List[int]] = None,  # 지정 시 해당 페이지만 분석 (1-based). None이면 전체
    convert_all_images: bool = False,  # True(업로드): 전체 이미지 변환 후 page_numbers만 분석. False: page_numbers 페이지만 변환·분석
    on_document_ready: Optional[Callable[[int, List[Image.Image]], None]] = None,  # (total_pages, pil_images) 업로드 시 문서·이미지 저장용
    on_page_complete: Optional[Callable[[int, Dict[str, Any]], None]] = None,  # (page_number, page_json) 페이지별 완료 시 DB 저장·알림용
) -> tuple[List[Dict[str, Any]], List[str], Optional[List[Image.Image]]]:
    """
    PDF 파일을 RAG 기반으로 분석하여 페이지별 JSON 결과 반환
    
    Args:
        pdf_path: PDF 파일 경로
        openai_api_key: OpenAI API 키 (None이면 환경변수 사용)
        openai_model: OpenAI 모델 이름 (None이면 config에서 가져옴)
        dpi: PDF 변환 해상도 (None이면 config에서 가져옴)
        save_images: 이미지를 파일로 저장할지 여부 (기본값: False)
        image_output_dir: 이미지 저장 디렉토리 (사용 안 함)
        question: 질문 텍스트 (None이면 config에서 가져옴)
        top_k: 검색할 예제 수 (None이면 config에서 가져옴)
        similarity_threshold: 최소 유사도 임계값 (None이면 config에서 가져옴)
        form_type: 양식지 번호 (01–06)
        upload_channel: 업로드 채널 (finet | mail). finet→엑셀 추출, mail→Azure OCR(표 복원, bbox 시 단어 좌표)
        
    Returns:
        (페이지별 JSON 결과 리스트, 이미지 파일 경로 리스트, PIL Image 객체 리스트) 튜플
    """
    # 설정값 가져오기 (파라미터가 None이면 config에서 가져옴)
    from modules.utils.config import rag_config
    config = rag_config
    
    openai_model = openai_model or config.openai_model
    dpi = dpi or config.dpi
    question = question or config.question
    top_k = top_k if top_k is not None else config.top_k
    similarity_threshold = similarity_threshold if similarity_threshold is not None else config.similarity_threshold
    rag_llm_workers = config.rag_llm_parallel_workers  # RAG+LLM 병렬 워커 수
    ocr_parallel_workers = getattr(config, "max_parallel_workers", 1)  # Azure OCR 병렬 수 (1=순차)
    
    pdf_name = Path(pdf_path).stem
    pdf_filename = f"{pdf_name}.pdf"
    
    # form_type이 전달되지 않았으면 추출 시도 (경로에서 또는 DB에서)
    if not form_type:
        try:
            from modules.utils.pdf_utils import extract_form_number_from_path
            form_type = extract_form_number_from_path(Path(pdf_path))
            
            # 경로에서 추출 실패 시 DB에서 가져오기
            if not form_type:
                from database.registry import get_db
                db_manager = get_db()
                doc = db_manager.get_document(pdf_filename)
                if doc and doc.get('form_type'):
                    form_type = doc['form_type']
            
            if form_type:
                print(f"📋 양식지 번호 (자동 추출): {form_type}")
        except Exception as e:
            print(f"⚠️ form_type 추출 실패: {e}")
    else:
        print(f"📋 양식지 번호 (전달받음): {form_type}")
    
    # 1. DB에서 먼저 확인. page_numbers 지정 시 특정 페이지만 분석이므로 캐시 스킵
    page_jsons = None
    if not include_bbox and not page_numbers:
        try:
            from database.registry import get_db
            db_manager = get_db()
            page_jsons = db_manager.get_page_results(pdf_filename=pdf_filename)
            if page_jsons and len(page_jsons) > 0:
                print(f"💾 DB에서 기존 파싱 결과 로드: {len(page_jsons)}개 페이지")
                image_paths = [None] * len(page_jsons)
                return page_jsons, image_paths, None
        except Exception as db_error:
            print(f"⚠️ DB 확인 실패: {db_error}. 새로 파싱합니다.")
    
    # 2. DB에 데이터가 없으면 RAG 기반 파싱
    # 디버깅 폴더 설정 (실제 분석을 수행할 때만 생성)
    from modules.utils.config import get_project_root
    project_root = get_project_root()
    debug_base_dir = project_root / debug_dir_name  # debug_dir_name 파라미터 사용
    debug_dir = debug_base_dir / pdf_name
    if debug_dir.exists():
        import shutil
        shutil.rmtree(debug_dir)
    debug_dir.mkdir(parents=True, exist_ok=True)
    # PDF를 이미지로 변환
    if progress_callback:
        progress_callback(0, 0, "🔄 PDF를 이미지로 변환 중...")
    
    from modules.core.extractors.pdf_processor import PdfImageConverter
    pdf_processor = PdfImageConverter(dpi=dpi)
    # 업로드: 전체 이미지 변환. 단일 페이지 분석: 해당 페이지만
    img_page_nums = None if (page_numbers and convert_all_images) else page_numbers
    images = pdf_processor.convert_pdf_to_images(pdf_path, page_numbers=img_page_nums)
    # 실제 페이지 번호 매핑. convert_all_images면 page_numbers 인덱스만 분석
    if page_numbers and convert_all_images:
        actual_page_numbers = page_numbers  # 분석 대상만, images는 전체라 인덱스 매핑 필요
        # OCR/LLM은 page_numbers 인덱스에 해당하는 이미지만 사용 (indices = [p-1 for p in page_numbers])
        analysis_indices = [p - 1 for p in page_numbers if 1 <= p <= len(images)]
    else:
        actual_page_numbers = page_numbers if page_numbers else [i + 1 for i in range(len(images))]
        analysis_indices = None  # 전체

    # 이미지 회전 보정 (프론트/디버깅에 보여줄 이미지도 바로잡기)
    try:
        from modules.utils.image_rotation_utils import (
            detect_and_correct_rotation,
            is_rotation_detection_available,
        )

        if is_rotation_detection_available():
            corrected_images: List[Image.Image] = []
            for idx, img in enumerate(images, start=1):
                try:
                    corrected, angle = detect_and_correct_rotation(img, return_angle=True)
                    if angle and angle != 0:
                        print(f"🔄 RAG용 페이지 이미지 회전 보정: 페이지 {idx} - {angle}도")
                    corrected_images.append(corrected)
                except Exception as rotate_error:
                    # 개별 페이지 회전 보정 실패 시 원본 유지
                    print(
                        f"⚠️ RAG용 페이지 이미지 회전 보정 실패 (페이지 {idx}): {rotate_error}"
                    )
                    corrected_images.append(img)
            images = corrected_images
        else:
            # 회전 감지 기능이 없으면 원본 그대로 사용
            pass
    except Exception as rotate_error:
        # 회전 보정 전체 실패해도 흐름은 유지
        print(f"⚠️ RAG용 페이지 이미지 회전 보정 전체 실패: {rotate_error}")

    pil_images = images
    print(f"PDF 변환 완료: {len(images)}개 페이지")
    if on_document_ready:
        try:
            on_document_ready(len(images), images)
        except Exception as e:
            print(f"⚠️ on_document_ready 콜백 실패: {e}")

    # 이미지 경로 리스트 초기화
    image_paths = [None] * len(images)
    
    # 디버깅: 분석 통계
    analysis_stats = {
        "total": len(images),
        "success": 0,
        "failed": 0,
        "empty_items": 0,
        "with_items": 0,
        "page_details": []
    }
    
    # 1단계: PDF에서 텍스트 추출. mail → Azure(표 복원), finet → PdfTextExtractor(excel)
    print(f"📝 1단계: PDF 텍스트 추출 시작 ({len(images)}개 페이지)")
    pdf_path_obj = Path(pdf_path)
    ocr_texts = [None] * len(images)
    ocr_words_list = [None] * len(images)
    # analysis_indices: convert_all_images 시 해당 인덱스만 OCR/LLM
    indices_to_process = analysis_indices if analysis_indices is not None else list(range(len(images)))

    use_azure_for_mail = upload_channel == "mail"
    if use_azure_for_mail:
        from modules.core.extractors.azure_extractor import get_azure_extractor
        from modules.utils.table_ocr_utils import raw_to_table_restored_text
        azure_extractor = get_azure_extractor(model_id="prebuilt-layout", enable_cache=False)
    else:
        text_extractor = PdfTextExtractor(upload_channel=upload_channel, form_number=form_type)

    def _azure_ocr_one_page(idx: int) -> tuple:
        """한 페이지 Azure OCR (병렬 워커용). 반환: (idx, ocr_text|None, words_data|None)"""
        pos = indices_to_process.index(idx) if idx in indices_to_process else idx
        page_num = actual_page_numbers[pos] if pos < len(actual_page_numbers) else idx + 1
        image = images[idx]
        try:
            os.makedirs(debug_dir, exist_ok=True)
            try:
                debug_image_path = os.path.join(debug_dir, f"page_{page_num}_original_image.png")
                image.save(debug_image_path, "PNG")
            except Exception:
                pass
            raw = azure_extractor.extract_from_pdf_page_raw(pdf_path_obj, page_num)
            if not raw:
                return (idx, None, None)
            ocr_text = raw_to_table_restored_text(raw)
            ocr_text = normalize_ocr_text(ocr_text or "", use_fullwidth=True)
            words = (raw.get("pages") or [{}])[0].get("words") or []
            words_data = {"words": words, "width": 1, "height": 1} if words else None
            return (idx, ocr_text if ocr_text.strip() else None, words_data)
        except Exception:
            return (idx, None, None)

    use_parallel_azure = use_azure_for_mail and ocr_parallel_workers > 1 and len(indices_to_process) > 1
    try:
        if use_parallel_azure:
            max_workers = min(ocr_parallel_workers, len(indices_to_process))
            print(f"🚀 1단계: Azure OCR 병렬 처리 (최대 {max_workers}개 스레드, {len(indices_to_process)}개 페이지)")
            completed = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_idx = {executor.submit(_azure_ocr_one_page, idx): idx for idx in indices_to_process}
                for future in as_completed(future_to_idx):
                    idx, ocr_text, words_data = future.result()
                    ocr_texts[idx] = ocr_text
                    ocr_words_list[idx] = words_data
                    completed += 1
                    if progress_callback:
                        progress_callback(idx + 1, len(images), f"🔍 페이지 {idx + 1}/{len(images)}: 텍스트 추출 완료")
                    n_items = len(ocr_text or "") if ocr_text else 0
                    w_count = len(words_data.get("words", [])) if words_data else 0
                    print(f"✅ 페이지 {idx + 1}/{len(images)} 완료 (길이: {n_items} 문자, 단어 {w_count}개) - 진행: {completed}/{len(images)}")
        else:
            for idx in indices_to_process:
                image = images[idx]
                page_num = actual_page_numbers[indices_to_process.index(idx)] if indices_to_process else idx + 1
                total_pages = len(indices_to_process)
                if progress_callback:
                    progress_callback(page_num, total_pages, f"🔍 페이지 {page_num}/{total_pages}: 텍스트 추출 중...")
                print(f"페이지 {page_num}/{total_pages} 텍스트 추출 중...", end="", flush=True)
                try:
                    if use_azure_for_mail:
                        idx, ocr_text, words_data = _azure_ocr_one_page(idx)
                        ocr_texts[idx] = ocr_text
                        ocr_words_list[idx] = words_data
                        w_count = len(words_data.get("words", [])) if words_data else 0
                        print(f" 완료 (길이: {len(ocr_text or '')} 문자, 단어 {w_count}개)")
                    else:
                        os.makedirs(debug_dir, exist_ok=True)
                        try:
                            debug_image_path = os.path.join(debug_dir, f"page_{page_num}_original_image.png")
                            image.save(debug_image_path, "PNG")
                        except Exception as debug_error:
                            print(f"  ⚠️ 원본 이미지 저장 실패: {debug_error}")
                        ocr_text = text_extractor.extract_text(pdf_path_obj, page_num)
                        if not ocr_text or len(ocr_text.strip()) == 0:
                            print(f"  ⚠️ 텍스트가 비어있습니다")
                            ocr_texts[idx] = None
                        else:
                            ocr_text = normalize_ocr_text(ocr_text, use_fullwidth=True)
                            ocr_texts[idx] = ocr_text
                            print(f" 완료 (길이: {len(ocr_text)} 문자)")
                except Exception as e:
                    print(f" 실패 - {e}")
                    ocr_texts[idx] = None
    finally:
        if not use_azure_for_mail:
            text_extractor.close_all()

    print(f"✅ 텍스트 추출 완료: {len([t for t in ocr_texts if t is not None])}/{len(images)}개 페이지 성공\n")
    
    # 2단계: RAG+LLM 병렬 처리 (OCR 텍스트가 있는 페이지만)
    stats_lock = Lock()
    
    def process_rag_llm(idx: int, ocr_text: str, ocr_words_data: Optional[Dict[str, Any]] = None) -> tuple[int, Dict[str, Any], Optional[str]]:
        """RAG+LLM 처리 (스레드에서 실행). page_numbers 사용 시 실제 페이지 번호 반영."""
        page_num = actual_page_numbers[idx] if idx < len(actual_page_numbers) else idx + 1
        total_pages = len(images)
        page_detail = {"page_num": page_num, "status": "unknown", "items_count": 0, "error": None}
        process_start_time = time.time()

        try:
            if progress_callback:
                progress_callback(page_num, total_pages, f"🔎 페이지 {page_num}/{total_pages}: RAG 검색 중...")

            print(f"페이지 {page_num}/{total_pages} RAG+LLM 처리 중...", end="", flush=True)

            def rag_progress_wrapper(msg: str):
                if progress_callback:
                    progress_callback(page_num, total_pages, f"🤖 페이지 {page_num}/{total_pages}: {msg}")

            page_json = extract_json_with_rag(
                ocr_text=ocr_text,
                question=question,
                model_name=openai_model,
                temperature=0,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
                progress_callback=rag_progress_wrapper if progress_callback else None,
                debug_dir=str(debug_dir),
                page_num=page_num,
                form_type=form_type,
                ocr_words=ocr_words_data["words"] if ocr_words_data else None,
                page_width=ocr_words_data["width"] if ocr_words_data else None,
                page_height=ocr_words_data["height"] if ocr_words_data else None,
                include_bbox=False,  # 최종 프롬프트에는 좌표 미포함. 좌표는 OCR 탭(그림) 전용.
            )
            rag_end_time = time.time()
            total_duration = rag_end_time - process_start_time
            
            # items 개수 확인 (page_json이 딕셔너리인지 확인)
            if not isinstance(page_json, dict):
                raise Exception(f"예상치 못한 응답 형식: {type(page_json)}. 딕셔너리가 아닙니다.")
            
            items = page_json.get("items", [])
            items_count = len(items) if items else 0
            page_detail["items_count"] = items_count
            
            if items_count > 0:
                page_detail["status"] = "success_with_items"
            else:
                page_detail["status"] = "success_empty"
            
            if progress_callback:
                progress_callback(page_num, total_pages, f"✅ 페이지 {page_num}/{total_pages} 완료 ({items_count}개 items)")
            
            print(f" 완료 ({items_count}개 items, 총 {total_duration:.2f}초)")
            
            return (idx, page_json, None)
            
        except Exception as e:
            error_msg = str(e)
            print(f" 실패 - {error_msg}")
            if progress_callback:
                progress_callback(page_num, total_pages, f"❌ 페이지 {page_num}/{total_pages} 실패: {error_msg}")
            
            page_detail["status"] = "failed"
            page_detail["error"] = error_msg
            
            # 실패한 페이지는 빈 결과로 반환
            error_result = {
                "items": [],
                "page_role": "detail",
                "error": error_msg
            }
            return (idx, error_result, error_msg)
        finally:
            # 통계 업데이트 (스레드 안전)
            with stats_lock:
                analysis_stats["page_details"].append(page_detail)
                if page_detail["status"] == "failed":
                    analysis_stats["failed"] += 1
                else:
                    analysis_stats["success"] += 1
                    if page_detail["items_count"] > 0:
                        analysis_stats["with_items"] += 1
                    else:
                        analysis_stats["empty_items"] += 1
    
    # RAG+LLM 병렬 처리
    page_results = {}
    valid_ocr_indices = [
        (idx, ocr_text, ocr_words_list[idx] if idx < len(ocr_words_list) else None)
        for idx, ocr_text in enumerate(ocr_texts)
        if ocr_text is not None
    ]
    
    if len(valid_ocr_indices) == 0:
        # OCR이 모두 실패한 경우
        print("⚠️ 모든 페이지 OCR 실패")
        page_jsons = [{
            "items": [],
            "page_role": "detail",
            "error": "OCR 실패"
        } for _ in range(len(images))]
        return page_jsons, image_paths, pil_images
    
    # 병렬 처리 여부 결정 (유효한 OCR 텍스트가 2개 이상일 때만 병렬 처리)
    use_parallel_rag = len(valid_ocr_indices) > 1
    
    if use_parallel_rag:
        # 병렬 처리: ThreadPoolExecutor 사용
        max_workers = min(rag_llm_workers, len(valid_ocr_indices))
        parallel_start_time = time.time()
        print(f"🚀 2단계: RAG+LLM 병렬 처리 시작 (최대 {max_workers}개 스레드, {len(valid_ocr_indices)}개 페이지)")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 유효한 OCR 텍스트에 대해 Future 제출
            future_to_idx = {
                executor.submit(process_rag_llm, idx, ocr_text, ocr_words_data): idx
                for idx, ocr_text, ocr_words_data in valid_ocr_indices
            }
            
            # 완료된 작업부터 처리
            completed_count = 0
            page_times = {}  # 각 페이지별 시작 시간 추적
            
            for future in as_completed(future_to_idx):
                idx, page_json, error = future.result()
                page_results[idx] = page_json
                completed_count += 1
                if on_page_complete:
                    page_num = actual_page_numbers[idx] if idx < len(actual_page_numbers) else idx + 1
                    pj = dict(page_json)
                    pj["page_number"] = page_num
                    if idx < len(ocr_texts) and ocr_texts[idx] and str(ocr_texts[idx]).strip():
                        pj["ocr_text"] = (ocr_texts[idx] or "").strip()
                    try:
                        on_page_complete(page_num, pj)
                    except Exception as cb_err:
                        print(f"⚠️ on_page_complete 콜백 실패 (페이지 {page_num}): {cb_err}")

                # 진행 상황 출력
                elapsed = time.time() - parallel_start_time
                if error:
                    print(f"❌ 페이지 {idx+1}/{len(images)} RAG+LLM 처리 실패: {error}")
                else:
                    items_count = len(page_json.get("items", []))
                    print(f"✅ 페이지 {idx+1}/{len(images)} 완료 ({items_count}개 items) - 전체 진행: {completed_count}/{len(valid_ocr_indices)}개, 경과 시간: {elapsed:.1f}초")
                
                if progress_callback:
                    progress_callback(completed_count, len(valid_ocr_indices), f"진행 중... ({completed_count}/{len(valid_ocr_indices)}개 페이지 완료, {elapsed:.1f}초 경과)")
        
        parallel_end_time = time.time()
        parallel_duration = parallel_end_time - parallel_start_time
        print(f"✅ 병렬 처리 완료: 총 {len(valid_ocr_indices)}개 페이지, 소요 시간: {parallel_duration:.2f}초 (평균 {parallel_duration/len(valid_ocr_indices):.2f}초/페이지)")
    else:
        idx, ocr_text, ocr_words_data = valid_ocr_indices[0]
        idx, page_json, error = process_rag_llm(idx, ocr_text, ocr_words_data)
        page_results[idx] = page_json
        if on_page_complete:
            page_num = actual_page_numbers[idx] if idx < len(actual_page_numbers) else idx + 1
            pj = dict(page_json)
            pj["page_number"] = page_num
            if idx < len(ocr_texts) and ocr_texts[idx] and str(ocr_texts[idx]).strip():
                pj["ocr_text"] = (ocr_texts[idx] or "").strip()
            try:
                on_page_complete(page_num, pj)
            except Exception as cb_err:
                print(f"⚠️ on_page_complete 콜백 실패 (페이지 {page_num}): {cb_err}")

    # OCR 실패한 페이지는 빈 결과로 추가 (분석 대상 인덱스만)
    for idx in indices_to_process:
        if idx not in page_results:
            page_results[idx] = {"items": [], "page_role": "detail", "error": "OCR 실패"}
    
    # convert_all_images(업로드): 분석한 페이지만 반환. 그 외: 전체 이미지 대비 결과
    if analysis_indices is not None:
        out_indices = indices_to_process
    else:
        out_indices = list(range(len(images)))
    
    # 최초 분석 시 OCR 결과를 각 페이지에 포함 (재분석 시 DB에서만 읽기 위해 저장용)
    page_jsons = []
    for i in out_indices:
        pj = dict(page_results.get(i, {"items": [], "page_role": "detail"}))
        pj["page_number"] = actual_page_numbers[out_indices.index(i)] if i in out_indices and out_indices.index(i) < len(actual_page_numbers) else (i + 1)
        if i < len(ocr_texts) and ocr_texts[i] and str(ocr_texts[i]).strip():
            pj["ocr_text"] = (ocr_texts[i] or "").strip()
        page_jsons.append(pj)
    
    # 후처리: 請求番号와 得意先가 비어있는 경우 앞 페이지에서 가져오기
    def fill_missing_management_id_and_customer(page_jsons: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        items가 있는데 請求番号와 得意先가 모두 비어있는 경우,
        바로 앞 페이지의 마지막 item에서 값을 가져와서 채워넣기
        
        Args:
            page_jsons: 페이지별 JSON 결과 리스트
            
        Returns:
            후처리된 페이지별 JSON 결과 리스트
        """
        last_management_id = None
        last_customer = None
        
        for page_idx, page_json in enumerate(page_jsons):
            items = page_json.get("items", [])
            
            # items가 비어있지 않은 경우에만 처리
            if items and len(items) > 0:
                # 현재 페이지의 모든 items를 확인하여 비어있는 경우 채워넣기
                for item in items:
                    current_mgmt_id = item.get("請求番号")
                    current_customer = item.get("得意先")
                    
                    # 請求番号와 得意先가 모두 비어있는 경우
                    if (current_mgmt_id is None or current_mgmt_id == "") and \
                       (current_customer is None or current_customer == ""):
                        # 앞 페이지의 마지막 값이 있으면 사용
                        if last_management_id is not None:
                            item["請求番号"] = last_management_id
                        if last_customer is not None:
                            item["得意先"] = last_customer
                
                # 현재 페이지의 마지막 item에서 請求番号와 得意先 추출
                # (null이 아닌 값만 업데이트)
                last_item = items[-1]
                if last_item.get("請求番号") is not None and last_item.get("請求番号") != "":
                    last_management_id = last_item.get("請求番号")
                if last_item.get("得意先") is not None and last_item.get("得意先") != "":
                    last_customer = last_item.get("得意先")
            else:
                # items가 비어있는 페이지는 last 값을 업데이트하지 않음
                # (앞 페이지의 값을 유지)
                pass
        
        return page_jsons
    
    # 후처리 실행
    page_jsons = fill_missing_management_id_and_customer(page_jsons)
    
    # 디버깅: 결과 확인
    try:
        print(f"\n📋 최종 결과 확인: {len(page_jsons)}개 페이지 결과 생성됨")
        for idx, result in enumerate(page_jsons):
            items_count = len(result.get("items", []))
            error = result.get("error")
            status = f"{items_count}개 items" if items_count > 0 else (f"오류: {error}" if error else "빈 결과")
            print(f"  - 페이지 {idx+1}: {status}")
        
        # 분석 통계 출력
        print(f"\n📊 RAG 분석 통계:")
        print(f"  - 전체 페이지: {analysis_stats['total']}개")
        print(f"  - 분석 성공: {analysis_stats['success']}개 (items 있음: {analysis_stats['with_items']}개, items 없음: {analysis_stats['empty_items']}개)")
        print(f"  - 분석 실패: {analysis_stats['failed']}개")
        print(f"\n📋 페이지별 상세:")
        for detail in analysis_stats.get("page_details", []):
            status_icon = "✅" if detail["status"].startswith("success") else "❌"
            items_info = f", {detail['items_count']}개 items" if detail["items_count"] > 0 else ""
            error_info = f", 오류: {detail['error']}" if detail.get("error") else ""
            print(f"  {status_icon} 페이지 {detail['page_num']}: {detail['status']}{items_info}{error_info}")
    except Exception as stats_error:
        print(f"\n⚠️ 통계 출력 중 오류 발생 (결과는 정상 반환): {stats_error}")
        import traceback
        print(f"  - 상세:\n{traceback.format_exc()}")
    
    # 반환값 검증
    if page_jsons is None:
        raise ValueError("page_jsons가 None입니다")
    if not isinstance(page_jsons, list):
        raise ValueError(f"page_jsons가 리스트가 아닙니다: {type(page_jsons)}")
    if len(page_jsons) == 0:
        raise ValueError("page_jsons가 비어있습니다")
    
    print(f"\n✅ extract_pages_with_rag 반환 준비 완료: {len(page_jsons)}개 페이지, {len(image_paths) if image_paths else 0}개 이미지 경로, {len(pil_images) if pil_images else 0}개 PIL 이미지")
    
    return page_jsons, image_paths, pil_images


def extract_single_page_from_image_path(
    image_path: str,
    page_number: int,
    pdf_filename: str,
    form_type: Optional[str] = None,
    openai_model: Optional[str] = None,
    question: Optional[str] = None,
    top_k: Optional[int] = None,
    similarity_threshold: Optional[float] = None,
    debug_dir_name: str = "debug2",
) -> Dict[str, Any]:
    """
    DB에 저장된 페이지 이미지(static) 경로로 단일 페이지만 분석 (OCR + RAG + LLM).
    PDF 없이 검토 탭 재분석/자동분석 시 사용.
    """
    from modules.utils.config import rag_config, get_project_root
    from modules.core.extractors.azure_extractor import get_azure_extractor
    from modules.utils.table_ocr_utils import raw_to_table_restored_text

    path = Path(image_path)
    if not path.is_absolute():
        path = get_project_root() / image_path
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    openai_model = openai_model or rag_config.openai_model
    question = question or rag_config.question
    top_k = top_k if top_k is not None else rag_config.top_k
    similarity_threshold = similarity_threshold if similarity_threshold is not None else rag_config.similarity_threshold

    debug_base = get_project_root() / debug_dir_name / Path(pdf_filename).stem
    debug_base.mkdir(parents=True, exist_ok=True)

    azure_extractor = get_azure_extractor(model_id="prebuilt-layout", enable_cache=False)
    raw = azure_extractor.extract_from_image_raw(image_path=path)
    if not raw:
        raise RuntimeError("OCR returned no result")
    ocr_text = raw_to_table_restored_text(raw)
    ocr_text = normalize_ocr_text(ocr_text or "", use_fullwidth=True)
    if not ocr_text or not ocr_text.strip():
        raise RuntimeError("OCR text is empty")
    words = (raw.get("pages") or [{}])[0].get("words") or []
    ocr_words_data = {"words": words, "width": 1, "height": 1} if words else None

    page_json = extract_json_with_rag(
        ocr_text=ocr_text,
        question=question,
        model_name=openai_model,
        temperature=0,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        debug_dir=str(debug_base),
        page_num=page_number,
        form_type=form_type,
        ocr_words=ocr_words_data["words"] if ocr_words_data else None,
        page_width=ocr_words_data.get("width") if ocr_words_data else None,
        page_height=ocr_words_data.get("height") if ocr_words_data else None,
        include_bbox=False,
    )
    if not isinstance(page_json, dict):
        raise ValueError(f"Unexpected response type: {type(page_json)}")
    page_json["page_number"] = page_number
    return page_json

