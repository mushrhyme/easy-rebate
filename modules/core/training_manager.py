"""
학습 데이터 자동 저장 관리 모듈

PDF 분석 완료 후 자동으로 img 폴더에 저장하는 기능을 제공합니다.
구조: img/{form_type}/{year}-{month}/{pdf_name}/
"""
import os
import shutil
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from io import BytesIO
import fitz  # PyMuPDF
from PIL import Image

from modules.utils.config import get_project_root
from database.registry import get_db


class TrainingManager:
    """
    학습 데이터 자동 저장 관리 클래스
    
    PDF 분석 완료 후 자동으로 img 폴더에 저장합니다.
    """
    
    @staticmethod
    def get_training_dir(form_type: str, year: Optional[int] = None, month: Optional[int] = None) -> Path:
        """
        학습 데이터 저장 디렉토리 경로 반환
        
        Args:
            form_type: 양식지 번호 (01, 02, 03, 04, 05)
            year: 연도 (None이면 현재 연도)
            month: 월 (None이면 현재 월)
        
        Returns:
            img/{form_type}/{year}-{month}/ 경로
        """
        project_root = get_project_root()
        img_dir = project_root / "img"
        
        # form_type 폴더
        form_dir = img_dir / form_type
        
        # 날짜 폴더명 생성
        if year and month:
            date_folder = f"{year}-{month:02d}"  # 예: 2025-01
        else:
            from datetime import datetime
            now = datetime.now()
            date_folder = f"{now.year}-{now.month:02d}"
        
        return form_dir / date_folder
    
    @staticmethod
    def save_to_training_folder(
        pdf_name: str,
        pdf_path: Optional[Path] = None,
        form_type: Optional[str] = None,
        data_year: Optional[int] = None,
        data_month: Optional[int] = None,
        pdf_bytes: Optional[bytes] = None
    ) -> Tuple[bool, str]:
        """
        PDF 분석 결과를 img 폴더에 자동 저장
        
        Args:
            pdf_name: PDF 파일명 (확장자 제외)
            pdf_path: PDF 파일 경로 (pdf_bytes가 없을 때 사용)
            form_type: 양식지 번호 (None이면 DB에서 조회)
            data_year: 연도 (None이면 DB에서 조회 또는 현재 연도)
            data_month: 월 (None이면 DB에서 조회 또는 현재 월)
            pdf_bytes: PDF 파일 바이트 데이터 (우선 사용)
        
        Returns:
            (성공 여부, 메시지)
        """
        try:
            # 1. DB에서 정보 조회 (form_type, data_year, data_month)
            db_manager = get_db()
            pdf_filename = f"{pdf_name}.pdf"
            
            doc = db_manager.get_document(pdf_filename)
            if not doc:
                return False, f"DB에서 문서를 찾을 수 없습니다: {pdf_name}"
            
            # form_type이 없으면 DB에서 가져오기
            if not form_type:
                form_type = doc.get('form_type')
                if not form_type:
                    return False, f"양식지 번호를 찾을 수 없습니다: {pdf_name}"
            
            # data_year, data_month가 없으면 DB에서 가져오기
            if not data_year or not data_month:
                data_year = doc.get('data_year') or data_year
                data_month = doc.get('data_month') or data_month
                
                # 여전히 없으면 현재 날짜 사용
                if not data_year or not data_month:
                    from datetime import datetime
                    now = datetime.now()
                    data_year = data_year or now.year
                    data_month = data_month or now.month
            
            # 2. 저장 디렉토리 생성
            training_dir = TrainingManager.get_training_dir(form_type, data_year, data_month)
            pdf_folder = training_dir / pdf_name
            pdf_folder.mkdir(parents=True, exist_ok=True)
            
            print(f"📁 학습 데이터 저장 경로: {pdf_folder}")
            print(f"   - 양식지: {form_type}")
            print(f"   - 날짜: {data_year}-{data_month:02d}")
            
            # 3. PDF 파일 저장
            dest_pdf_path = pdf_folder / f"{pdf_name}.pdf"
            
            if pdf_bytes:
                # 바이트 데이터에서 직접 저장
                with open(dest_pdf_path, 'wb') as f:
                    f.write(pdf_bytes)
            elif pdf_path and pdf_path.exists():
                # 파일 경로에서 복사
                shutil.copy2(str(pdf_path), str(dest_pdf_path))
            else:
                # 세션 디렉토리에서 찾기 시도
                from modules.utils.pdf_utils import find_pdf_path
                session_pdf_path = find_pdf_path(pdf_name)
                if session_pdf_path and os.path.exists(session_pdf_path):
                    shutil.copy2(session_pdf_path, str(dest_pdf_path))
                else:
                    return False, f"PDF 파일을 찾을 수 없습니다: {pdf_name}"
            
            # 4. DB에서 페이지 결과 가져오기
            page_results = db_manager.get_page_results(pdf_filename=pdf_filename)
            if not page_results:
                return False, f"분석 결과를 찾을 수 없습니다: {pdf_name}"
            
            # 5. PDF를 이미지로 변환하여 Page{page_num}.png 형식으로 저장
            try:
                doc = fitz.open(str(dest_pdf_path))
                total_pages = doc.page_count
                
                for page_idx in range(total_pages):
                    page = doc.load_page(page_idx)
                    pix = page.get_pixmap(dpi=300)
                    img_bytes = pix.tobytes("png")
                    image = Image.open(BytesIO(img_bytes)).convert("RGB")
                    page_num = page_idx + 1
                    
                    image_path = pdf_folder / f"Page{page_num}.png"
                    image.save(image_path, "PNG", dpi=(300, 300), optimize=True)
                
                doc.close()
            except Exception as e:
                return False, f"PDF 이미지 변환 실패: {str(e)}"
            
            # 6. 각 페이지의 결과를 Page{page_num}_answer.json 형식으로 저장
            saved_count = 0
            for page_result in page_results:
                page_num = page_result.get('page_number')
                if not page_num:
                    continue
                
                # answer.json 파일 경로 (기본 버전: v1)
                answer_json_path = pdf_folder / f"Page{page_num}_answer.json"
                
                # 전체 페이지 결과 저장 (document_meta, party, payment, totals, items 등)
                # page_number는 파일명에 반영되므로 제외
                answer_data = {
                    k: v for k, v in page_result.items()
                    if k != 'page_number'
                }
                if not answer_data:
                    answer_data = {
                        'page_role': page_result.get('page_role', 'detail'),
                        'items': page_result.get('items', [])
                    }
                
                # 페이지 데이터를 JSON으로 저장
                with open(answer_json_path, 'w', encoding='utf-8') as f:
                    json.dump(answer_data, f, ensure_ascii=False, indent=2)
                
                saved_count += 1
            
            return True, f"✅ 학습 데이터 저장 완료! {saved_count}개 페이지 저장됨 (경로: {pdf_folder.relative_to(get_project_root())})"
            
        except Exception as e:
            import traceback
            error_msg = f"❌ 오류 발생: {str(e)}\n{traceback.format_exc()}"
            return False, error_msg
