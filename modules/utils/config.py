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
    form_extraction_method: dict = None
    form_color_grouping_column: dict = None
    form_field_mapping: dict = None

    def __post_init__(self):
        if self.form_extraction_method is None:
            self.form_extraction_method = {
                "01": "excel",
                "02": "excel",
                "03": "upstage",
                "04": "upstage",
                "05": "excel",
                # 양식지 06: Upstage OCR 사용
                "06": "upstage",
            }
        if self.form_color_grouping_column is None:
            self.form_color_grouping_column = {
                "01": "請求伝票番号",
                "02": "JANコード",
                "03": "請求No",
                "04": "管理No",
                "05": "照会番号"
            }
        if self.form_field_mapping is None:
            self.form_field_mapping = {
                "customer": {
                    "01": "得意先名", 
                    "02": "得意先様",  
                    "03": "得意先名", 
                    "04": "得意先",  
                    "05": "得意先", 
                },
                "customer_code": {
                    "01": "得意先コード",
                    "02": "得意先コード",
                    "03": "得意先コード",
                    "04": "得意先コード",
                    "05": "得意先コード",
                },
                "management_id": {
                    "01": "請求伝票番号",
                    "02": "請求No（契約No）",
                    "03": "請求No",
                    "04": "管理No",
                    "05": "照会番号",
                },
                "product_name": {
                    "01": "商品名",
                    "02": "商品名",
                    "03": "商品名",
                    "04": "商品名",
                    "05": "商品名",
                },
                "summary": {
                    "01": "備考",
                    "03": "摘要",
                },
                "tax": {
                    "01": "消費税率",
                    "03": "税額",
                },
            }

    top_k: int = 15
    similarity_threshold: float = 0.7
    search_method: str = "hybrid"
    hybrid_alpha: float = 0.5
    # openai_model: str="gpt-5.2-2025-12-11"
    # openai_model: str = "gpt-5.1-2025-11-13"
    # openai_model: str = "gpt-5-2025-08-07"
    # openai_model: str = "gpt-5-mini-2025-08-07"
    openai_model: str = "gpt-4o-2024-11-20"
    # openai_model: str = "gpt-4o-2024-08-06"
    question: str = "이 페이지의 상품명, 수량, 금액 등 항목 정보를 모두 추출해줘"
    max_parallel_workers: int = 1
    rag_llm_parallel_workers: int = 5  # LLM 병렬 워커 수 (3 → 5로 증가)
    ocr_request_delay: float = 2.0
    rag_prompt_file: str = "rag_with_example_v3.txt"
    gemini_prompt_file: str = "prompt_v2.txt"
    auto_save_to_training_folder: bool = True  # PDF 분석 완료 후 자동으로 img 폴더에 저장할지 여부


# 전역 설정 인스턴스 (이 값을 수정하면 전체 애플리케이션에 적용됨)
rag_config = RAGConfig()


def get_extraction_method_for_form(form_number: str = None) -> str:
    """
    양식지 번호에 따라 텍스트 추출 방법을 반환합니다.
    """
    config = rag_config
    if form_number and config.form_extraction_method:
        result = config.form_extraction_method.get(form_number, config.text_extraction_method)
        return result
    result = config.text_extraction_method
    return result


def get_color_grouping_column_for_form(form_number: str = None) -> str:
    """
    양식지 번호에 따라 색상 그룹핑 기준 컬럼을 반환합니다.
    """
    config = rag_config
    if form_number and config.form_color_grouping_column:
        return config.form_color_grouping_column.get(form_number)
    return None


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

