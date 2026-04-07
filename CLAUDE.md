# React Rebate — 조건청구서 업로드·처리 시스템

## 프로젝트 개요

PDF 조건청구서를 업로드하면 OCR → RAG → LLM 파이프라인으로 자동 분석하고,
사용자가 검토·수정 후 SAP용 Excel로 내보내는 풀스택 시스템.

## 기술 스택

- **Backend**: FastAPI + Python 3.10+ (uv 패키지 매니저)
- **Frontend**: React 19 + TypeScript + Vite
- **Database**: PostgreSQL 12+ (pgvector, pg_trgm 확장)
- **AI/ML**: OpenAI GPT-4, Google Gemini, Anthropic Claude, sentence-transformers
- **OCR**: Tesseract, Azure Vision, Upstage, Gemini
- **상태관리**: Zustand (클라이언트), React Query (서버), Context (인증/토스트)

## 개발 서버 실행

```bash
./dev.sh          # 백엔드(8000) + 프론트엔드(3002) 동시 실행
# 또는 개별 실행:
uv run rebate-server        # 백엔드 단독 (DEBUG=true면 auto-reload)
cd frontend && npm run dev  # 프론트엔드 단독
```

## 디렉토리 구조

```
react_rebate/
├── backend/          # FastAPI 앱 (main.py, api/routes/, core/)
├── frontend/         # React 앱 (src/components/, hooks/, api/)
├── database/         # DB 스키마, 매니저 (db_manager.py, db_items.py 등)
├── modules/          # PDF 처리 핵심 로직
│   ├── core/         #   processor.py, rag_manager.py, extractors/
│   └── utils/        #   유틸리티 (OCR, LLM, 텍스트 처리)
├── prompts/          # LLM 프롬프트 템플릿 (v1~v9)
├── config/           # rag_provider.json 등
├── scripts/          # 유틸리티 스크립트
└── docs/             # 문서
```

## PDF 처리 파이프라인

```
Upload → PDF→Images(PyMuPDF) → OCR(Tesseract/Gemini/Azure/Upstage)
       → RAG검색(pgvector+BM25) → LLM분석(GPT-4+프롬프트)
       → DB저장(items) → WebSocket으로 실시간 진행률 전송
```

## 핵심 개념

- **form_type**: 양식코드 (01~05), 양식마다 필드·프롬프트가 다름
- **upload_channel**: `finet`(Excel) / `mail`(OCR via Upstage)
- **current/archive 패턴**: 모든 핵심 테이블이 `_current`/`_archive`로 분리, 매월 1일 자동 마이그레이션
- **optimistic locking**: items 테이블의 `version` 필드로 동시 편집 충돌 방지
- **RAG**: pgvector(primary) + FAISS(fallback), hybrid search(BM25+semantic)

## 환경변수 (.env)

```
GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
AZURE_API_KEY, AZURE_API_ENDPOINT, UPSTAGE_API_KEY
DB_NAME=rebate_db, DB_HOST, DB_PORT, DB_USER, DB_PASSWORD
API_HOST=0.0.0.0, API_PORT=8000, DEBUG=true
```

## 프론트엔드 프록시 (vite.config.ts)

- `/api` → `http://127.0.0.1:8000`
- `/ws` → `ws://127.0.0.1:8000`
- `/static` → `http://127.0.0.1:8000`
