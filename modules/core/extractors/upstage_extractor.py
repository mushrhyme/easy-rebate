"""
Upstage OCR Extractor 모듈

Upstage OCR API를 사용하여 이미지나 PDF 페이지에서 텍스트를 추출합니다.
결과를 파일로 캐싱하여 API 호출을 최소화합니다.
"""

import os
import json
import time
import requests
from pathlib import Path
from typing import Optional
import fitz  # PyMuPDF
from PIL import Image
from io import BytesIO

# .env 파일 로드
from modules.utils.config import load_env
load_env()


class UpstageExtractor:
    """
    Upstage OCR API를 사용한 텍스트 추출 클래스
    
    이미지나 PDF 페이지에서 텍스트를 추출하고, 결과를 캐싱합니다.
    """
    
    def __init__(self, api_key: Optional[str] = None, enable_cache: bool = True):
        """
        Args:
            api_key: Upstage API 키 (None이면 환경변수에서 가져옴)
            enable_cache: 캐시 사용 여부 (기본값: True)
        """
        self.api_key = api_key or os.getenv("UPSTAGE_API_KEY")
        self.enable_cache = enable_cache
        self.api_url = "https://api.upstage.ai/v1/document-digitization"
    
    def get_cache_path(self, pdf_path: Path, page_num: int) -> Path:
        """
        Upstage OCR 결과 캐시 파일 경로를 반환합니다.
        
        Args:
            pdf_path: PDF 파일 경로
            page_num: 페이지 번호 (1부터 시작)
        
        Returns:
            캐시 파일 경로
        """
        cache_dir = pdf_path.parent
        cache_filename = f"{pdf_path.stem}_Page{page_num}_upstage_ocr.json"
        return cache_dir / cache_filename
    
    def load_cache(self, cache_path: Path) -> Optional[str]:
        """
        저장된 Upstage OCR 결과를 로드합니다.
        
        Args:
            cache_path: 캐시 파일 경로
        
        Returns:
            OCR 텍스트 또는 None
        """
        if not self.enable_cache or not cache_path.exists():
            return None
        
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
                return cache_data.get("text", None)
        except Exception as e:
            print(f"⚠️ 캐시 파일 로드 실패 ({cache_path}): {e}")
            return None
    
    def save_cache(self, cache_path: Path, text: str):
        """
        Upstage OCR 결과를 캐시 파일로 저장합니다.
        
        Args:
            cache_path: 캐시 파일 경로
            text: OCR 텍스트
        """
        if not self.enable_cache:
            return
        
        try:
            cache_data = {
                "text": text,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 캐시 파일 저장 실패 ({cache_path}): {e}")
    
    def extract_from_image(self, image_path: Path, cache_path: Optional[Path] = None) -> Optional[str]:
        """
        Upstage OCR API를 사용하여 이미지에서 텍스트를 추출합니다.
        캐시 파일이 있으면 API 호출 없이 캐시를 사용합니다.
        
        Args:
            image_path: 이미지 파일 경로
            cache_path: 캐시 파일 경로 (None이면 자동 생성)
        
        Returns:
            추출된 텍스트 또는 None
        """
        # 캐시 파일 경로가 없으면 자동 생성
        if cache_path is None:
            cache_path = image_path.parent / f"{image_path.stem}_upstage_ocr.json"
        
        # 캐시 확인
        cached_text = self.load_cache(cache_path)
        if cached_text:
            print(f"✅ Upstage OCR 캐시 사용: {cache_path}")
            return cached_text
        
        # Upstage API 키 확인
        if not self.api_key:
            print("⚠️ UPSTAGE_API_KEY 환경 변수가 설정되지 않았습니다.")
            return None
        
        # 이미지 파일 확인
        if not image_path.exists():
            print(f"⚠️ 이미지 파일을 찾을 수 없습니다: {image_path}")
            return None
        
        try:
            # Upstage OCR API 호출
            print(f"🔍 Upstage OCR API 호출 중: {image_path}")
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            # 파일 열기 (requests가 파일을 닫아주므로 with 문 밖에서 열기)
            files = {"document": open(image_path, "rb")}
            data = {"model": "ocr"}
            response = requests.post(self.api_url, headers=headers, files=files, data=data)
            
            # 파일 닫기
            files["document"].close()
            
            # 응답 확인
            response.raise_for_status()
            result = response.json()
            
            # 텍스트 추출 (응답 구조에 따라 조정 필요)
            text = None
            if isinstance(result, dict):
                # 응답 구조에 따라 텍스트 추출
                # 일반적으로 "text" 또는 "result" 필드에 텍스트가 있음
                text = result.get("text") or result.get("result") or result.get("content")
                # 만약 다른 구조라면 전체 응답을 문자열로 변환
                if not text:
                    # pages나 다른 구조일 수 있음
                    if "pages" in result:
                        # 여러 페이지가 있는 경우 모든 텍스트 합치기
                        pages = result.get("pages", [])
                        texts = []
                        for page in pages:
                            if isinstance(page, dict):
                                page_text = page.get("text") or page.get("content")
                                if page_text:
                                    texts.append(page_text)
                        text = "\n".join(texts) if texts else None
                    else:
                        # 전체 JSON을 문자열로 변환 (디버깅용)
                        text = json.dumps(result, ensure_ascii=False)
            
            if text:
                # 캐시에 저장
                self.save_cache(cache_path, text)
                print(f"✅ Upstage OCR 완료 및 캐시 저장: {cache_path}")
                return text
            else:
                print(f"⚠️ Upstage OCR 결과가 비어있습니다: {image_path}")
                print(f"   응답: {result}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Upstage OCR API 호출 실패 ({image_path}): {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    print(f"   오류 상세: {error_detail}")
                except:
                    print(f"   응답 상태 코드: {e.response.status_code}")
            return None
        except Exception as e:
            print(f"⚠️ Upstage OCR 오류 ({image_path}): {e}")
            import traceback
            traceback.print_exc()
            return None

    def extract_from_image_raw(self, image_path: Optional[Path] = None, image_bytes: Optional[bytes] = None) -> Optional[dict]:
        """
        Upstage OCR API를 호출하여 이미지에서 텍스트를 추출하고,
        **전체 API 응답(bbox 포함)** 을 그대로 반환합니다. 캐시 미사용.
        테스트/하이라이트 UI용.

        Args:
            image_path: 이미지 파일 경로 (image_bytes가 없을 때 사용)
            image_bytes: 이미지 바이트 (업로드 파일 등)

        Returns:
            API 응답 dict (pages[].words[].boundingBox 등) 또는 None
        """
        if not self.api_key:
            print("⚠️ UPSTAGE_API_KEY 환경 변수가 설정되지 않았습니다.")
            return None

        file_to_close = None
        try:
            if image_bytes is not None:
                files = {"document": ("image.png", image_bytes, "image/png")}
            elif image_path and image_path.exists():
                file_to_close = open(image_path, "rb")
                files = {"document": file_to_close}
            else:
                print("⚠️ extract_from_image_raw: image_path 또는 image_bytes 필요")
                return None

            headers = {"Authorization": f"Bearer {self.api_key}"}
            data = {"model": "ocr"}
            response = requests.post(self.api_url, headers=headers, files=files, data=data)
            if file_to_close:
                file_to_close.close()
                file_to_close = None

            response.raise_for_status()
            result = response.json()
            if isinstance(result, dict) and ("pages" in result or "text" in result):
                return result
            print(f"⚠️ Upstage OCR 응답 형식 예상 외: {type(result)}")
            return result if isinstance(result, dict) else None
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Upstage OCR API 호출 실패: {e}")
            return None
        except Exception as e:
            if file_to_close:
                try:
                    file_to_close.close()
                except Exception:
                    pass
            print(f"⚠️ Upstage OCR 오류: {e}")
            import traceback
            traceback.print_exc()
            return None

    def extract_from_pdf_page(self, pdf_path: Path, page_num: int, dpi: int = 200) -> Optional[str]:
        """
        PDF 페이지를 이미지로 변환한 후 Upstage OCR로 텍스트를 추출합니다.
        
        Args:
            pdf_path: PDF 파일 경로
            page_num: 페이지 번호 (1부터 시작)
            dpi: PDF 변환 해상도 (기본값: 200)
        
        Returns:
            추출된 텍스트 또는 None
        """
        try:
            # PDF에서 페이지를 이미지로 변환
            doc = fitz.open(pdf_path)
            if page_num < 1 or page_num > doc.page_count:
                doc.close()
                return None
            
            page = doc.load_page(page_num - 1)
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")
            doc.close()

            # 1) 필요 시 이미지 회전 감지 및 보정
            try:
                from modules.utils.image_rotation_utils import (
                    detect_and_correct_rotation,
                    is_rotation_detection_available,
                )

                if is_rotation_detection_available():
                    image = Image.open(BytesIO(img_bytes))
                    corrected_image, angle = detect_and_correct_rotation(
                        image, return_angle=True
                    )

                    # 회전이 실제로 발생한 경우에만 이미지 교체
                    if angle and angle != 0:
                        print(
                            f"🔄 Upstage OCR용 이미지 회전 보정: 페이지 {page_num} - {angle}도"
                        )
                        buf = BytesIO()
                        # PNG로 다시 인코딩
                        if corrected_image.mode != "RGB":
                            corrected_image = corrected_image.convert("RGB")
                        corrected_image.save(buf, format="PNG")
                        img_bytes = buf.getvalue()
                else:
                    # 회전 감지 기능이 사용 불가한 경우는 그냥 원본 사용
                    pass
            except Exception as rotate_error:
                # 회전 보정에 실패해도 전체 OCR 흐름은 유지
                print(
                    f"⚠️ Upstage OCR용 이미지 회전 보정 실패 "
                    f"({pdf_path}, 페이지 {page_num}): {rotate_error}"
                )

            # 2) 임시 이미지 파일 생성
            temp_image_path = pdf_path.parent / f"{pdf_path.stem}_Page{page_num}_temp.png"
            with open(temp_image_path, "wb") as f:
                f.write(img_bytes)
            
            # 캐시 파일 경로
            cache_path = self.get_cache_path(pdf_path, page_num)
            
            # Upstage OCR 호출
            text = self.extract_from_image(temp_image_path, cache_path)
            
            # 임시 이미지 파일 삭제
            try:
                if temp_image_path.exists():
                    temp_image_path.unlink()
            except:
                pass
            
            return text
            
        except Exception as e:
            print(f"⚠️ PDF 페이지 이미지 변환 실패 ({pdf_path}, 페이지 {page_num}): {e}")
            return None

    def extract_from_pdf_page_raw(self, pdf_path: Path, page_num: int, dpi: int = 200) -> Optional[dict]:
        """
        PDF 페이지를 이미지로 변환한 후 Upstage OCR을 호출하고,
        **전체 API 응답(words + bbox 포함)** 을 그대로 반환합니다. 캐시 미사용.
        RAG/LLM에서 word_indices → bbox 매핑용.
        """
        try:
            doc = fitz.open(pdf_path)
            if page_num < 1 or page_num > doc.page_count:
                doc.close()
                return None
            page = doc.load_page(page_num - 1)
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")
            doc.close()

            try:
                from modules.utils.image_rotation_utils import (
                    detect_and_correct_rotation,
                    is_rotation_detection_available,
                )
                if is_rotation_detection_available():
                    image = Image.open(BytesIO(img_bytes))
                    corrected_image, angle = detect_and_correct_rotation(image, return_angle=True)
                    if angle and angle != 0:
                        buf = BytesIO()
                        if corrected_image.mode != "RGB":
                            corrected_image = corrected_image.convert("RGB")
                        corrected_image.save(buf, format="PNG")
                        img_bytes = buf.getvalue()
            except Exception:
                pass

            temp_image_path = pdf_path.parent / f"{pdf_path.stem}_Page{page_num}_temp.png"
            with open(temp_image_path, "wb") as f:
                f.write(img_bytes)
            result = self.extract_from_image_raw(image_path=temp_image_path)
            try:
                if temp_image_path.exists():
                    temp_image_path.unlink()
            except Exception:
                pass
            return result
        except Exception as e:
            print(f"⚠️ PDF 페이지 raw OCR 실패 ({pdf_path}, 페이지 {page_num}): {e}")
            return None

    def extract_from_pil_image(self, image: Image.Image, cache_path: Optional[Path] = None) -> Optional[str]:
        """
        PIL Image 객체에서 Upstage OCR로 텍스트를 추출합니다.
        
        Args:
            image: PIL Image 객체
            cache_path: 캐시 파일 경로 (None이면 자동 생성)
        
        Returns:
            추출된 텍스트 또는 None
        """
        import tempfile
        
        try:
            # 임시 이미지 파일 생성
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                temp_image_path = Path(tmp_file.name)
                # RGB 모드로 변환 (PNG 저장을 위해)
                if image.mode != 'RGB':
                    image = image.convert('RGB')
                image.save(temp_image_path, "PNG")
            
            # Upstage OCR 호출
            text = self.extract_from_image(temp_image_path, cache_path)
            
            # 임시 파일 삭제
            try:
                if temp_image_path.exists():
                    temp_image_path.unlink()
            except:
                pass
            
            return text
            
        except Exception as e:
            print(f"⚠️ PIL Image OCR 추출 실패: {e}")
            return None


def get_upstage_extractor(api_key: Optional[str] = None, enable_cache: bool = True) -> UpstageExtractor:
    """
    UpstageExtractor 인스턴스를 생성하여 반환합니다.
    
    Args:
        api_key: Upstage API 키 (None이면 환경변수에서 가져옴)
        enable_cache: 캐시 사용 여부 (기본값: True)
    
    Returns:
        UpstageExtractor 인스턴스
    """
    return UpstageExtractor(api_key=api_key, enable_cache=enable_cache)

