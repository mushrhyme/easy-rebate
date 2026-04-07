"""
공통 설정 및 초기화 모듈

PIL Image 설정, .env 로드, 프로젝트 루트 경로 계산 등
애플리케이션 전역 설정을 중앙에서 관리합니다.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from PIL import Image, ImageFile
from dataclasses import dataclass

# PIL Image 설정 (DecompressionBombWarning 방지)
Image.MAX_IMAGE_PIXELS = None  # 제한 없음
ImageFile.LOAD_TRUNCATED_IMAGES = True  # 손상된 이미지도 로드 시도

# .env 파일 로드 (프로젝트 루트의 .env)
_env_loaded = False

def load_env():
    """프로젝트 루트의 .env 파일 로드 (한 번만 실행)"""
    global _env_loaded
    if not _env_loaded:
        env_path = get_project_root() / '.env'
        load_dotenv(env_path)
        _env_loaded = True

def get_project_root() -> Path:
    """
    프로젝트 루트 디렉토리 Path 반환
    """
    current_file = Path(__file__).resolve()
    return current_file.parent.parent.parent

# 모듈 import 시 자동으로 .env 로드
load_env()


@dataclass
class RAGConfig:
    """
    RAG 파싱 설정값 클래스
    
    이 클래스의 값만 수정하면 전체 애플리케이션의 설정이 변경됩니다.
    """
    dpi: int = 200
    text_extraction_method: str = None

    def __post_init__(self):
        # upload_channel: finet(엑셀) / mail(우편물, Azure OCR + 표 복원)
        self.upload_channel_extraction_method = {
            "finet": "excel",
            "mail": "azure",
        }
        # .env 로드 후 RAG/Gemini 프롬프트 파일명 오버라이드 (RAG_PROMPT_FILE, GEMINI_PROMPT_FILE)
        env_rag = os.getenv("RAG_PROMPT_FILE", "").strip()
        if env_rag:
            self.rag_prompt_file = env_rag
        env_gemini = os.getenv("GEMINI_PROMPT_FILE", "").strip()
        if env_gemini:
            self.gemini_prompt_file = env_gemini
    top_k: int = 15
    similarity_threshold: float = 0.7
    search_method: str = "hybrid"
    hybrid_alpha: float = 0.5
    # RAG·정답지·템플릿 생성 등 모든 LLM 호출에 사용할 OpenAI 모델 (단일 설정)
    openai_model: str = "gpt-5.2-2025-12-11"
    question: str = "이 페이지의 상품명, 수량, 금액 등 항목 정보를 모두 추출해줘"
    max_parallel_workers: int = 3  # Azure OCR 1단계 병렬 수 (1=순차, 3~5 권장. 업스테이지와 달리 동시 호출 가능)
    rag_llm_parallel_workers: int = 5  # RAG+LLM 2단계 병렬 워커 수
    ocr_request_delay: float = 2.0  # (미사용) Upstage 등 호출 간격용 예비
    rag_prompt_file: str = "rag_with_example_v11.txt"
    gemini_prompt_file: str = "prompt_v5.txt"


# 전역 설정 인스턴스 (이 값을 수정하면 전체 애플리케이션에 적용됨)
rag_config = RAGConfig()


def get_extraction_method_for_upload_channel(upload_channel: str = None) -> str:
    """upload_channel에 따라 추출 방법 반환. finet→excel, mail→azure(표 복원)."""
    if upload_channel and rag_config.upload_channel_extraction_method:
        return rag_config.upload_channel_extraction_method.get(upload_channel, "azure")
    return "azure"

def folder_name_to_upload_channel(folder_name: str) -> str:
    """
    폴더명을 upload_channel로 변환합니다.

    img 구조: finet/ (엑셀), mail/ (Azure 표 복원)
    - finet → excel 추출
    - mail  → azure 추출
    알 수 없는 폴더명은 기본값 "mail".
    """
    if not folder_name:
        return "mail"  # 기본값

    folder_name = folder_name.strip().lower()
    if folder_name in ("finet", "mail"):
        return folder_name
    return "mail"


def get_rag_prompt_path() -> Path:
    """
    RAG 프롬프트 파일 경로를 반환합니다.
    """
    config = rag_config
    return get_project_root() / "prompts" / config.rag_prompt_file


def get_gemini_prompt_path() -> Path:
    """
    Gemini 프롬프트 파일 경로를 반환합니다.
    """
    config = rag_config
    return get_project_root() / "prompts" / config.gemini_prompt_file


def load_rag_prompt() -> str:
    """
    RAG 프롬프트 파일을 읽어서 반환합니다.
    """
    prompt_path = get_rag_prompt_path()
    if not prompt_path.exists():
        raise FileNotFoundError(f"RAG 프롬프트 파일을 찾을 수 없습니다: {prompt_path}")
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()


def load_gemini_prompt() -> str:
    """
    정답지 생성용 프롬프트 파일을 읽어서 반환합니다. (파일명은 레거시로 gemini_prompt_file 사용)
    """
    prompt_path = get_gemini_prompt_path()
    if not prompt_path.exists():
        raise FileNotFoundError(f"프롬프트 파일을 찾을 수 없습니다: {prompt_path}")
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()

