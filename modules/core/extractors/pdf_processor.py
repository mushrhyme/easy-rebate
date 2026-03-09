"""
PDF를 이미지로 변환하는 공통 모듈

PDF 파일을 이미지로 변환하고 저장하는 기능을 제공합니다.
PyMuPDF (fitz)를 사용하여 PDF를 이미지로 변환합니다.
여러 extractor 모듈에서 공통으로 사용됩니다.
"""

import os
from typing import List, Optional
import fitz  # PyMuPDF
from PIL import Image
from io import BytesIO

# 공통 설정 로드
from modules.utils.config import load_env
load_env()


class PdfImageConverter:
    """PDF를 이미지로 변환하는 클래스 (PyMuPDF 사용)"""
    
    def __init__(self, dpi: int = 200):
        """
        Args:
            dpi: PDF 변환 시 해상도 (기본값: 200)
        """
        self.dpi = dpi
        # PyMuPDF의 zoom factor 계산 (DPI를 기반으로)
        # 72 DPI가 기본값이므로, 200 DPI는 200/72 ≈ 2.78배
        self.zoom = dpi / 72.0
    
    def convert_pdf_to_images(self, pdf_path: str, page_numbers: Optional[List[int]] = None) -> List[Image.Image]:
        """
        PDF 파일을 이미지 리스트로 변환 (PyMuPDF 사용)

        Args:
            pdf_path: PDF 파일 경로
            page_numbers: 지정 시 해당 페이지만 변환 (1-based). None이면 전체.

        Returns:
            PIL Image 객체 리스트. page_numbers 지정 시 해당 페이지만, 순서 유지.
        """
        images = []
        doc = fitz.open(pdf_path)
        try:
            indices = list(range(len(doc))) if page_numbers is None else [p - 1 for p in page_numbers if 1 <= p <= len(doc)]
            for page_idx in indices:
                page = doc[page_idx]
                mat = fitz.Matrix(self.zoom, self.zoom)
                pix = page.get_pixmap(matrix=mat)
                img_data = pix.tobytes("png")
                img = Image.open(BytesIO(img_data))
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                images.append(img)
        finally:
            doc.close()
        return images
    
    def save_images(self, images: List[Image.Image], output_dir: str, prefix: str = "page") -> List[str]:
        """
        이미지들을 파일로 저장
        
        Args:
            images: PIL Image 객체 리스트
            output_dir: 저장할 디렉토리 경로
            prefix: 파일명 접두사 (기본값: "page")
            
        Returns:
            저장된 파일 경로 리스트
            예: ["/path/to/page_1.jpg", "/path/to/page_2.jpg", ...]
        """
        os.makedirs(output_dir, exist_ok=True)  # 디렉토리 생성
        saved_paths = []
        
        for idx, img in enumerate(images):
            filename = f"{prefix}_{idx+1}.jpg"  # JPEG 형식으로 저장
            filepath = os.path.join(output_dir, filename)
            try:
                # 이미지가 로드되지 않은 경우 강제로 로드
                img.load()
                # JPEG로 저장 (품질 95로 고품질 유지)
                # RGB 모드로 변환 (JPEG는 RGB만 지원)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img.save(filepath, "JPEG", quality=95, optimize=True)
                # 저장된 파일이 제대로 생성되었는지 확인
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    saved_paths.append(filepath)
                else:
                    print(f"⚠️ 이미지 저장 실패: {filepath} (파일 크기가 0입니다)")
            except Exception as e:
                print(f"⚠️ 이미지 저장 중 오류 발생 ({filepath}): {e}")
                # 오류가 발생해도 계속 진행
                if os.path.exists(filepath):
                    saved_paths.append(filepath)
        
        return saved_paths

