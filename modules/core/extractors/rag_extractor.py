"""
RAG 기반 JSON 추출 모듈

OCR 텍스트를 입력받아 벡터 DB에서 유사한 예제를 검색하고,
그 예제를 컨텍스트로 사용하여 LLM으로 JSON을 추출합니다.
"""

import os
import re
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from openai import OpenAI
import numpy as np

from modules.core.rag_manager import get_rag_manager
from modules.utils.config import get_project_root, load_rag_prompt


def _normalize_amount_colon(value: Any) -> Any:
    """OCR 회계 점선이 콜론으로 읽힌 금액 문자열을 숫자만 이어 붙인 형태로 정규화. 예: '1:500' -> '1500'"""
    if isinstance(value, str) and re.fullmatch(r"\d+:\d+", value):
        return value.replace(":", "")
    return value


def _sanitize_invalid_json_escapes(s: str) -> str:
    """
    JSON 원문에서 잘못된 이스케이프(\\X, X가 허용 문자 아님)를 수정.
    허용: \\" \\\\ \\/ \\b \\f \\n \\r \\t \\uXXXX → 그대로 유지.
    그 외(예: \\ن) → 백슬래시 제거 후 다음 문자만 유지.
    """
    out = []
    i = 0
    while i < len(s):
        if s[i] != "\\" or i + 1 >= len(s):
            out.append(s[i])
            i += 1
            continue
        n = s[i + 1]
        if n in '"\\/bfnrt':
            out.append(s[i])
            out.append(n)
            i += 2
            continue
        if n == "u" and i + 5 <= len(s):
            hex_part = s[i + 2 : i + 6]
            if len(hex_part) == 4 and all(c in "0123456789aAbBcCdDeEfF" for c in hex_part):
                out.append(s[i : i + 6])
                i += 6
                continue
        # invalid: drop backslash, keep next char (e.g. \ن → ن)
        out.append(n)
        i += 2
    return "".join(out)


# RAG 예제를 프롬프트에 넣을 때 제거할 필드 (DB/앱 식별용, LLM 추출 대상 아님)
_EXAMPLE_STRIP_KEYS = frozenset({"item_id", "pdf_filename", "page_number", "item_order", "version", "review_status"})


