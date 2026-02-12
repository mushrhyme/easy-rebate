"""
PDF 관련 유틸리티 함수
"""

import os
from pathlib import Path
from typing import Optional, List, Dict
import fitz  # PyMuPDF
from modules.utils.session_manager import SessionManager


class PdfTextExtractor:
    """
    PDF 텍스트 추출 클래스 (캐싱 지원)
    
    여러 페이지를 처리할 때 성능 향상을 위해 문서를 캐싱합니다.
    """
    
    def __init__(self, method: Optional[str] = None, upload_channel: Optional[str] = None, form_number: Optional[str] = None):
        """
        PDF 문서 캐시 초기화
        
        Args:
            method: 텍스트 추출 방법 ("pymupdf", "excel", "upstage"). "excel"/"pymupdf"는 PyMuPDF 사용. None이면 설정에서 가져옴
            upload_channel: 업로드 채널 (finet | mail). 우선 사용
            form_number: 양식지 번호 (예: "01", "02"). 하위 호환, upload_channel이 없을 때만 사용
        """
        self._pdf_cache: Dict[Path, fitz.Document] = {}
        self.method = method
        self.upload_channel = upload_channel
        self.form_number = form_number
    
    def extract_text(self, pdf_path: Path, page_num: int) -> str:
        """
        PDF에서 특정 페이지의 텍스트를 추출합니다.
        
        Args:
            pdf_path: PDF 파일 경로
            page_num: 페이지 번호 (1부터 시작)
            
        Returns:
            추출된 텍스트 (없으면 빈 문자열)
        """
        # 설정에서 추출 방법 가져오기 (upload_channel 기반)
        method = self.method
        if method is None:
            from modules.utils.config import get_extraction_method_for_upload_channel
            
            # upload_channel 결정 (우선순위: 설정된 값 > DB 조회 > 경로에서 추출)
            upload_channel = self.upload_channel
            if not upload_channel:
                # DB에서 문서 정보 조회 시도
                try:
                    from database.registry import get_db
                    pdf_filename = f"{pdf_path.stem}.pdf"
                    doc = get_db().get_document(pdf_filename)
                    if doc and doc.get('upload_channel'):
                        upload_channel = doc['upload_channel']
                except Exception:
                    pass
            
            # upload_channel에 따라 변환 방식 결정
            if upload_channel:
                method = get_extraction_method_for_upload_channel(upload_channel)
            else:
                method = "upstage"  # 기본값
        
        # Upstage OCR 방법 사용
        if method == "upstage":
            try:
                from modules.core.extractors.upstage_extractor import get_upstage_extractor
                extractor = get_upstage_extractor()
                text = extractor.extract_from_pdf_page(pdf_path, page_num)
                if text:
                    return text
                # Upstage OCR 실패 시 PyMuPDF로 폴백
                print(f"⚠️ Upstage OCR 실패, PyMuPDF로 폴백 ({pdf_path}, 페이지 {page_num})")
            except Exception as e:
                print(f"⚠️ Upstage OCR 오류, PyMuPDF로 폴백 ({pdf_path}, 페이지 {page_num}): {e}")
        
        # "excel" / "pymupdf": PyMuPDF로 전체 텍스트 추출 (표·줄글 혼합 시 순서 보장)
        # 기본 PyMuPDF 방법 사용
        try:
            if not pdf_path.exists():
                return ""
            
            # 캐시에서 문서 가져오기 또는 로드
            if pdf_path not in self._pdf_cache:
                self._pdf_cache[pdf_path] = fitz.open(pdf_path)
            
            doc = self._pdf_cache[pdf_path]
            if page_num < 1 or page_num > doc.page_count:
                return ""
            
            page = doc.load_page(page_num - 1)
            # dict 형태로 추출 후 y 좌표로 정렬하여 순서 보장
            text_dicts = page.get_text("dict")
            if text_dicts and "blocks" in text_dicts:
                # 각 블록의 텍스트를 y 좌표 기준으로 정렬
                blocks = []
                for block in text_dicts["blocks"]:
                    if "lines" in block:
                        for line in block["lines"]:
                            if "spans" in line:
                                for span in line["spans"]:
                                    if "text" in span and "bbox" in span:
                                        blocks.append((span["bbox"][1], span["text"]))  # y 좌표, 텍스트
                # y 좌표로 정렬
                blocks.sort(key=lambda x: x[0])
                text = "\n".join([block[1] for block in blocks])
            else:
                # 폴백: 기본 get_text 사용
                text = page.get_text()
            return text.strip() if text else ""
        except Exception as e:
            print(f"⚠️ PDF 텍스트 추출 실패 ({pdf_path}, 페이지 {page_num}): {e}")
            return ""
    
    def close_all(self):
        """캐시된 모든 PDF 문서 닫기"""
        for doc in self._pdf_cache.values():
            try:
                doc.close()
            except:
                pass
        self._pdf_cache.clear()
    
    def __del__(self):
        """소멸자: 모든 문서 닫기"""
        self.close_all()


def extract_form_number_from_path(pdf_path: Path) -> Optional[str]:
    """
    PDF 경로에서 양식지 번호를 추출합니다.
    
    Args:
        pdf_path: PDF 파일 경로
    
    Returns:
        양식지 번호 (예: "01", "02") 또는 None
    """
    if isinstance(pdf_path, str):
        pdf_path = Path(pdf_path)
    
    # 경로를 정규화
    pdf_path = pdf_path.resolve()
    
    # img/XX/... 패턴 찾기
    parts = pdf_path.parts
    try:
        img_idx = parts.index("img")
        if img_idx + 1 < len(parts):
            form_folder = parts[img_idx + 1]
            # 숫자 2자리 형식인지 확인 (01, 02, 03 등)
            if form_folder.isdigit() and len(form_folder) == 2:
                return form_folder
    except ValueError:
        pass
    
    return None


