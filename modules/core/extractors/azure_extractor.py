"""
Azure Document Intelligence (OCR) Extractor 모듈

Azure Document Intelligence API를 사용하여 이미지/PDF에서 텍스트를 추출합니다.
모델은 model_id(또는 환경변수 AZURE_DOCUMENT_MODEL_ID)로 선택 가능합니다.

표에서 ケース/バラ 등 열 구분이 필요할 때:
  - Upstage: 단어만 순서대로 나열되어 열 구분 불가.
  - Azure prebuilt-layout: 표 레이아웃 복원 가능. result["tables"]에
    tables[].cells[] 각각 rowIndex, columnIndex, content가 있으므로
    헤더 행(예: ケース, バラ)의 columnIndex와 데이터 셀의 columnIndex를
    매칭하면 "20"이 케이스 수량인지 바라 수량인지 구분 가능.

사용 가능한 prebuilt 모델 예:
  - prebuilt-read   : OCR 전용 (단어 나열만)
  - prebuilt-layout : 레이아웃·표 구조 (tables[].cells[].rowIndex, columnIndex, content)
  - prebuilt-document: 일반 문서 (텍스트+키/밸류 등)

Upstage extractor와 동일한 인터페이스를 제공하며,
결과를 Upstage 호환 형식(pages[].words[].text, boundingBox) + tables 로 정규화합니다.
"""

import os
import json
import time
import requests
from pathlib import Path
from typing import Optional
import fitz  # PyMuPDF
from PIL import Image

from modules.utils.config import load_env

load_env()

# Azure Document Intelligence API
# https://learn.microsoft.com/en-us/rest/api/aiservices/document-models/analyze-document-from-stream
API_VERSION = "2024-11-30"
# 기본 모델. 표에서 ケース/バラ 등 열 구분이 필요하면 prebuilt-layout 사용.
#   prebuilt-read   - OCR 전용 (단어 나열만, 표 구조 없음)
#   prebuilt-layout - 표 레이아웃 복원 (tables[].cells[].rowIndex, columnIndex, content)
DEFAULT_MODEL_ID = "prebuilt-read"
DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_POLL_TIMEOUT = 120.0


def _normalize_azure_result(azure_result: dict) -> dict:
    """
    Azure 분석 결과를 Upstage와 호환되는 형식으로 정규화합니다.
    - text: 전체 텍스트
    - pages[].words[].text, pages[].words[].boundingBox (polygon)
    - tables: (prebuilt-layout 한정) 표 배열. 각 표는 cells[] with rowIndex, columnIndex, content.
              케이스/バラ 등 열 구분 시 이 구조로 columnIndex와 헤더 행을 매칭하면 됨.
    """
    if not azure_result or not isinstance(azure_result, dict):
        return {"text": "", "pages": [], "tables": []}

    content = azure_result.get("content") or ""
    pages_in = azure_result.get("pages") or []
    pages_out = []

    for page_in in pages_in:
        if not isinstance(page_in, dict):
            continue
        words_in = page_in.get("words") or []
        words_out = []
        for w in words_in:
            if not isinstance(w, dict):
                continue
            text = w.get("content") or w.get("text") or ""
            polygon = w.get("polygon")
            if polygon is not None:
                words_out.append({"text": text, "boundingBox": polygon})
            else:
                words_out.append({"text": text})
        lines_in = page_in.get("lines") or []
        line_texts = [ln.get("content") or ln.get("text") or "" for ln in lines_in if isinstance(ln, dict)]
        page_text = "\n".join(line_texts) if line_texts else " ".join(w["text"] for w in words_out)
        pages_out.append({
            "text": page_text,
            "content": page_text,
            "words": words_out,
        })
    full_text = content.strip() if isinstance(content, str) else ""
    if not full_text and pages_out:
        full_text = "\n".join(p.get("text", "") or p.get("content", "") for p in pages_out)

    # prebuilt-layout 응답: tables[] 포함. 셀별 rowIndex/columnIndex로 ケース vs バラ 구분 가능.
    tables = azure_result.get("tables") or []
    return {"text": full_text, "pages": pages_out, "tables": tables}


