#!/usr/bin/env python3
"""
텍스트 파일을 여러 GPT / Gemini 모델로 처리하고 결과를 비교하는 스크립트

사용법:
    python compare_models.py <텍스트_파일_경로>
    
예시:
    python compare_models.py debug2/日本アクセス和歌山支店/page_2_prompt.txt

필요 환경변수:
    - OPENAI_API_KEY: OpenAI API 키
    - GEMINI_API_KEY: Google Gemini API 키
    - ANTHROPIC_API_KEY: Anthropic Claude API 키

결과물:
    - model_comparison_results/ 폴더에 각 모델별 결과 파일 저장

텍스트 길이: 10,185 문자
입력 토큰 (GPT 기준): 8,162 토큰
✅ 17,35s → gpt_gpt-4o-2024-11-20
✅ 45.11s → gpt_gpt-5.2-2025-12-11
✅ 23.04s → claude_claude-haiku-4-5
✅ 66.83s → gemini_gemini-3-flash-preview
✅ 64.66s → gemini_gemini-2.5-pro
✅ 28.32s → gemini_gemini-2.5-flash
✅ 28.55s → gemini_gemini-2.0-flash
✅ 14.22s → gemini_gemini-2.5-flash-lites
✅ 7.92s → gemini_gemini-2.5-flash-lite-preview-09-2025
✅ 26.08s → gemini_gemini-2.0-flash-lite
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

# 프로젝트 루트 설정
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# GPT 모델 목록
GPT_MODELS = [
    "gpt-4o-2024-11-20",
    # "gpt-5-mini-2025-08-07",
    # "gpt-5-nano-2025-08-07",
    "gpt-5.2-2025-12-11"

]

# Gemini 모델 목록 (필요시 스크립트 상단에서 수정 가능)
GEMINI_MODELS = [
    # "gemini-3-flash-preview",
    # "gemini-2.5-pro",
    # "gemini-2.5-flash",
    # "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash-lite-preview-09-2025",
    # "gemini-2.0-flash-lite",
]

# Claude 모델 목록 (Haiku 등)
CLAUDE_MODELS = [
    "claude-haiku-4-5"
]


def call_gpt(model_name: str, text: str, api_key: str) -> tuple[str, float, str | None]:
    """GPT 모델로 텍스트 처리"""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        start = time.time()
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": text}],
            timeout=60,
            max_completion_tokens=16000,
        )
        elapsed = time.time() - start
        result = response.choices[0].message.content or ""
        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = f"prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}"
        return result, elapsed, usage
    except Exception as e:
        return f"[ERROR] {str(e)}", 0.0, None


def call_gemini(model_name: str, text: str, api_key: str) -> tuple[str, float, str | None]:
    """Gemini 모델로 텍스트 처리"""
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        start = time.time()
        response = model.generate_content(text)
        elapsed = time.time() - start

        if not response.candidates or not response.candidates[0].content:
            return "[ERROR] Gemini 응답에 content가 없습니다.", elapsed, None

        result_parts = []
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                result_parts.append(part.text)
        result = "".join(result_parts) if result_parts else "[ERROR] 빈 응답"

        usage = None
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            usage = f"prompt={getattr(um, 'prompt_token_count', 'N/A')}, completion={getattr(um, 'candidates_token_count', 'N/A')}"

        return result, elapsed, usage
    except Exception as e:
        return f"[ERROR] {str(e)}", 0.0, None


def call_claude(model_name: str, text: str, api_key: str) -> tuple[str, float, str | None]:
    """Claude 모델로 텍스트 처리"""
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        start = time.time()
        response = client.messages.create(
            model=model_name,
            max_tokens=16000,
            messages=[{"role": "user", "content": text}],
        )
        elapsed = time.time() - start

        result_parts = []
        for block in response.content:
            if hasattr(block, "text") and block.text:
                result_parts.append(block.text)
        result = "".join(result_parts) if result_parts else "[ERROR] 빈 응답"

        usage = None
        if hasattr(response, "usage") and response.usage:
            u = response.usage
            usage = f"prompt={getattr(u, 'input_tokens', 'N/A')}, completion={getattr(u, 'output_tokens', 'N/A')}"

        return result, elapsed, usage
    except Exception as e:
        return f"[ERROR] {str(e)}", 0.0, None


def count_input_tokens(text: str) -> int | None:
    """GPT(cl100k_base) 기준 입력 토큰 수. tiktoken 미설치 시 None."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return None


def sanitize_filename(name: str) -> str:
    """파일명으로 사용 가능한 문자열로 변환"""
    return "".join(c if c.isalnum() or c in ".-_" else "_" for c in name)