def extract_text_from_pdf_page(
    pdf_path: Path,
    page_num: int,
    method: Optional[str] = None,  # None이면 upload_channel에 따라 자동 결정
    upload_channel: Optional[str] = None,  # 업로드 채널 (finet | mail). 우선 사용
    form_number: Optional[str] = None  # 양식지 번호 (하위 호환, upload_channel이 없을 때만 사용)
) -> str:
    """
    PDF에서 특정 페이지의 텍스트를 추출합니다.
    
    Args:
        pdf_path: PDF 파일 경로 (Path 객체 또는 문자열)
        page_num: 페이지 번호 (1부터 시작)
        method: 텍스트 추출 방법 ("pymupdf" 또는 "excel", 둘 다 PyMuPDF 사용). None이면 upload_channel에 따라 자동 결정
        upload_channel: 업로드 채널 (finet | mail). 우선 사용
        form_number: 양식지 번호 (예: "01", "02"). 하위 호환, upload_channel이 없을 때만 사용
        
    Returns:
        추출된 텍스트 (없으면 빈 문자열)
        
    Examples:
        # 단일 페이지
        text = extract_text_from_pdf_page(Path("doc.pdf"), 1)
        
        # 여러 페이지 (캐싱 사용)
        extractor = PdfTextExtractor(upload_channel="finet")
        for page in range(1, 10):
            text = extractor.extract_text(Path("doc.pdf"), page)
        extractor.close_all()
    """
    # Path 객체로 변환
    if isinstance(pdf_path, str):
        pdf_path = Path(pdf_path)
    
    # 설정에서 추출 방법 가져오기 (upload_channel 기반)
    if method is None:
        from modules.utils.config import get_extraction_method_for_upload_channel
        
        # upload_channel 결정 (우선순위: 파라미터 > DB 조회 > 경로에서 추출)
        if not upload_channel:
            # DB에서 문서 정보 조회 시도
            try:
                from database.registry import get_db
                pdf_filename = f"{pdf_path.stem}.pdf"
                doc = get_db().get_document(pdf_filename)
                if doc and doc.get('upload_channel'):
                    upload_channel = doc['upload_channel']
            except Exception:
                pass
        
        # upload_channel에 따라 변환 방식 결정
        if upload_channel:
            method = get_extraction_method_for_upload_channel(upload_channel)
        else:
            method = "upstage"  # 기본값
        
        print(f"📝 [PDF 추출] upload_channel: {upload_channel}, 방법: {method}")
    # Upstage OCR 방법 사용
    if method == "upstage":
        try:
            from modules.core.extractors.upstage_extractor import get_upstage_extractor
            extractor = get_upstage_extractor()
            text = extractor.extract_from_pdf_page(pdf_path, page_num)
            if text:
                return text
            # Upstage OCR 실패 시 PyMuPDF로 폴백
            print(f"⚠️ Upstage OCR 실패, PyMuPDF로 폴백 ({pdf_path}, 페이지 {page_num})")
        except Exception as e:
            print(f"⚠️ Upstage OCR 오류, PyMuPDF로 폴백 ({pdf_path}, 페이지 {page_num}): {e}")
            import traceback
            traceback.print_exc()
    
    # "excel" / "pymupdf": PyMuPDF로 전체 텍스트 추출 (표·줄글 혼합 시 순서 보장)
    # 기본 PyMuPDF 방법 사용
    try:
        if not pdf_path.exists():
            return ""
        
        doc = fitz.open(pdf_path)
        try:
            if page_num < 1 or page_num > doc.page_count:
                return ""
            
            page = doc.load_page(page_num - 1)
            # dict 형태로 추출 후 y 좌표로 정렬하여 순서 보장
            text_dicts = page.get_text("dict")
            if text_dicts and "blocks" in text_dicts:
                # 각 블록의 텍스트를 y 좌표 기준으로 정렬
                blocks = []
                for block in text_dicts["blocks"]:
                    if "lines" in block:
                        for line in block["lines"]:
                            if "spans" in line:
                                for span in line["spans"]:
                                    if "text" in span and "bbox" in span:
                                        blocks.append((span["bbox"][1], span["text"]))  # y 좌표, 텍스트
                # y 좌표로 정렬
                blocks.sort(key=lambda x: x[0])
                text = "\n".join([block[1] for block in blocks])
            else:
                # 폴백: 기본 get_text 사용
                text = page.get_text()
            return text.strip() if text else ""
        finally:
            doc.close()
    except Exception as e:
        print(f"⚠️ PDF 텍스트 추출 실패 ({pdf_path}, 페이지 {page_num}): {e}")
        return ""


def find_pdf_path(pdf_name: str) -> Optional[str]:
    """
    PDF 파일 경로 찾기 (세션 디렉토리만 확인)
    
    Args:
        pdf_name: PDF 파일명 (확장자 제외)
        
    Returns:
        PDF 파일 경로 또는 None
    """
    # 세션 디렉토리 확인
    pdfs_dir = SessionManager.get_pdfs_dir()
    pdf_path = os.path.join(pdfs_dir, f"{pdf_name}.pdf")
    
    if os.path.exists(pdf_path):
        return pdf_path
    
    return None



