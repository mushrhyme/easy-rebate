# Azure OCR / OpenAI 병렬 처리 정리

## 동시 호출 가능 여부 (맞음)

- **Azure Document Intelligence**: 동시 호출 가능. 기본 약 15 TPS, 초과 시 큐잉. 업스테이지처럼 “한 번에 하나만” 제한이 아님.
- **OpenAI API**: 동시 호출 가능. RPM/TPM 제한만 있음. burst 시 429 대응을 위해 백오프 권장.

즉, **업스테이지와 달리 Azure·OpenAI 모두 동시에 여러 번 호출해도 되는 것이 맞습니다.**

---

## 현재 구현

| 단계 | 서비스 | 방식 | 설정 |
|------|--------|------|------|
| 1단계 | Azure OCR (mail) / PyMuPDF (finet) | **순차** | `max_parallel_workers = 1` (config), `ocr_request_delay`는 읽기만 하고 미사용 |
| 2단계 | RAG + LLM (OpenAI 또는 Gemini) | **병렬** | `ThreadPoolExecutor`, `rag_llm_parallel_workers = 5` |

- 1단계: `rag_pages_extractor.py`에서 `for idx, image in enumerate(images):` 루프로 페이지마다 한 번씩 호출.
- 2단계: `valid_ocr_indices`에 대해 `ThreadPoolExecutor(max_workers=rag_llm_workers)`로 동시에 여러 페이지 RAG+LLM 호출.

---

## 병렬화 방법

### 이미 병렬인 것: OpenAI (RAG+LLM)

- `modules/core/extractors/rag_pages_extractor.py` 2단계에서 `ThreadPoolExecutor` + `rag_llm_parallel_workers`(기본 5)로 페이지 단위 병렬 처리.
- 조정: `modules/utils/config.py`의 `rag_llm_parallel_workers` (기본 5). 필요 시 3~10 등으로 변경.

### Azure OCR (1단계) — 병렬화 적용됨

- `max_parallel_workers > 1` 이고 페이지가 2장 이상일 때, 1단계 Azure OCR을 `ThreadPoolExecutor`로 병렬 호출.
- 설정: `modules/utils/config.py`에서 `max_parallel_workers = 3` 또는 `5` 등으로 올리면 됨. 기본값 1이면 기존처럼 순차.
- `ocr_request_delay`는 현재 미사용(Upstage용 예비).

요약: **Azure·OpenAI 모두 동시 호출 가능**하고, **OpenAI(RAG+LLM)는 이미 병렬**, **Azure OCR도 `max_parallel_workers`로 병렬** 처리됩니다.
