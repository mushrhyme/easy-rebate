"""
Gemini Vision API를 사용하여 PDF를 페이지별 JSON으로 변환하는 모듈

PDF 파일을 이미지로 변환하고, Gemini Vision API로 각 페이지를 분석하여
구조화된 JSON 결과를 반환합니다. 캐시 기능을 통해 재현성을 보장합니다.
"""

import json
import re
import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import google.generativeai as genai
from PIL import Image

# 공통 설정 로드 (PIL 설정, .env 로드 등)
from modules.utils.config import load_env, load_gemini_prompt, get_gemini_prompt_path, rag_config
load_env()  # 명시적으로 .env 로드

# 공통 PdfImageConverter 모듈 import
from modules.core.extractors.pdf_processor import PdfImageConverter


class GeminiVisionParser:
    """Gemini Vision API를 사용하여 이미지를 구조화된 JSON으로 파싱"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        prompt_version: str = "v1",
    ):
        """
        Args:
            api_key: Google Gemini API 키 (None이면 환경변수에서 가져옴)
            model_name: 사용할 Gemini 모델 이름
            prompt_version: 프롬프트 버전 (사용하지 않음, 호환성 유지용)
        """
        if api_key is None:
            api_key = os.getenv("GEMINI_API_KEY")  # .env 파일에서 환경변수 가져오기
            if not api_key:
                raise ValueError("GEMINI_API_KEY가 필요합니다. .env 파일에 GEMINI_API_KEY를 설정하거나 api_key 파라미터를 제공하세요.")
        
        # 모델 이름 기본값: 전역 설정(rag_config.gemini_extractor_model) 사용
        if model_name is None:
            try:
                model_name = getattr(rag_config, "gemini_extractor_model", "gemini-2.5-flash-lite")
            except Exception:
                model_name = "gemini-2.5-flash-lite"

        genai.configure(api_key=api_key)  # API 키 설정
        
        # 안전성 설정: 문서 분석을 위해 필터 완화
        safety_settings = [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE"
            }
        ]
        
        self.model = genai.GenerativeModel(
            model_name=model_name,
            safety_settings=safety_settings
        )  # Gemini 모델 초기화
        self.model_name = model_name
    
    def get_parsing_prompt(self) -> str:
        """
        Gemini Vision을 위한 구조화 파싱 프롬프트
        
        Returns:
            파싱 프롬프트 문자열
        """
        # config에서 지정한 단일 프롬프트 파일 사용
        try:
            prompt = load_gemini_prompt()
            print(f"📄 프롬프트 파일 로드: {get_gemini_prompt_path().name}")
            return prompt
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Gemini 프롬프트 파일을 찾을 수 없습니다: {e}")
    
    def parse_image(
        self,
        image: Image.Image,
        max_size: int = 1000,
        timeout: int = 120,
        debug_dir: Optional[Union[str, Path]] = None,
        page_number: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        이미지를 Gemini Vision으로 파싱하여 JSON 반환
        
        Args:
            image: PIL Image 객체
            max_size: Gemini API에 전달할 최대 이미지 크기 (픽셀, 기본값: 600)
            timeout: API 호출 타임아웃 (초)
            debug_dir: 지정 시 프롬프트·원문 응답을 이 디렉터리에 저장 (정답지 디버깅용)
            page_number: debug_dir 사용 시 파일명에 사용 (page_N_prompt.txt, page_N_response.txt)
        
        Returns:
            파싱 결과 JSON 딕셔너리
        """
        prompt_text = self.get_parsing_prompt()
        if debug_dir is not None and page_number is not None:
            debug_path = Path(debug_dir)
            debug_path.mkdir(parents=True, exist_ok=True)
            try:
                (debug_path / f"page_{page_number}_prompt.txt").write_text(prompt_text, encoding="utf-8")
            except Exception as e:
                print(f"  [debug] prompt 저장 실패: {e}")

        # 원본 이미지 정보
        original_width, original_height = image.size
        
        # 이미지 리사이즈 (Gemini API 속도 개선을 위해)
        api_image = image
        if original_width > max_size or original_height > max_size:
            ratio = min(max_size / original_width, max_size / original_height)
            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)
            api_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            print(f"  이미지 리사이즈: {original_width}x{original_height}px → {new_width}x{new_height}px", end="", flush=True)
        else:
            print(f"  이미지 크기: {original_width}x{original_height}px", end="", flush=True)
        
        # Gemini API 호출: 재시도 로직 포함 (SAFETY 오류 대응)
        max_retries = 3
        retry_delay = 2
        response = None
        
        for attempt in range(max_retries):
            try:
                chat = self.model.start_chat(history=[])
                _ = chat.send_message([api_image])
                response = chat.send_message(prompt_text)
                break
            except Exception as e:
                error_msg = str(e)
                if "SAFETY" in error_msg or "安全性" in error_msg or "finish_reason: SAFETY" in error_msg:
                    if attempt < max_retries - 1:
                        print(f"  ⚠️ SAFETY 필터 감지 (시도 {attempt + 1}/{max_retries}), {retry_delay}초 후 재시도...", end="", flush=True)
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    raise Exception(f"SAFETY 필터로 인해 {max_retries}회 시도 모두 실패: {error_msg}")
                raise
        
        if not response.candidates:
            raise Exception("Gemini API 응답에 candidates가 없습니다.")
        
        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            raise Exception("Gemini API 응답에 content parts가 없습니다.")
        
        result_text = ""
        for part in candidate.content.parts:
            if hasattr(part, 'text') and part.text:
                result_text += part.text
        
        if not result_text:
            raise Exception("Gemini API 응답에 텍스트가 없습니다.")
        
        if debug_dir is not None and page_number is not None:
            debug_path = Path(debug_dir)
            debug_path.mkdir(parents=True, exist_ok=True)
            try:
                (debug_path / f"page_{page_number}_response.txt").write_text(result_text, encoding="utf-8")
            except Exception as e:
                print(f"  [debug] response 저장 실패: {e}")
        
        try:
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                result_json = json.loads(json_match.group())
                if debug_dir is not None and page_number is not None:
                    debug_path = Path(debug_dir)
                    try:
                        (debug_path / f"page_{page_number}_response_parsed.json").write_text(
                            json.dumps(result_json, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
                    except Exception as e:
                        print(f"  [debug] parsed JSON 저장 실패: {e}")
                return result_json
            return {"text": result_text}
        except json.JSONDecodeError:
            return {"text": result_text}

    def parse_image_with_template(
        self,
        image: Image.Image,
        template_item: Dict[str, Any],
        max_size: int = 1200,
    ) -> Dict[str, Any]:
        """
        이미지 + 템플릿(첫 행)을 주고, 같은 키 구조로 나머지 행까지 포함한 전체 items 생성.
        템플릿은 키와 예시 값만 제공하며, LLM이 문서 이미지를 보고 모든 행을 채움.

        Args:
            image: PIL Image (문서 페이지)
            template_item: 한 행의 키-값 예시 (키 목록 + 첫 행 값)
            max_size: 이미지 최대 크기

        Returns:
            {"items": [...], "page_role": "detail"} 형태
        """
        original_width, original_height = image.size
        api_image = image
        if original_width > max_size or original_height > max_size:
            ratio = min(max_size / original_width, max_size / original_height)
            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)
            api_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        template_json = json.dumps(template_item, ensure_ascii=False, indent=2)
        prompt = f"""You are given a document page image and ONE example row (template) with the following keys and values.
Your task: Look at the image and generate ALL rows on this page. Each row must have exactly the same keys as the template.
Output ONLY a single JSON object with key "items" (array of objects). No other text.

Template (one row, keys and example value):
{template_json}

Output format: {{ "items": [ {{ ... }}, {{ ... }}, ... ] }}
Use the same key names as the template. Fill values from the document for each row."""

        max_retries = 3
        retry_delay = 2
        response = None
        for attempt in range(max_retries):
            try:
                chat = self.model.start_chat(history=[])
                _ = chat.send_message([api_image])
                response = chat.send_message(prompt)
                break
            except Exception as e:
                error_msg = str(e)
                if "SAFETY" in error_msg or "安全性" in error_msg or "finish_reason: SAFETY" in error_msg:
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    raise Exception(f"SAFETY 필터로 인해 {max_retries}회 시도 모두 실패: {error_msg}")
                raise

        if not response or not response.candidates:
            raise Exception("Gemini API 응답에 candidates가 없습니다.")
        result_text = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text:
                result_text += part.text
        if not result_text:
            raise Exception("Gemini API 응답에 텍스트가 없습니다.")

        try:
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                result_json = json.loads(json_match.group())
                items = result_json.get("items")
                if not isinstance(items, list):
                    items = []
                return {"items": items, "page_role": result_json.get("page_role", "detail")}
            return {"items": [], "page_role": "detail"}
        except json.JSONDecodeError:
            return {"items": [], "page_role": "detail"}


def extract_pages_with_gemini(
    pdf_path: str,
    gemini_api_key: Optional[str] = None,
    gemini_model: str = "gemini-3-pro-preview",
        dpi: int = 300,
    use_gemini_cache: bool = False,  # 캐시 비활성화 (DB 사용)
    gemini_cache_path: Optional[str] = None,
    save_images: bool = False,  # 로컬 저장 비활성화 (기본값: False)
    image_output_dir: Optional[str] = None,
    use_history: bool = False,  # 히스토리 비활성화
    history_dir: Optional[str] = None
) -> tuple[List[Dict[str, Any]], List[str], Optional[List[Image.Image]]]:
    """
    PDF 파일을 Gemini로 분석하여 페이지별 JSON 결과 반환
    
    DB를 우선 사용하며, DB에 데이터가 없을 때만 Gemini API를 호출합니다.
    캐시 파일은 사용하지 않습니다.
    
    Args:
        pdf_path: PDF 파일 경로
        gemini_api_key: Gemini API 키 (None이면 환경변수 또는 기본값 사용)
        gemini_model: Gemini 모델 이름
        dpi: PDF 변환 해상도 (기본값: 300)
        use_gemini_cache: Gemini 캐시 사용 여부 (기본값: False, 사용 안 함)
        gemini_cache_path: Gemini 캐시 파일 경로 (사용 안 함)
        save_images: 이미지를 파일로 저장할지 여부 (기본값: False, 사용 안 함)
        image_output_dir: 이미지 저장 디렉토리 (사용 안 함)
        use_history: 히스토리 관리 사용 여부 (기본값: False, 사용 안 함)
        history_dir: 히스토리 디렉토리 (사용 안 함)
        
    Returns:
        (페이지별 Gemini 파싱 결과 JSON 리스트, 이미지 파일 경로 리스트, PIL Image 객체 리스트) 튜플
        이미지 파일 경로는 항상 None 리스트 (로컬 저장 비활성화)
        PIL Image 객체 리스트는 새로 변환한 경우에만 반환
    """
    pdf_name = Path(pdf_path).stem
    pdf_filename = f"{pdf_name}.pdf"
    
    # 이미지 경로 리스트 초기화 (로컬 저장 비활성화로 항상 None 리스트)
    image_paths = []
    pil_images = None  # PIL Image 객체 리스트 (새로 변환한 경우에만)
    
    # 1. DB에서 먼저 확인
    page_jsons = None
    try:
        from database.registry import get_db
        db_manager = get_db()
        page_jsons = db_manager.get_page_results(
            pdf_filename=pdf_filename
        )
        if page_jsons and len(page_jsons) > 0:
            print(f"💾 DB에서 기존 파싱 결과 로드: {len(page_jsons)}개 페이지")
            # DB에서 로드한 경우 이미지는 None (이미 DB에 저장되어 있음)
            image_paths = [None] * len(page_jsons)
            return page_jsons, image_paths, None
    except Exception as db_error:
        print(f"⚠️ DB 확인 실패: {db_error}. 새로 파싱합니다.")
    
    # 2. DB에 데이터가 없으면 Gemini API 호출
    # PDF를 이미지로 변환
    pdf_processor = PdfImageConverter(dpi=dpi)  # PDF 처리기 생성
    images = pdf_processor.convert_pdf_to_images(pdf_path)  # PDF → 이미지 변환
    pil_images = images  # PIL Image 객체 리스트 저장 (DB 저장용)
    print(f"PDF 변환 완료: {len(images)}개 페이지")
    
    # 로컬 저장 비활성화 (DB에만 저장)
    image_paths = [None] * len(images)  # 항상 None 리스트
    
    # Gemini Vision으로 각 페이지 파싱
    gemini_parser = GeminiVisionParser(api_key=gemini_api_key, model_name=gemini_model)  # Gemini 파서 생성
    page_jsons = []
    
    # 각 페이지 파싱 (처음부터 시작)
    start_idx = 0
    total_parse_time = 0.0
    
    # 페이지 수가 충분히 많을 때만 멀티스레딩 사용 (오버헤드 고려)
    use_parallel = (len(images) - start_idx) > 1
    
    if use_parallel:
        # 멀티스레딩으로 병렬 파싱
        completed_count = 0  # 완료된 페이지 수 추적
        results_lock = Lock()  # 결과 리스트 업데이트 시 동기화용
        
        def parse_single_page(idx: int) -> tuple[int, Dict[str, Any], float, Optional[str]]:
            """단일 페이지 파싱 함수 (스레드에서 실행) - 각 스레드마다 별도의 파서 인스턴스 생성"""
            parse_start_time = time.time()
            try:
                # 각 스레드마다 별도의 파서 인스턴스 생성 (thread-safe)
                thread_parser = GeminiVisionParser(api_key=gemini_api_key, model_name=gemini_model)
                page_json = thread_parser.parse_image(images[idx])  # 각 페이지 파싱
                parse_end_time = time.time()
                parse_duration = parse_end_time - parse_start_time
                return (idx, page_json, parse_duration, None)
            except Exception as e:
                parse_end_time = time.time()
                parse_duration = parse_end_time - parse_start_time
                error_result = {"text": f"파싱 실패: {str(e)}", "error": True}
                return (idx, error_result, parse_duration, str(e))
        
        # ThreadPoolExecutor로 병렬 처리 (최대 5개 스레드)
        max_workers = min(5, len(images) - start_idx)  # 최대 5개 스레드 또는 남은 페이지 수 중 작은 값
        print(f"🚀 멀티스레딩 파싱 시작 (최대 {max_workers}개 스레드)")
        
        # 결과를 저장할 딕셔너리 (인덱스 순서 보장)
        parsed_results = {}
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 모든 페이지에 대해 Future 제출
            future_to_idx = {
                executor.submit(parse_single_page, idx): idx 
                for idx in range(start_idx, len(images))
            }
            
            # 완료된 작업부터 처리
            for future in as_completed(future_to_idx):
                idx, page_json, parse_duration, error = future.result()
                total_parse_time += parse_duration
                
                # 결과를 딕셔너리에 저장 (인덱스 순서 보장)
                with results_lock:
                    parsed_results[idx] = page_json
                    completed_count += 1
                
                # 진행 상황 출력
                if error:
                    print(f"페이지 {idx+1}/{len(images)} 파싱 실패 (소요 시간: {parse_duration:.2f}초) - {error}")
                else:
                    print(f"페이지 {idx+1}/{len(images)} 파싱 완료 (소요 시간: {parse_duration:.2f}초) [{completed_count}/{len(images) - start_idx}]")
        
        # 최종 결과를 인덱스 순서대로 page_jsons에 반영
        for idx in range(start_idx, len(images)):
            if idx in parsed_results:
                if idx < len(page_jsons):
                    page_jsons[idx] = parsed_results[idx]  # 업데이트
                else:
                    # 인덱스 순서를 맞추기 위해 None으로 채운 후 추가
                    while len(page_jsons) < idx:
                        page_jsons.append(None)
                    page_jsons.append(parsed_results[idx])  # 추가
    
    else:
        # 단일 페이지인 경우 순차 처리
        for idx in range(start_idx, len(images)):
            parse_start_time = time.time()  # 파싱 시간 측정 시작
            try:
                print(f"페이지 {idx+1}/{len(images)} Gemini Vision 파싱 중...", end="", flush=True)
                
                page_json = gemini_parser.parse_image(images[idx])  # 각 페이지 파싱
                parse_end_time = time.time()
                parse_duration = parse_end_time - parse_start_time
                total_parse_time += parse_duration
                
                # 페이지 결과를 리스트에 추가/업데이트
                if idx < len(page_jsons):
                    page_jsons[idx] = page_json  # 업데이트
                else:
                    page_jsons.append(page_json)  # 추가
                
                # 파싱 시간 출력
                print(f" 완료 (소요 시간: {parse_duration:.2f}초)")
                
            except Exception as e:
                parse_end_time = time.time()
                parse_duration = parse_end_time - parse_start_time
                total_parse_time += parse_duration
                print(f" 실패 (소요 시간: {parse_duration:.2f}초) - {e}")
                # 실패한 페이지는 빈 결과로 추가
                if idx >= len(page_jsons):
                    page_jsons.append({"text": f"파싱 실패: {str(e)}", "error": True})
                # 에러가 발생해도 계속 진행
                continue
        
    # 전체 파싱 시간 요약 출력
    if start_idx < len(images):
        parsed_count = len(images) - start_idx
        avg_time = total_parse_time / parsed_count if parsed_count > 0 else 0
        print(f"\n📊 파싱 통계:")
        print(f"  - 새로 파싱한 페이지: {parsed_count}개")
        print(f"  - 총 소요 시간: {total_parse_time:.2f}초")
        print(f"  - 평균 페이지당 시간: {avg_time:.2f}초")
    
    # 로컬 저장 비활성화로 image_paths는 항상 None 리스트
    if not image_paths and page_jsons:
        image_paths = [None] * len(page_jsons)
    
    return page_jsons, image_paths, pil_images