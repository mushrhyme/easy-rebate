"""
공통 설정 및 초기화 모듈

PIL Image 설정, .env 로드, 프로젝트 루트 경로 계산 등
애플리케이션 전역 설정을 중앙에서 관리합니다.
"""

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
    dpi: int = 300
    text_extraction_method: str = None

    def __post_init__(self):
        # upload_channel: finet(엑셀) / mail(우편물, Upstage OCR)
        self.upload_channel_extraction_method = {
            "finet": "excel",
            "mail": "upstage",
        }
    top_k: int = 15
    similarity_threshold: float = 0.7
    search_method: str = "hybrid"
    hybrid_alpha: float = 0.5
    # RAG 최종 프롬프트용 LLM 선택: "gpt" | "gemini" (gemini_extractor 사용)
    rag_llm_provider: str = "gemini"  # "gpt"로 변경 시 openai_model 사용
    # openai_model: str="gpt-5.2-2025-12-11"
    # openai_model: str = "gpt-5.1-2025-11-13"
    # openai_model: str = "gpt-5-2025-08-07"
    # openai_model: str = "gpt-5-mini-2025-08-07"
    openai_model: str = "gpt-4o-2024-11-20"  # rag_llm_provider="gpt" 일 때 사용
    # openai_model: str = "gpt-4o-2024-08-06"
    gemini_extractor_model: str = "gemini-2.5-flash-lite"  # rag_llm_provider="gemini" 일 때 사용
    question: str = "이 페이지의 상품명, 수량, 금액 등 항목 정보를 모두 추출해줘"
    max_parallel_workers: int = 1
    rag_llm_parallel_workers: int = 5  # LLM 병렬 워커 수 (3 → 5로 증가)
    ocr_request_delay: float = 2.0
    rag_prompt_file: str = "rag_with_example_v3.txt"
    gemini_prompt_file: str = "prompt_v3.txt"
    # PDF 분석 완료 후 img 폴더에 복사할지 여부. False면 DB만 사용(중복 저장 없음).
    # True로 두면 벡터DB 재구축(ベクターDB再構築) 시 img 스캔에 새 문서가 포함됨.
    auto_save_to_training_folder: bool = False


# 전역 설정 인스턴스 (이 값을 수정하면 전체 애플리케이션에 적용됨)
rag_config = RAGConfig()


def get_extraction_method_for_upload_channel(upload_channel: str = None) -> str:
    """upload_channel에 따라 추출 방법 반환. finet→excel, mail→upstage."""
    if upload_channel and rag_config.upload_channel_extraction_method:
        return rag_config.upload_channel_extraction_method.get(upload_channel, "upstage")
    return "upstage"


def folder_name_to_upload_channel(folder_name: str) -> str:
    """
    폴더명을 upload_channel로 변환합니다.

    img 구조: finet/ (엑셀), mail/ (Upstage)
    - finet → excel 추출
    - mail  → upstage 추출
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
    Gemini 프롬프트 파일을 읽어서 반환합니다.
    """
    prompt_path = get_gemini_prompt_path()
    if not prompt_path.exists():
        raise FileNotFoundError(f"Gemini 프롬프트 파일을 찾을 수 없습니다: {prompt_path}")
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()


def get_effective_rag_provider():
    """
    UI 설정 파일(config/rag_provider.json)을 읽어 실제 사용할 (provider, model_name) 반환.
    provider: "gemini" | "gpt"
    model_name: rag_config의 모델 또는 gpt5.2일 때 "gpt-5.2-2025-12-11"
    """
    import json
    config = rag_config
    path = get_project_root() / "config" / "rag_provider.json"
    if not path.exists():
        return (getattr(config, "rag_llm_provider", "gemini"), None)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        p = (data.get("provider") or "gemini").strip().lower()
    except Exception:
        return (getattr(config, "rag_llm_provider", "gemini"), None)
    if p == "gpt5.2":
        return ("gpt", "gpt-5.2-2025-12-11")
    if p == "gemini":
        return ("gemini", getattr(config, "gemini_extractor_model", "gemini-2.5-flash-lite"))
    return (getattr(config, "rag_llm_provider", "gemini"), None)