def _sanitize_example_answer_for_prompt(answer_json: Dict[str, Any], key_order: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    RAG 예제 answer_json을 프롬프트용으로 정리: DB 전용 필드 제거 + key_order대로 키 순서 복원.
    answer.json 원본에 있던 필드만 남기고 순서를 맞춤.
    """
    if not answer_json or not isinstance(answer_json, dict):
        return answer_json
    page_keys = (key_order or {}).get("page_keys", [])
    item_keys = (key_order or {}).get("item_keys", [])
    out = {}
    for key in page_keys if page_keys else answer_json.keys():
        if key not in answer_json:
            continue
        if key == "items" and isinstance(answer_json[key], list) and answer_json[key]:
            clean_items = []
            for item in answer_json[key]:
                if not isinstance(item, dict):
                    clean_items.append(item)
                    continue
                # DB 전용 필드 제거
                stripped = {k: v for k, v in item.items() if k not in _EXAMPLE_STRIP_KEYS}
                # item_keys 순서대로 정렬 (원본 answer.json 순서)
                ordered = {}
                for ik in (item_keys if item_keys else stripped.keys()):
                    if ik in stripped:
                        ordered[ik] = stripped[ik]
                for ik in stripped:
                    if ik not in ordered:
                        ordered[ik] = stripped[ik]
                clean_items.append(ordered)
            out[key] = clean_items
        else:
            out[key] = answer_json[key]
    for key in answer_json:
        if key not in out:
            out[key] = answer_json[key]
    return out


def _reorder_json_by_key_order(json_data: Dict[str, Any], key_order: Dict[str, Any]) -> Dict[str, Any]:
    """
    메타데이터의 키 순서를 사용하여 JSON 재정렬
    
    Args:
        json_data: 재정렬할 JSON 딕셔너리
        key_order: {
            "page_keys": ["page_number", "page_role", ...],
            "item_keys": ["照会番号", "management_id", ...]
        }
        
    Returns:
        키 순서가 재정렬된 JSON 딕셔너리
    """
    if not key_order:
        return json_data
    
    reordered = {}
    page_keys = key_order.get("page_keys", [])
    item_keys = key_order.get("item_keys", [])
    
    # 페이지 레벨 키 순서대로 추가
    for key in page_keys:
        if key in json_data:
            if key == "items" and isinstance(json_data[key], list) and item_keys:
                # items 배열 내부 객체들도 재정렬
                reordered_items = []
                for item in json_data[key]:
                    if isinstance(item, dict):
                        reordered_item = {}
                        # 정의된 키 순서대로 추가
                        for item_key in item_keys:
                            if item_key in item:
                                reordered_item[item_key] = item[item_key]
                        # 정의에 없지만 결과에 있는 키 추가 (순서는 뒤로)
                        for item_key in item.keys():
                            if item_key not in item_keys:
                                reordered_item[item_key] = item[item_key]
                        reordered_items.append(reordered_item)
                    else:
                        reordered_items.append(item)
                reordered[key] = reordered_items
            else:
                reordered[key] = json_data[key]
    
    # 정의에 없지만 결과에 있는 키 추가 (순서는 뒤로)
    for key in json_data.keys():
        if key not in page_keys:
            reordered[key] = json_data[key]
    
    return reordered


def convert_numpy_types(obj: Any) -> Any:
    """
    NumPy 타입을 Python 네이티브 타입으로 변환 (JSON 직렬화를 위해)
    
    Args:
        obj: 변환할 객체 (딕셔너리, 리스트, 또는 단일 값)
        
    Returns:
        변환된 객체
    """
    if isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, (np.integer, np.floating)):
        return float(obj) if isinstance(obj, np.floating) else int(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    else:
        return obj


def _vertices_to_rect(vertices):
    if not vertices:
        return None
    xs = [v["x"] for v in vertices]
    ys = [v["y"] for v in vertices]
    left = min(xs)
    top = min(ys)
    right = max(xs)
    bottom = max(ys)
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def _bbox_from_word_indices(words: list, indices: list) -> Optional[Dict[str, float]]:
    """단어 인덱스 리스트로 union bbox 계산 (페이지 픽셀 좌표)."""
    if not words or not indices:
        return None
    rects = []
    for i in indices:
        if i < 0 or i >= len(words):
            continue
        w = words[i]
        bbox = w.get("boundingBox") or w.get("bounding_box")
        if not bbox:
            continue
        vert = bbox.get("vertices")
        rect = _vertices_to_rect(vert)
        if rect:
            rects.append(rect)
    if not rects:
        return None
    left = min(r["left"] for r in rects)
    top = min(r["top"] for r in rects)
    right = max(r["left"] + r["width"] for r in rects)
    bottom = max(r["top"] + r["height"] for r in rects)
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def _attach_bbox_to_json(obj: Any, words: list, path: str = "") -> None:
    """재귀적으로 _word_indices를 bbox로 변환해 _bbox 키로 붙인다. 리스트/딕셔너리만 순회."""
    if isinstance(obj, dict):
        keys = list(obj.keys())
        for key in keys:
            if key.endswith("_word_indices"):
                base = key[:- len("_word_indices")]
                if base in obj and isinstance(obj[key], list):
                    bbox = _bbox_from_word_indices(words, obj[key])
                    if bbox is not None:
                        obj[base + "_bbox"] = bbox
            else:
                _attach_bbox_to_json(obj[key], words, path + "." + key if path else key)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _attach_bbox_to_json(item, words, path + f"[{i}]")


def extract_json_with_rag(
    ocr_text: str,
    question: Optional[str] = None,
    model_name: Optional[str] = None,
    temperature: Optional[float] = None,  # None이면 API 호출 시 포함하지 않음 (모델 기본값 사용)
    top_k: Optional[int] = None,
    similarity_threshold: Optional[float] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    debug_dir: Optional[str] = None,
    page_num: Optional[int] = None,
    prompt_version: str = "v3",  # 사용하지 않음 (호환성 유지용)
    form_type: Optional[str] = None,
    ocr_words: Optional[list] = None,
    page_width: Optional[int] = None,
    page_height: Optional[int] = None,
    include_bbox: bool = False,  # True일 때만 프롬프트에 WORD_INDEX 요청·결과에 _bbox 부여 (OCR 탭 그림용)
) -> Dict[str, Any]:
    """
    RAG 기반 JSON 추출
    
    Args:
        ocr_text: OCR 추출 결과 텍스트
        question: 질문 텍스트 (None이면 config에서 가져옴)
        model_name: 사용할 OpenAI 모델명 (None이면 config에서 가져옴)
        temperature: 모델 temperature (None이면 API 호출 시 포함하지 않음, 모델 기본값 사용)
        top_k: 검색할 예제 수 (None이면 config에서 가져옴)
        similarity_threshold: 최소 유사도 임계값 (None이면 config에서 가져옴)
        form_type: 양식지 번호 (01, 02, 03, 04, 05). None이면 모든 양식지에서 검색 (하위 호환성)
        include_bbox: True면 OCR 탭처럼 좌표용으로 _word_indices 요청·_bbox 부여. 기본은 False(최종 프롬프트에 좌표 없음).
        
    Returns:
        추출된 JSON 딕셔너리
    """
    # RAG Manager 및 설정 가져오기 (UI 설정 파일 우선)
    from modules.utils.config import rag_config, get_effective_rag_provider
    config = rag_config
    effective_provider, effective_model = get_effective_rag_provider()
    rag_llm_provider = effective_provider
    rag_manager = get_rag_manager()

    # API 키 확인 (provider에 따라)
    if rag_llm_provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY가 필요합니다. .env 파일에 설정하세요.")
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY가 필요합니다. .env 파일에 설정하세요.")
    
    # form_type이 전달된 경우 인덱스 새로고침
    # (rag_tab.py와 동일한 동작을 위해 reload_index() 호출)
    # 참고: search_similar_advanced() 내부에서도 form_type별 인덱스를 로드하지만,
    # BM25 인덱스 갱신 등을 위해 reload_index()를 먼저 호출
    if form_type:
        rag_manager.reload_index()
    
    # 파라미터가 None이면 config 또는 UI 설정에서 가져오기
    question = question or config.question
    if effective_model is not None:
        model_name = effective_model
    elif rag_llm_provider == "gemini":
        model_name = getattr(config, "gemini_extractor_model", "gemini-2.5-flash-lite")
    else:
        model_name = model_name or config.openai_model
    top_k = top_k if top_k is not None else config.top_k
    similarity_threshold = similarity_threshold if similarity_threshold is not None else config.similarity_threshold
    search_method = getattr(config, 'search_method', 'hybrid')  # 기본값: hybrid
    hybrid_alpha = getattr(config, 'hybrid_alpha', 0.5)  # 기본값: 0.5
    
    if progress_callback:
        if search_method == "hybrid":
            progress_callback("벡터 DB에서 유사한 예제 검색 중 (하이브리드: BM25 + 벡터)...")
        else:
            progress_callback("벡터 DB에서 유사한 예제 검색 중...")

    # 전체 통합 검색 (form_type=None으로 모든 양식에서 검색, 최상위 유사 예제의 양식지를 따름)
    effective_form_type = None
    
    # 하이브리드 검색 사용 (전체 DB 통합 검색)
    similar_examples = rag_manager.search_similar_advanced(
        query_text=ocr_text,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        search_method=search_method,
        hybrid_alpha=hybrid_alpha,
        form_type=effective_form_type,
    )
    
    # 검색 결과가 없으면 threshold를 낮춰서 재검색 (notepad 예제와 동일하게 최상위 결과 사용)
    if not similar_examples:
        print(f"  ⚠️ 검색 결과 없음 (threshold: {similarity_threshold}), threshold를 0.0으로 낮춰 재검색...")
        similar_examples = rag_manager.search_similar_advanced(
            query_text=ocr_text,
            top_k=1,  # 최상위 1개만
            similarity_threshold=0.0,  # threshold 무시
            search_method=search_method,
            hybrid_alpha=hybrid_alpha,
            form_type=effective_form_type,
        )
        if similar_examples:
            score_key = "hybrid_score" if "hybrid_score" in similar_examples[0] else \
                       "final_score" if "final_score" in similar_examples[0] else \
                       "similarity"
            score_value = similar_examples[0].get(score_key, 0)
            print(f"  ✅ 재검색 성공: {score_key}: {score_value:.4f} (threshold 무시하고 최상위 결과 사용)")
    
    # RAG에서 선택된 최상위 예제 메타데이터 (문서/페이지/form_type)를 추출해 둔다.
    # - debug JSON 저장뿐만 아니라, LLM 결과(JSON)에도 _rag_reference로 포함시키기 위함.
    top_example_metadata = None
    if similar_examples:
        top_example = similar_examples[0]
        top_meta = top_example.get("metadata", {}) or {}
        top_meta = convert_numpy_types(top_meta)
        top_example_metadata = {
            "id": top_example.get("id"),
            "source": top_example.get("source"),
            "pdf_name": top_meta.get("pdf_name"),
            "page_num": top_meta.get("page_num"),
            "form_type": top_meta.get("form_type"),
            "metadata": top_meta,
        }
    
    if progress_callback:
        if similar_examples:
            # 점수 키 확인 (hybrid_score, final_score, similarity 중 하나)
            score_key = "hybrid_score" if "hybrid_score" in similar_examples[0] else \
                       "final_score" if "final_score" in similar_examples[0] else \
                       "similarity"
            score_value = similar_examples[0].get(score_key, 0)
            progress_callback(f"유사한 예제 {len(similar_examples)}개 발견 ({score_key}: {score_value:.2f})")
        else:
            progress_callback("유사한 예제 없음 (예제 없이 진행)")
    
    # 디버깅: OCR 텍스트 저장
    if debug_dir and page_num:
        try:
            # 디버깅 폴더가 없으면 생성
            os.makedirs(debug_dir, exist_ok=True)
            if not os.path.exists(debug_dir):
                raise Exception(f"디버깅 폴더 생성 실패: {debug_dir}")
            
            ocr_file = os.path.join(debug_dir, f"page_{page_num}_ocr_text.txt")
            with open(ocr_file, 'w', encoding='utf-8') as f:
                f.write(ocr_text)
            # print(f"  💾 디버깅: OCR 텍스트 저장 완료 - {ocr_file}")
            
            # RAG 검색 결과 저장
            if similar_examples and top_example_metadata:
                rag_example_file = os.path.join(debug_dir, f"page_{page_num}_rag_example.json")
                top_example = similar_examples[0]

                # NumPy 타입을 Python 네이티브 타입으로 변환
                example_data = {
                    "similarity": top_example.get('similarity', 0),
                    "ocr_text": top_example.get('ocr_text', ''),
                    "answer_json": top_example.get('answer_json', {}),
                    # 어떤 문서를 참조했는지 확인하기 위한 정보
                    "reference": top_example_metadata,
                }
                # 추가 점수 필드도 포함 (hybrid_score, bm25_score 등)
                if 'hybrid_score' in top_example:
                    example_data["hybrid_score"] = top_example.get('hybrid_score', 0)
                if 'bm25_score' in top_example:
                    example_data["bm25_score"] = top_example.get('bm25_score', 0)
                if 'final_score' in top_example:
                    example_data["final_score"] = top_example.get('final_score', 0)
                
                # NumPy 타입 변환 후 JSON 저장
                example_data = convert_numpy_types(example_data)
                with open(rag_example_file, 'w', encoding='utf-8') as f:
                    json.dump(example_data, f, ensure_ascii=False, indent=2)
                # print(f"  💾 디버깅: RAG 예제 저장 완료 - {rag_example_file}")
            else:
                print(f"  💾 디버깅: RAG 예제 없음")
        except Exception as debug_error:
            import traceback
            print(f"⚠️ 디버깅 정보 저장 실패: {debug_error}")
            print(f"  상세:\n{traceback.format_exc()}")
    
    # 2. 프롬프트 구성 (include_bbox이고 ocr_words 있을 때만 단어 인덱스·좌표용 지시 추가)
    prompt_template = load_rag_prompt()
    text_for_prompt = ocr_text
    word_index_instruction = ""
    if include_bbox and ocr_words and len(ocr_words) > 0:
        lines = [f"{i}\t{(w.get('text') or '').strip()}" for i, w in enumerate(ocr_words)]
        text_for_prompt = "\n".join(lines)
        word_index_instruction = """

WORD_INDEX RULES (좌표 부여용, 반드시 준수):
- 위 TARGET_OCR은 한 줄에 "단어인덱스(0부터)\\t단어텍스트" 형태로 나열된 것이다.
- **문자열 값을 추출하는 모든 필드**에 대해, 같은 키 이름 뒤에 _word_indices 를 붙여
  해당 값이 TARGET_OCR의 어느 단어 인덱스들로 구성되는지 JSON 배열로 반드시 출력한다.
- 예: 商品名: "農心 辛ラーメン" 이면 商品名_word_indices: [5, 6, 7] 처럼 해당 단어 인덱스 배열을 함께 출력.
- items 배열 안의 각 객체 필드(商品名, 金額, 得意先 등)도 모두 해당 필드별로 _word_indices 를 출력한다.
- null 값인 필드는 _word_indices 를 출력하지 않는다.
"""

    if similar_examples:
        example = similar_examples[0]
        example_ocr = example["ocr_text"]
        # DB 전용 필드 제거 + key_order로 원본 answer.json 순서 복원 후 프롬프트에 삽입
        example_answer = _sanitize_example_answer_for_prompt(
            example["answer_json"],
            example.get("key_order"),
        )
        example_answer_str = json.dumps(example_answer, ensure_ascii=False, indent=2)
        prompt = prompt_template.format(
            example_ocr=example_ocr,
            example_answer_str=example_answer_str,
            ocr_text=text_for_prompt
        )
    else:
        prompt = prompt_template.format(
            example_ocr="",
            example_answer_str="{}",
            ocr_text=text_for_prompt
        )
    if word_index_instruction:
        prompt = prompt.replace("ANSWER:\n", word_index_instruction.strip() + "\n\nANSWER:\n", 1)
    
    # 디버깅: 프롬프트 저장 (항상 저장)
    try:
        # debug_dir이 없으면 프로젝트 루트의 debug 폴더에 저장
        if not debug_dir:
            project_root = get_project_root()  # 이미 상단에서 import됨
            debug_dir = project_root / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            debug_dir = str(debug_dir)
        
        # page_num이 없으면 타임스탬프 사용
        if page_num:
            prompt_file = os.path.join(debug_dir, f"page_{page_num}_prompt.txt")
        else:
            timestamp = int(time.time())
            prompt_file = os.path.join(debug_dir, f"prompt_{timestamp}.txt")
        
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt)
        # print(f"  💾 프롬프트 저장 완료: {prompt_file}")
    except Exception as debug_error:
        import traceback
        print(f"⚠️ 프롬프트 저장 실패: {debug_error}")
        print(f"  상세:\n{traceback.format_exc()}")
    
    # 3. LLM API 호출 (provider에 따라 Gemini 또는 GPT 사용)
    if progress_callback:
        progress_callback(f"🤖 LLM ({model_name})에 요청 중...")
    
    try:
        llm_start_time = time.time()
        if rag_llm_provider == "gemini":
            # Gemini (gemini_extractor 모델) 사용
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            temperature_str = str(temperature) if temperature is not None else "None (모델 기본값 사용)"
            print(f"  📝 API 호출: 프롬프트 길이={len(prompt)} 문자, 모델={model_name}, temperature={temperature_str}")
            gen_config = {"max_output_tokens": 8000}
            if temperature is not None:
                gen_config["temperature"] = temperature
            response = model.generate_content(prompt, generation_config=gen_config)
            llm_end_time = time.time()
            llm_duration = llm_end_time - llm_start_time
            if not response.candidates or not response.candidates[0].content:
                raise Exception("Gemini API 응답에 content가 없습니다.")
            result_parts = []
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    result_parts.append(part.text)
            result_text = "".join(result_parts) if result_parts else ""
            usage = None
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                um = response.usage_metadata
                usage = f"prompt={getattr(um, 'prompt_token_count', 'N/A')}, completion={getattr(um, 'candidates_token_count', 'N/A')}"
            print(f"  📥 API 응답: 길이={len(result_text) if result_text else 0} 문자, 소요 시간={llm_duration:.2f}초")
            if usage:
                print(f"  📊 토큰 사용량: {usage}")
        else:
            # GPT (OpenAI) 사용
            client = OpenAI(api_key=api_key)
            temperature_str = str(temperature) if temperature is not None else "None (모델 기본값 사용)"
            print(f"  📝 API 호출: 프롬프트 길이={len(prompt)} 문자, 모델={model_name}, temperature={temperature_str}")
            api_params = {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "timeout": 120,
                "max_completion_tokens": 8000,
            }
            if temperature is not None:
                api_params["temperature"] = temperature
            try:
                response = client.chat.completions.create(**api_params)
                llm_end_time = time.time()
                llm_duration = llm_end_time - llm_start_time
                result_text = response.choices[0].message.content or ""
                usage = response.usage if hasattr(response, "usage") else None
                if usage:
                    print(f"  📊 토큰 사용량: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}, total={usage.total_tokens}")
            except Exception as api_error:
                llm_end_time = time.time()
                llm_duration = llm_end_time - llm_start_time
                print(f"  ❌ API 호출 실패 (소요 시간: {llm_duration:.2f}초): {api_error}")
                raise
            print(f"  📥 API 응답: 길이={len(result_text) if result_text else 0} 문자, 소요 시간={llm_duration:.2f}초")
        
        # 디버깅: LLM 원본 응답 저장
        if debug_dir and page_num:
            try:
                llm_response_file = os.path.join(debug_dir, f"page_{page_num}_llm_response.txt")
                with open(llm_response_file, 'w', encoding='utf-8') as f:
                    f.write(result_text)
                # print(f"  💾 디버깅: LLM 응답 저장 완료 - {llm_response_file}")
            except Exception as debug_error:
                import traceback
                print(f"⚠️ LLM 응답 저장 실패: {debug_error}")
                print(f"  상세:\n{traceback.format_exc()}")
        
        if progress_callback:
            progress_callback("LLM 응답 수신 완료, JSON 파싱 중...")
        
        if not result_text:
            raise Exception("LLM API 응답에 텍스트가 없습니다.")
        
        # JSON 추출 (마크다운 코드 블록 제거 및 정리)
        result_text = result_text.strip()
        
        # 마크다운 코드 블록 제거
        if result_text.startswith('```'):
            # 첫 번째 ``` 제거
            result_text = result_text.split('```', 1)[1]
            # json 또는 다른 언어 태그 제거
            if result_text.startswith('json'):
                result_text = result_text[4:].strip()
            elif result_text.startswith('\n'):
                result_text = result_text[1:]
            # 마지막 ``` 제거
            if result_text.endswith('```'):
                result_text = result_text.rsplit('```', 1)[0].strip()
        
        # 앞뒤 공백 및 불필요한 문자 제거
        result_text = result_text.strip()
        
        # 탭 제거 (JSON 문자열 내 탭이 파싱 오류·잘림 유발할 수 있음)
        result_text = result_text.replace("\t", " ")
        # Python의 None을 JSON의 null로 치환 (LLM이 None을 출력하는 경우 대비)
        # 단, 문자열 내의 "None"은 치환하지 않도록 주의
        import re
        # "key": None 패턴을 "key": null로 치환
        result_text = re.sub(r':\s*None\s*([,}])', r': null\1', result_text)
        # True/False도 JSON 표준에 맞게 처리
        result_text = re.sub(r':\s*True\s*([,}])', r': true\1', result_text)
        result_text = re.sub(r':\s*False\s*([,}])', r': false\1', result_text)
        
        # JSON 파싱 시도 (실패 시 잘못된 이스케이프 정규화 후 1회 재시도)
        try:
            # NaN 문자열을 null로 변환 (JSON 표준에 맞게)
            import math
            result_text = re.sub(r':\s*NaN\s*([,}])', r': null\1', result_text, flags=re.IGNORECASE)
            result_text = re.sub(r':\s*"NaN"\s*([,}])', r': null\1', result_text, flags=re.IGNORECASE)

            try:
                result_json = json.loads(result_text)
            except json.JSONDecodeError:
                result_text = _sanitize_invalid_json_escapes(result_text)
                result_json = json.loads(result_text)  # 잘못된 이스케이프 정규화 후 재시도 1회
            
            # items 내 문자열 값 정규화: 탭·全角スペース→공백, 연속 공백/줄바꿈 하나로
            def _normalize_item_string(s):
                if not isinstance(s, str):
                    return s
                s = s.replace("\t", " ").replace("\u3000", " ").replace("\n", " ")
                s = re.sub(r" +", " ", s).strip()
                return s
            
            if isinstance(result_json.get("items"), list):
                for item in result_json["items"]:
                    if isinstance(item, dict):
                        for k, v in list(item.items()):
                            if isinstance(v, str):
                                item[k] = _normalize_item_string(v)
            
            # result_json이 딕셔너리가 아닌 경우 처리 (리스트인 경우 등)
            if not isinstance(result_json, dict):
                if isinstance(result_json, list):
                    # 리스트인 경우: items 배열로 간주하고 딕셔너리로 변환
                    print(f"  ⚠️ LLM 응답이 리스트 형식입니다. 딕셔너리로 변환합니다.")
                    result_json = {
                        "items": result_json,
                        "page_role": "detail"
                    }
                else:
                    # 다른 타입인 경우 에러
                    raise Exception(f"LLM 응답이 예상치 못한 형식입니다: {type(result_json)}. 딕셔너리 또는 리스트여야 합니다.")
            
            # NaN 값 정규화 함수 (재귀적으로 딕셔너리와 리스트를 순회)
            def normalize_nan(obj):
                import math
                if isinstance(obj, dict):
                    # Python 3.7+에서는 dict가 삽입 순서를 보존하므로 items() 순서대로 재생성하면 순서 유지
                    return {k: normalize_nan(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [normalize_nan(item) for item in obj]
                elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
                    return None
                else:
                    return obj
            
            # NaN 값 정규화
            result_json = normalize_nan(result_json)
            
            # null 값 정규화: items가 null이면 빈 리스트로, page_role이 null이면 기본값으로
            if result_json.get("items") is None:
                result_json["items"] = []
                print(f"  ⚠️ items가 null이어서 빈 리스트로 변환했습니다.")
            
            if result_json.get("page_role") is None:
                result_json["page_role"] = "detail"  # 기본값
                print(f"  ⚠️ page_role이 null이어서 'detail'로 변환했습니다.")
            
            # items가 리스트가 아닌 경우 빈 리스트로 변환
            if not isinstance(result_json.get("items"), list):
                print(f"  ⚠️ items가 리스트가 아닙니다 ({type(result_json.get('items'))}). 빈 리스트로 변환합니다.")
                result_json["items"] = []
            
            # items 내부의 각 항목에서 NaN 값 정규화
            if isinstance(result_json.get("items"), list):
                for item in result_json["items"]:
                    if isinstance(item, dict):
                        for key in ['quantity', 'case_count', 'bara_count', 'units_per_case', 'amount']:
                            if key in item and isinstance(item[key], float) and (math.isnan(item[key]) or math.isinf(item[key])):
                                item[key] = None
                                print(f"  ⚠️ {key}가 NaN이어서 null로 변환했습니다.")
            # 金額 등 금액 필드: OCR 점선이 "1:500"처럼 읽힌 경우 콜론 제거 후처리 ("1500")
            if isinstance(result_json.get("items"), list):
                for item in result_json["items"]:
                    if isinstance(item, dict):
                        for key, val in list(item.items()):
                            item[key] = _normalize_amount_colon(val)

            # 키 순서 재정렬 (REFERENCE_JSON이 있는 경우)
            if similar_examples and len(similar_examples) > 0:
                example = similar_examples[0]
                key_order = example.get("key_order")
                if key_order:
                    result_json = _reorder_json_by_key_order(result_json, key_order)

            # 좌표는 OCR 탭처럼 그림 그릴 때만 사용: include_bbox이고 ocr_words 있을 때만 _bbox 부여
            if include_bbox and ocr_words:
                _attach_bbox_to_json(result_json, ocr_words)
                if page_width is not None and page_height is not None:
                    result_json["_page_bbox"] = {"width": page_width, "height": page_height}

            # RAG에서 사용한 참조 예제 메타데이터를 LLM 결과에도 포함시켜,
            # 이후 DB 저장 시 form_type 등을 결정할 때 사용할 수 있게 한다.
            if top_example_metadata:
                # 충돌을 피하기 위해 내부 메타 키 이름은 _rag_reference로 사용
                result_json["_rag_reference"] = top_example_metadata

            # 디버깅: 파싱된 JSON 저장
            if debug_dir and page_num:
                try:
                    parsed_json_file = os.path.join(debug_dir, f"page_{page_num}_llm_response_parsed.json")
                    with open(parsed_json_file, 'w', encoding='utf-8') as f:
                        json.dump(result_json, f, ensure_ascii=False, indent=2)
                    # print(f"  💾 디버깅: 파싱된 JSON 저장 완료 - {parsed_json_file}")
                except Exception as debug_error:
                    import traceback
                    print(f"⚠️ 파싱된 JSON 저장 실패: {debug_error}")
                    print(f"  상세:\n{traceback.format_exc()}")
        except json.JSONDecodeError as e:
            # 파싱 실패 시 더 자세한 정보 제공
            error_pos = e.pos if hasattr(e, 'pos') else None
            if error_pos:
                start = max(0, error_pos - 50)
                end = min(len(result_text), error_pos + 50)
                context = result_text[start:end]
                raise Exception(
                    f"JSON 파싱 실패: {e}\n"
                    f"오류 위치 근처 텍스트: ...{context}...\n"
                    f"전체 응답 텍스트:\n{result_text[:500]}..."
                )
            else:
                raise Exception(f"JSON 파싱 실패: {e}\n응답 텍스트:\n{result_text[:500]}...")
        
        return result_json
        
    except json.JSONDecodeError as e:
        raise Exception(f"JSON 파싱 실패: {e}\n응답 텍스트: {result_text}")
    except Exception as e:
        raise Exception(f"LLM API 호출 실패: {e}")

