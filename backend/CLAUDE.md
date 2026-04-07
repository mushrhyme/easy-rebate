# Backend — FastAPI + Python

## 실행

```bash
uv run rebate-server   # pyproject.toml의 scripts 항목 (backend.main:run)
```

## API 라우트 구조

| 라우트 파일 | 경로 | 주요 기능 |
|-------------|------|-----------|
| documents.py | `/api/documents` | PDF 업로드, 문서 목록/삭제, 페이지 재분석 |
| items.py | `/api/items` | 아이템 CRUD, 락 관리 (optimistic locking) |
| search.py | `/api/search` | 고객 검색 (RAG), 페이지 이미지 조회 |
| sap_upload.py | `/api/sap-upload` | SAP용 Excel 생성/내보내기 |
| rag_admin.py | `/api/rag-admin` | RAG 벡터 학습/관리 (관리자) |
| auth.py | `/api/auth` | 로그인, 비밀번호 변경 |
| attachments.py | `/api/attachments` | 파일 첨부 |
| websocket.py | `/ws` | 실시간 처리 진행률 (WebSocket) |
| form_types.py | `/api/form-types` | 양식 타입 설정 |
| settings.py | `/api/settings` | 사용자 설정 |

## 핵심 모듈 (`modules/`)

### modules/core/
- **processor.py** — PDF 처리 오케스트레이터. `PdfProcessor.process_pdf()`가 메인 진입점
- **rag_manager.py** (89K, 최대 파일) — RAG 검색·학습 전체. pgvector + BM25 하이브리드
- **build_faiss_db.py** — FAISS 인덱스 빌더
- **build_pgvector_db.py** — pgvector 임베딩 빌더
- **storage.py** — 파일 저장 유틸

### modules/core/extractors/
- **rag_pages_extractor.py** — 메인 추출: PDF→이미지→OCR→RAG→LLM
- **gemini_extractor.py** / **azure_extractor.py** / **upstage_extractor.py** — OCR 제공자별 래퍼
- **pdf_processor.py** — PDF→이미지 변환

### modules/utils/
- **openai_chat_completion.py** — OpenAI API 래퍼
- **llm_retry.py** — LLM 호출 재시도 로직
- **form2_rebate_utils.py**, **form04_mishu_utils.py** — 양식별 후처리
- **retail_resolve.py**, **retail_user_utils.py** — 고객 마스터 매칭
- **text_normalizer.py** — 텍스트 정규화
- **fill_empty_values_utils.py** — 빈값 자동 채움

## 데이터베이스 구조

### 핵심 테이블 (모두 `_current` / `_archive` 쌍)
- **documents** — PDF 메타데이터 (filename, form_type, total_pages, upload_channel)
- **page_data** — 페이지별 데이터 (page_role, page_meta JSONB, ocr_text, is_rag_candidate)
- **items** — 행 단위 데이터 (item_data JSONB, review_status, version)
- **item_locks** — 편집 락 (locked_by_user_id, expires_at)
- **page_images** — 페이지 이미지 경로

### RAG/벡터 테이블
- **rag_page_embeddings** — pgvector 임베딩 (embedding vector(384), form_type, answer_json)

### 기타 테이블
- **users** — 사용자 (username, role, is_admin)
- **user_sessions** — 세션 관리
- **form_field_mappings** — 논리→물리 필드명 매핑
- **form_type_labels** — 양식코드 표시명

### DB 매니저 파일 (`database/`)
- **db_manager.py** — 메인 DB 인터페이스 (문서, 페이지)
- **db_items.py** — 아이템 CRUD (가장 큰 DB 모듈)
- **db_locks.py** — optimistic locking
- **db_users.py** — 사용자 관리
- **registry.py** — DB 커넥션 풀
- **table_selector.py** — current/archive 테이블 선택
- **archive_migration.py** — 월별 아카이브 마이그레이션 (APScheduler, 매월 1일)

### CSV 데이터 (`database/csv/`)
- **retail_user.csv** — 고객 마스터
- **dist_retail.csv** — 유통 정보
- **unit_price.csv** — 단가 정보

## 설정 (`backend/core/`)

- **config.py** — Pydantic Settings (환경변수 로드, CORS, 업로드 설정)
- **auth.py** — 인증 유틸
- **session.py** — 세션 관리
- **scheduler.py** — APScheduler (아카이브 마이그레이션 스케줄)