def parse_json_from_response(result: str) -> dict | None:
    """
    LLM 응답 텍스트에서 JSON을 추출하여 파싱
    마크다운 코드 블록(```json ... ```), Python None/True/False 등을 처리
    """
    if not result or result.startswith("[ERROR]"):
        return None

    text = result.strip()

    # 마크다운 코드 블록 제거
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
        else:
            # ``` 로 시작하는 경우
            text = text.split("```", 1)[-1]
            if text.lower().startswith("json"):
                text = text[4:].strip()
            if "```" in text:
                text = text.rsplit("```", 1)[0].strip()

    # JSON 객체 또는 배열 추출
    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        text = obj_match.group(0)

    # Python 문법을 JSON 표준으로 치환
    text = re.sub(r":\s*None\s*([,}])", r": null\1", text)
    text = re.sub(r":\s*True\s*([,}])", r": true\1", text)
    text = re.sub(r":\s*False\s*([,}])", r": false\1", text)
    text = re.sub(r":\s*NaN\s*([,}])", r": null\1", text, flags=re.IGNORECASE)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return {"items": parsed, "page_role": "detail"}
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def run_comparison(text_path: str) -> None:
    """메인 실행 함수"""
    path = Path(text_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / text_path

    if not path.exists():
        print(f"❌ 파일을 찾을 수 없습니다: {path}")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    print(f"📄 입력 파일: {path}")
    print(f"   텍스트 길이: {len(text):,} 문자")
    n_tokens = count_input_tokens(text)
    if n_tokens is not None:
        print(f"   입력 토큰 (GPT 기준): {n_tokens:,} 토큰")
    else:
        print(f"   입력 토큰: (tiktoken 미설치로 생략, pip install tiktoken)")
    print()

    output_dir = PROJECT_ROOT / "model_comparison_results"
    output_dir.mkdir(exist_ok=True)

    base_name = sanitize_filename(path.stem)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / f"{base_name}_{timestamp}"
    run_dir.mkdir(exist_ok=True)

    # 입력 텍스트 복사 (참고용)
    input_copy = run_dir / "input_text.txt"
    with open(input_copy, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"📁 결과 저장 경로: {run_dir}\n")

    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    if not openai_key:
        print("⚠️ OPENAI_API_KEY가 설정되지 않았습니다. GPT 모델은 건너뜁니다.")
    if not gemini_key:
        print("⚠️ GEMINI_API_KEY가 설정되지 않았습니다. Gemini 모델은 건너뜁니다.")
    if not anthropic_key:
        print("⚠️ ANTHROPIC_API_KEY가 설정되지 않았습니다. Claude 모델은 건너뜁니다.")

    all_results = []

    # GPT 모델 실행
    for model in GPT_MODELS:
        if not openai_key:
            continue
        print(f"🔄 GPT {model} 실행 중...", end=" ", flush=True)
        result, elapsed, usage = call_gpt(model, text, openai_key)
        safe_name = sanitize_filename(model)
        out_file = run_dir / f"gpt_{safe_name}.txt"
        header = f"# Model: {model}\n# Elapsed: {elapsed:.2f}s\n"
        if usage:
            header += f"# Usage: {usage}\n"
        header += "# ---\n\n"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(header + result)
        status = "✅" if not result.startswith("[ERROR]") else "❌"
        parsed = parse_json_from_response(result)
        if parsed is not None:
            json_file = run_dir / f"gpt_{safe_name}.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=2)
            print(f"{status} {elapsed:.2f}s → {out_file.name}, {json_file.name}")
        else:
            print(f"{status} {elapsed:.2f}s → {out_file.name}")
        all_results.append(("GPT", model, elapsed, result.startswith("[ERROR]")))

    # Claude 모델 실행
    for model in CLAUDE_MODELS:
        if not anthropic_key:
            continue
        print(f"🔄 Claude {model} 실행 중...", end=" ", flush=True)
        result, elapsed, usage = call_claude(model, text, anthropic_key)
        safe_name = sanitize_filename(model)
        out_file = run_dir / f"claude_{safe_name}.txt"
        header = f"# Model: {model}\n# Elapsed: {elapsed:.2f}s\n"
        if usage:
            header += f"# Usage: {usage}\n"
        header += "# ---\n\n"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(header + result)
        status = "✅" if not result.startswith("[ERROR]") else "❌"
        parsed = parse_json_from_response(result)
        if parsed is not None:
            json_file = run_dir / f"claude_{safe_name}.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=2)
            print(f"{status} {elapsed:.2f}s → {out_file.name}, {json_file.name}")
        else:
            print(f"{status} {elapsed:.2f}s → {out_file.name}")
        all_results.append(("Claude", model, elapsed, result.startswith("[ERROR]")))

    # Gemini 모델 실행
    for model in GEMINI_MODELS:
        if not gemini_key:
            continue
        print(f"🔄 Gemini {model} 실행 중...", end=" ", flush=True)
        result, elapsed, usage = call_gemini(model, text, gemini_key)
        safe_name = sanitize_filename(model)
        out_file = run_dir / f"gemini_{safe_name}.txt"
        header = f"# Model: {model}\n# Elapsed: {elapsed:.2f}s\n"
        if usage:
            header += f"# Usage: {usage}\n"
        header += "# ---\n\n"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(header + result)
        status = "✅" if not result.startswith("[ERROR]") else "❌"
        parsed = parse_json_from_response(result)
        if parsed is not None:
            json_file = run_dir / f"gemini_{safe_name}.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=2)
            print(f"{status} {elapsed:.2f}s → {out_file.name}, {json_file.name}")
        else:
            print(f"{status} {elapsed:.2f}s → {out_file.name}")
        all_results.append(("Gemini", model, elapsed, result.startswith("[ERROR]")))

    # 요약
    print("\n" + "=" * 50)
    print("📊 요약")
    print("=" * 50)
    for provider, model, elapsed, failed in all_results:
        status = "실패" if failed else f"{elapsed:.2f}s"
        print(f"  {provider} {model}: {status}")
    print(f"\n결과 폴더: {run_dir}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n사용법: python compare_models.py <텍스트_파일_경로>")
        print("\n예시:")
        print('  python compare_models.py "debug2/日本アクセス和歌山支店/page_2_prompt.txt"')
        sys.exit(1)

    text_path = sys.argv[1]
    run_comparison(text_path)


if __name__ == "__main__":
    main()