class AzureExtractor:
    """
    Azure Document Intelligence API를 사용한 텍스트 추출 클래스.
    model_id로 prebuilt-read / prebuilt-layout 등 모델을 선택할 수 있습니다.
    Upstage extractor와 동일한 메서드 시그니처를 제공합니다.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        model_id: Optional[str] = None,
        enable_cache: bool = True,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
    ):
        """
        Args:
            api_key: Azure API 키 (None이면 환경변수 AZURE_API_KEY)
            endpoint: Azure endpoint URL (None이면 환경변수 AZURE_API_ENDPOINT)
            model_id: 문서 분석 모델 (None이면 prebuilt-read).
                      예: "prebuilt-read", "prebuilt-layout"
            enable_cache: 캐시 사용 여부
            poll_interval: 결과 폴링 간격(초)
            poll_timeout: 폴링 최대 대기 시간(초)
        """
        self.api_key = api_key or os.getenv("AZURE_API_KEY")
        raw_endpoint = (endpoint or os.getenv("AZURE_API_ENDPOINT") or "").strip()
        if raw_endpoint and not raw_endpoint.endswith("/"):
            raw_endpoint = raw_endpoint + "/"
        self.endpoint = raw_endpoint
        self.model_id = (model_id or os.getenv("AZURE_DOCUMENT_MODEL_ID") or DEFAULT_MODEL_ID).strip()
        self.enable_cache = enable_cache
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self._analyze_url = f"{self.endpoint}documentintelligence/documentModels/{self.model_id}:analyze?api-version={API_VERSION}"

    def _headers(self) -> dict:
        return {"Ocp-Apim-Subscription-Key": self.api_key or ""}

    def _analyze_document(self, data: bytes, content_type: str = "image/png") -> Optional[dict]:
        """
        문서/이미지 바이트로 Analyze 요청을 보내고, 폴링 후 결과 JSON을 반환합니다.
        """
        if not self.api_key or not self.endpoint:
            print("⚠️ AZURE_API_KEY 또는 AZURE_API_ENDPOINT가 설정되지 않았습니다.")
            return None
        try:
            resp = requests.post(
                self._analyze_url,
                headers={**self._headers(), "Content-Type": content_type},
                data=data,
                timeout=60,
            )
            if resp.status_code != 202:
                try:
                    err = resp.json()
                    print(f"⚠️ Azure Analyze 오류: {err}")
                except Exception:
                    print(f"⚠️ Azure Analyze 실패: {resp.status_code} {resp.text[:500]}")
                return None
            operation_location = resp.headers.get("Operation-Location")
            if not operation_location:
                print("⚠️ Azure 응답에 Operation-Location이 없습니다.")
                return None
            # 폴링 (응답: status + analyzeResult)
            deadline = time.monotonic() + self.poll_timeout
            while time.monotonic() < deadline:
                time.sleep(self.poll_interval)
                poll_resp = requests.get(operation_location, headers=self._headers(), timeout=30)
                poll_resp.raise_for_status()
                result = poll_resp.json()
                status = result.get("status", "").lower()
                if status == "succeeded":
                    return result.get("analyzeResult") or result
                if status == "failed":
                    print(f"⚠️ Azure 분석 실패: {result.get('error', result)}")
                    return None
            print("⚠️ Azure 분석 폴링 시간 초과")
            return None
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Azure Document Intelligence API 오류: {e}")
            return None
        except Exception as e:
            print(f"⚠️ Azure OCR 오류: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_cache_path(self, pdf_path: Path, page_num: int) -> Path:
        """캐시 파일 경로 (Upstage와 동일 규칙)."""
        cache_dir = pdf_path.parent
        cache_filename = f"{pdf_path.stem}_Page{page_num}_azure_ocr.json"
        return cache_dir / cache_filename

    def load_cache(self, cache_path: Path) -> Optional[str]:
        """캐시에서 텍스트만 로드."""
        if not self.enable_cache or not cache_path.exists():
            return None
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            return cache_data.get("text") or None
        except Exception as e:
            print(f"⚠️ Azure 캐시 로드 실패 ({cache_path}): {e}")
            return None

    def save_cache(self, cache_path: Path, normalized: dict):
        """정규화된 결과를 캐시에 저장."""
        if not self.enable_cache:
            return
        try:
            cache_data = {
                "text": normalized.get("text", ""),
                "pages": normalized.get("pages", []),
                "tables": normalized.get("tables", []),
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Azure 캐시 저장 실패 ({cache_path}): {e}")

    def extract_from_image(
        self,
        image_path: Path,
        cache_path: Optional[Path] = None,
    ) -> Optional[str]:
        """
        이미지에서 텍스트를 추출합니다. 캐시가 있으면 사용합니다.
        Returns:
            추출된 전체 텍스트 또는 None
        """
        if cache_path is None:
            cache_path = image_path.parent / f"{image_path.stem}_azure_ocr.json"
        cached = self.load_cache(cache_path)
        if cached:
            print(f"✅ Azure OCR 캐시 사용: {cache_path}")
            return cached
        if not image_path.exists():
            print(f"⚠️ 이미지 파일 없음: {image_path}")
            return None
        data = image_path.read_bytes()
        suffix = image_path.suffix.lower()
        content_type = "image/png"
        if suffix in (".jpg", ".jpeg"):
            content_type = "image/jpeg"
        elif suffix == ".bmp":
            content_type = "image/bmp"
        elif suffix in (".tif", ".tiff"):
            content_type = "image/tiff"
        raw = self._analyze_document(data, content_type=content_type)
        if not raw:
            return None
        normalized = _normalize_azure_result(raw)
        text = (normalized.get("text") or "").strip()
        if text:
            self.save_cache(cache_path, normalized)
            print(f"✅ Azure OCR 완료 및 캐시 저장: {cache_path}")
        return text or None

    def extract_from_image_raw(
        self,
        image_path: Optional[Path] = None,
        image_bytes: Optional[bytes] = None,
    ) -> Optional[dict]:
        """
        이미지에서 OCR 후 Upstage 호환 형식의 전체 결과를 반환합니다. 캐시 미사용.
        Returns:
            {"text": "...", "pages": [{"words": [{"text", "boundingBox"}]}]} 또는 None
        """
        if image_bytes is not None:
            data = image_bytes
            content_type = "image/png"
        elif image_path and image_path.exists():
            data = image_path.read_bytes()
            suffix = image_path.suffix.lower()
            content_type = "image/png"
            if suffix in (".jpg", ".jpeg"):
                content_type = "image/jpeg"
            elif suffix == ".bmp":
                content_type = "image/bmp"
            elif suffix in (".tif", ".tiff"):
                content_type = "image/tiff"
        else:
            print("⚠️ extract_from_image_raw: image_path 또는 image_bytes 필요")
            return None
        raw = self._analyze_document(data, content_type=content_type)
        if not raw:
            return None
        return _normalize_azure_result(raw)

    def extract_from_pdf_page(
        self,
        pdf_path: Path,
        page_num: int,
        dpi: int = 300,
    ) -> Optional[str]:
        """PDF 한 페이지를 이미지로 변환 후 Azure OCR로 텍스트 추출."""
        cache_path = self.get_cache_path(pdf_path, page_num)
        if self.enable_cache:
            cached = self.load_cache(cache_path)
            if cached:
                return cached
        try:
            doc = fitz.open(pdf_path)
            if page_num < 1 or page_num > doc.page_count:
                doc.close()
                return None
            page = doc.load_page(page_num - 1)
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")
            doc.close()
            temp_path = pdf_path.parent / f"{pdf_path.stem}_Page{page_num}_temp_azure.png"
            temp_path.write_bytes(img_bytes)
            try:
                text = self.extract_from_image(temp_path, cache_path=cache_path)
                return text
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ PDF 페이지 Azure OCR 실패 ({pdf_path}, 페이지 {page_num}): {e}")
        return None

    def extract_from_pdf_page_raw(
        self,
        pdf_path: Path,
        page_num: int,
        dpi: int = 300,
    ) -> Optional[dict]:
        """PDF 한 페이지를 이미지로 변환 후 Azure OCR raw 결과(Upstage 호환 형식) 반환."""
        try:
            doc = fitz.open(pdf_path)
            if page_num < 1 or page_num > doc.page_count:
                doc.close()
                return None
            page = doc.load_page(page_num - 1)
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")
            doc.close()
            temp_path = pdf_path.parent / f"{pdf_path.stem}_Page{page_num}_temp_azure.png"
            temp_path.write_bytes(img_bytes)
            try:
                return self.extract_from_image_raw(image_path=temp_path)
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ PDF 페이지 Azure raw OCR 실패 ({pdf_path}, 페이지 {page_num}): {e}")
        return None

    def extract_from_pil_image(
        self,
        image: Image.Image,
        cache_path: Optional[Path] = None,
    ) -> Optional[str]:
        """PIL Image에서 텍스트 추출."""
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                temp_path = Path(tmp.name)
                if image.mode != "RGB":
                    image = image.convert("RGB")
                image.save(temp_path, "PNG")
            return self.extract_from_image(temp_path, cache_path=cache_path)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


def get_azure_extractor(
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
    model_id: Optional[str] = None,
    enable_cache: bool = True,
) -> AzureExtractor:
    """
    AzureExtractor 인스턴스를 생성하여 반환합니다.

    Args:
        api_key: Azure API 키 (None이면 AZURE_API_KEY)
        endpoint: Azure endpoint (None이면 AZURE_API_ENDPOINT)
        model_id: 문서 모델. None이면 AZURE_DOCUMENT_MODEL_ID 또는 "prebuilt-read".
                  예: "prebuilt-read", "prebuilt-layout"
        enable_cache: 캐시 사용 여부
    """
    return AzureExtractor(
        api_key=api_key,
        endpoint=endpoint,
        model_id=model_id,
        enable_cache=enable_cache,
    )
