"""
Azure Form Recognizer Extractor 모듈

Azure Document Intelligence (Form Recognizer)를 사용하여
이미지나 PDF 페이지에서 텍스트를 추출합니다.

UpstageExtractor와 동일한 수준/인터페이스를 목표로 하며,
PDF → 이미지 변환 및 (필요 시) 회전 보정 흐름도 최대한 유사하게 맞춥니다.
"""

import os
import json
import time
from pathlib import Path
from typing import Optional
from io import BytesIO

import fitz  # PyMuPDF
from PIL import Image

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from azure.core.pipeline.transport import RequestsTransport

# .env 파일 로드
from modules.utils.config import load_env

load_env()


class AzureExtractor:
    """
    Azure Form Recognizer를 사용한 텍스트 추출 클래스

    - 이미지나 PDF 페이지에서 텍스트를 추출하고, 결과를 캐싱합니다.
    - 이미지 해상도/전처리는 UpstageExtractor와 최대한 동일하게 유지합니다.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        model_id: str = "prebuilt-layout",
        enable_cache: bool = True,
    ):
        """
        Args:
            endpoint: Azure Form Recognizer 엔드포인트
            api_key: Azure API 키 (None이면 환경변수에서 가져옴)
            model_id: 사용할 모델 ID (기본값: prebuilt-layout)
            enable_cache: 캐시 사용 여부 (기본값: True)
        """

        self.endpoint = endpoint or os.getenv("AZURE_API_ENDPOINT")
        self.api_key = api_key or os.getenv("AZURE_API_KEY")
        self.model_id = model_id
        self.enable_cache = enable_cache

        self._client: Optional[DocumentAnalysisClient] = None

    # -------------------------
    # 내부 유틸
    # -------------------------
    def _get_client(self) -> Optional[DocumentAnalysisClient]:
        """DocumentAnalysisClient 인스턴스를 반환합니다."""
        if self._client is not None:
            return self._client

        if not self.endpoint or not self.api_key:
            print("⚠️ Azure Form Recognizer 설정이 부족합니다. (AZURE_API_ENDPOINT / AZURE_API_KEY)")
            return None

        transport = RequestsTransport(connection_verify=False)
        self._client = DocumentAnalysisClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.api_key),
            transport=transport,
        )
        return self._client

    def get_cache_path(self, pdf_path: Path, page_num: int) -> Path:
        """
        Azure OCR 결과 캐시 파일 경로를 반환합니다.

        Args:
            pdf_path: PDF 파일 경로
            page_num: 페이지 번호 (1부터 시작)

        Returns:
            캐시 파일 경로
        """
        cache_dir = pdf_path.parent
        cache_filename = f"{pdf_path.stem}_Page{page_num}_azure_ocr.json"
        return cache_dir / cache_filename

    def load_cache(self, cache_path: Path) -> Optional[str]:
        """
        저장된 Azure OCR 결과를 로드합니다.

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
            print(f"⚠️ Azure 캐시 파일 로드 실패 ({cache_path}): {e}")
            return None

    def save_cache(self, cache_path: Path, text: str) -> None:
        """
        Azure OCR 결과를 캐시 파일로 저장합니다.

        Args:
            cache_path: 캐시 파일 경로
            text: OCR 텍스트
        """
        if not self.enable_cache:
            return

        try:
            cache_data = {
                "text": text,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Azure 캐시 파일 저장 실패 ({cache_path}): {e}")

    # -------------------------
    # 공통 분석 로직
    # -------------------------
    def _analyze_image_bytes(self, image_bytes: bytes) -> Optional[str]:
        """
        Azure Form Recognizer로 이미지(바이트)를 분석하여 텍스트만 추출합니다.
        """
        client = self._get_client()
        if client is None:
            return None

        try:
            # BytesIO 래핑 (노트북 예제와 동일한 방식)
            image_stream = BytesIO(image_bytes)
            poller = client.begin_analyze_document(self.model_id, document=image_stream)
            result = poller.result()

            text_parts = []
            for page in result.pages:
                # 노트북 예시와 동일하게, line 단위로 개행을 붙여서 이어붙입니다.
                #   text += ''.join(line.content + '\n' for line in page.lines)
                for line in page.lines:
                    text_parts.append(line.content)
                    text_parts.append("\n")

            text = "".join(text_parts).strip()
            return text

        except Exception as e:
            print(f"⚠️ Azure 분석 실패: {e}")
            import traceback

            traceback.print_exc()
            return None

    # -------------------------
    # 공개 API
    # -------------------------
    def extract_from_image(self, image_path: Path, cache_path: Optional[Path] = None) -> Optional[str]:
        """
        Azure Form Recognizer를 사용하여 이미지 파일에서 텍스트를 추출합니다.
        캐시 파일이 있으면 API 호출 없이 캐시를 사용합니다.

        Args:
            image_path: 이미지 파일 경로
            cache_path: 캐시 파일 경로 (None이면 자동 생성)

        Returns:
            추출된 텍스트 또는 None
        """
        # 캐시 파일 경로 자동 생성
        if cache_path is None:
            cache_path = image_path.parent / f"{image_path.stem}_azure_ocr.json"

        # 캐시 확인
        cached_text = self.load_cache(cache_path)
        if cached_text:
            print(f"✅ Azure OCR 캐시 사용: {cache_path}")
            return cached_text

        if not image_path.exists():
            print(f"⚠️ 이미지 파일을 찾을 수 없습니다: {image_path}")
            return None

        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()

            text = self._analyze_image_bytes(image_bytes)
            if text:
                self.save_cache(cache_path, text)
                print(f"✅ Azure OCR 완료 및 캐시 저장: {cache_path}")
                return text

            print(f"⚠️ Azure OCR 결과가 비어있습니다: {image_path}")
            return None

        except Exception as e:
            print(f"⚠️ Azure OCR 이미지 분석 오류 ({image_path}): {e}")
            import traceback

            traceback.print_exc()
            return None

    def extract_from_pdf_page(self, pdf_path: Path, page_num: int, dpi: int = 300) -> Optional[str]:
        """
        PDF 페이지를 이미지로 변환한 후 Azure OCR로 텍스트를 추출합니다.

        UpstageExtractor.extract_from_pdf_page와 동일한 수준/흐름을 유지합니다.

        Args:
            pdf_path: PDF 파일 경로
            page_num: 페이지 번호 (1부터 시작)
            dpi: PDF 변환 해상도 (기본값: 300)

        Returns:
            추출된 텍스트 또는 None
        """
        try:
            # PDF에서 페이지를 이미지로 변환 (Upstage와 동일한 방식)
            doc = fitz.open(pdf_path)
            if page_num < 1 or page_num > doc.page_count:
                doc.close()
                return None

            page = doc.load_page(page_num - 1)
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")
            doc.close()

            # 필요 시 이미지 회전 감지 및 보정 (Upstage와 동일한 유틸 사용)
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

                    if angle and angle != 0:
                        print(
                            f"🔄 Azure OCR용 이미지 회전 보정: 페이지 {page_num} - {angle}도"
                        )
                        buf = BytesIO()
                        if corrected_image.mode != "RGB":
                            corrected_image = corrected_image.convert("RGB")
                        corrected_image.save(buf, format="PNG")
                        img_bytes = buf.getvalue()
                else:
                    # 회전 감지 기능이 없으면 원본 그대로 사용
                    pass
            except Exception as rotate_error:
                # 회전 보정 실패해도 전체 흐름은 유지
                print(
                    f"⚠️ Azure OCR용 이미지 회전 보정 실패 "
                    f"({pdf_path}, 페이지 {page_num}): {rotate_error}"
                )

            # 캐시 파일 경로
            cache_path = self.get_cache_path(pdf_path, page_num)

            # 캐시 확인
            cached_text = self.load_cache(cache_path)
            if cached_text:
                print(f"✅ Azure OCR 캐시 사용: {cache_path}")
                return cached_text

            # Azure 분석 호출
            text = self._analyze_image_bytes(img_bytes)

            if text:
                self.save_cache(cache_path, text)
                print(f"✅ Azure OCR 완료 및 캐시 저장: {cache_path}")
                return text

            print(f"⚠️ Azure OCR 결과가 비어있습니다: {pdf_path}, 페이지 {page_num}")
            return None

        except Exception as e:
            print(f"⚠️ PDF 페이지 Azure OCR 실패 ({pdf_path}, 페이지 {page_num}): {e}")
            import traceback

            traceback.print_exc()
            return None


def get_azure_extractor(
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    model_id: str = "prebuilt-layout",
    enable_cache: bool = True,
) -> AzureExtractor:
    """
    AzureExtractor 인스턴스를 생성하여 반환합니다.

    Args:
        endpoint: Azure Form Recognizer 엔드포인트
        api_key: Azure API 키
        model_id: 사용할 모델 ID (기본값: prebuilt-layout)
        enable_cache: 캐시 사용 여부 (기본값: True)

    Returns:
        AzureExtractor 인스턴스
    """
    return AzureExtractor(
        endpoint=endpoint,
        api_key=api_key,
        model_id=model_id,
        enable_cache=enable_cache,
    )

