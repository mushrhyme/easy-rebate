# React Rebate - 조건청구서 업로드·처리 시스템

조건청구서 PDF를 업로드해서 **자동 파싱 → 검토/수정 → SAP 업로드용 엑셀 생성**까지 처리하는 풀스택 시스템입니다.  
현재 코드 기준으로 **아키텍처, form_type, RAG 구조**를 반영해 정리한 최종 README입니다.

---

## 1. 시스템 개요

- **프론트엔드**: `frontend/`  
  - React + Vite 기반 SPA  
  - 조건청구서 목록 조회, 페이지별 그리드 편집, RAG 예제/추천 확인, SAP 엑셀 다운로드 UI 제공
- **백엔드**: `backend/`  
  - FastAPI (`backend/main.py`)  
  - PDF 업로드/처리, RAG 검색, DB 연동, SAP 엑셀 생성, WebSocket 진행률 알림 담당
- **핵심 모듈**: `modules/`  
  - `modules/core/processor.py`, `modules/core/extractors/pdf_processor.py`: PDF → 이미지/텍스트 변환, 회전 보정  
  - `modules/core/rag_manager.py`: FAISS 기반 글로벌 RAG 인덱스 관리  
  - `modules/core/extractors/`: OCR/RAG/LLM 조합으로 페이지별 JSON 추출 (Upstage, Gemini 등)  
  - `modules/utils/`: 설정, 세션, 텍스트 정규화, 이미지 회전 유틸
- **DB 레이어**: `database/`  
  - PostgreSQL 스키마는 `database/SCHEMA.md`, `database/init_database.sql` 참고  
  - 현재월/아카이브 분리(`*_current`, `*_archive`), RAG 인덱스(`rag_vector_index`) 등

**한 줄 요약**:  
PDF 업로드 → 글로벌 RAG + LLM으로 구조화 JSON → 양식별 후처리·key_order 정렬 → DB 저장·그리드 편집 → master_code 추천/RAG로 코드 매핑 → SAP 업로드용 엑셀 생성.

---

## 2. 실행 방법 (개발 환경)

### 2.1 공통

- Python 3.10+  
- Node.js (Vite 기준 18+ 권장)  
- PostgreSQL (스키마는 `database/init_database.sql` 사용)

#### Python 의존성 설치

```bash
pip install -r requirements.txt
```

#### DB 초기화

```bash
psql -U postgres -d rebate_db -f database/init_database.sql
```

### 2.2 백엔드(FastAPI)

```bash
# 프로젝트 루트에서
python -m uvicorn backend.main:app --reload
```

- 기본 설정은 `backend/core/config.py` 의 `settings`를 따릅니다.  
- `/health` 로 헬스 체크, `/api/*` 및 `/ws/*` 라우트는 `backend/api/` 하위 라우터 참고.

### 2.3 프론트엔드(React + Vite)

```bash
cd frontend
npm install
npm run dev
```

- 개발 시 CORS는 `backend/main.py` 에서 로컬 네트워크/포트 패턴을 허용하도록 설정되어 있습니다.  
- `.env` 또는 Vite 설정에서 API 호스트(`VITE_API_BASE_URL` 등)가 백엔드 주소를 가리키도록 맞춰줍니다.

---

## 3. PDF → DB 저장까지의 처리 흐름

### 3.1 업로드 & 세션 관리

- 사용자는 연월을 선택한 뒤, 파일 업로더로 **1개 이상 PDF**를 업로드합니다.
- 백엔드는:
  - 파일 크기/양식지 유효성 검사
  - 이미 등록된 문서(`documents_current`/`documents_archive`)인지 중복 체크
  - 전부 신규일 때만 **세션 ID/작업 ID**를 발급하고, 임시 PDF 파일로 저장
- 프론트는 **WebSocket(`/ws/processing/{task_id}`)** 으로 진행률 이벤트를 구독합니다.

### 3.2 PDF → 이미지/텍스트

- `PdfProcessor` 가 백그라운드에서 각 PDF를 처리합니다.
- 공통 처리:
  - 페이지 단위 이미지 생성 (기본 300 DPI)
  - 이미지 회전 보정(`image_rotation_utils`)으로 기울어진 스캔 교정
- 텍스트 추출 방식은:
  - `upload_channel` (finet | mail)에 따라 텍스트 추출 방법을 결정합니다 (finet→excel, mail→upstage),
  - 없을 경우 설정 파일(`config`) fallback 을 사용합니다.

### 3.3 OCR/RAG/LLM에 의한 페이지별 JSON 추출

- **이미 DB에 파싱 결과가 있는 페이지**는 그대로 재사용 (`items_current`, `page_data_current` 등).  
- 새로 파싱해야 하는 페이지에 대해서만:
  - OCR 결과(또는 PyMuPDF 텍스트)를 전각/반각 정규화 후 RAG 입력으로 사용
  - `modules/core/rag_manager.RAGManager` 가 관리하는 **글로벌 FAISS 인덱스**에서 유사 예제 검색
  - 검색된 예제의 `answer_json`·`key_order`·메타데이터를 LLM 프롬프트에 포함
  - 현재 페이지 텍스트를 입력해 **`{ items: [...], page_role, ... }` 형태의 JSON**을 생성
- 여러 페이지는 비동기/병렬로 처리되며, 필요 시 Upstage OCR을 사용해 bbox 기반 좌표 정보를 함께 취득합니다.

### 3.4 key_order 기반 정렬 및 후처리

- `rag_manager._extract_key_order(answer_json)` 이 **page_keys / item_keys** 를 계산해 메타데이터에 저장합니다.
- 이후:
  - RAG 예시 기준 key 순서를 유지하도록 `_reorder_json_by_key_order` 로 LLM 결과 JSON을 정렬
  - `database/db_items.py`, `database/db_manager.py` 에서도 `get_key_order_by_form_type` 으로 불러온 `item_keys` 로 재정렬
- 양식별 후처리:
  - 빈 거래처명/코드/관리번호/摘要 등은 동일 페이지/이전 페이지/다음 페이지 값을 참조하여 채움
  - 양식 02 전용 규칙(예: 리ベート計算条件이 「納価条件」인 행은 특정 수량 필드를 0으로 세팅 등)을 적용

### 3.5 DB 저장 구조

주요 테이블은 `database/SCHEMA.md` 에 상세히 정리되어 있습니다. 핵심만 요약하면:

- `documents_current` / `documents_archive`
  - PDF 파일 단위 메타데이터 (파일명, form_type, 연월 등)
- `page_data_current` / `page_data_archive`
  - 페이지 역할(`page_role`), 페이지별 메타(JSONB)
- `items_current` / `items_archive`
  - 행 단위 데이터 (`item_data` JSONB + 공통 컬럼 + 검토 상태 + 버전)
- `page_images_current` / `page_images_archive`
  - 페이지 이미지 경로/데이터
- `rag_learning_status_*`
  - 각 페이지의 RAG 학습 상태 및 shard 정보
- `rag_vector_index`
  - **글로벌 인덱스 1개(`index_name='base', form_type NULL/''**) + shard_*  
  - `metadata_json` 안에 `metadata[doc_id] = { ocr_text, answer_json, metadata(form_type 등), key_order }`

아카이브 마이그레이션(`database/archive_migration.py`)은 `*_current` → `*_archive` 이동만 처리하며,  
`rag_vector_index` 의 메타데이터(key_order 포함)는 별도로 유지/관리됩니다.

---

## 4. form_type 및 양식 마스터 구조

- **form_type** 은:
  - 각 조건청구서 양식을 구분하는 코드(예: `"01"`, `"02"`, `"03"`, `"04"`, `"05"` 등)로,
  - `documents_*`, `rag_learning_status_*`, 예제 메타데이터 내에서 공통적으로 사용됩니다.
- 벡터 인덱스는 **단일 글로벌 인덱스**를 사용합니다.
  - `rag_vector_index.index_name = 'base'`, `form_type IS NULL OR form_type = ''`  
  - 실제 예제별 양식 구분은 `metadata[doc_id]['metadata']['form_type']` 로 관리합니다.
- 새로운 양식 추가 시:
  - img 폴더 구조는 `upload_channel` (finet 또는 mail) 또는 form_type (01-06)으로 구성할 수 있으며, 자동으로 `upload_channel`로 매핑됩니다.
  - 학습용 예제(`img/` 하위 answer_json 등)를 준비한 뒤,
  - `python build_faiss_db.py [form_folder]` 로 인덱스를 재빌드합니다 (실제 로직은 `modules/core/build_faiss_db.py`).

형식→참조 RAG, master_code 추천/RAG, B열/D열 매핑 자동화에 대한 자세한 설계는 `sap_upload.md` 를 참고하세요.

---

## 5. 조회·편집·검색·SAP 엑셀 생성

### 5.1 문서/행 조회·편집

- 프론트는 `documents` API로 문서 목록을, `items` API로 페이지별/문서별 행 데이터를 조회합니다.
- 그리드에서 행 단위 수정 시:
  - 해당 `item_id` 에 **락(item_locks_current)** 을 걸어 동시 편집 충돌을 방지
  - 저장 시 `items_current` 의 `item_data` 및 공통 컬럼, 버전이 갱신

### 5.2 검색

- 거래처명, 상품명 등으로 `items_*` 를 검색할 수 있으며,
- 필요 시 대응 페이지 이미지는 `page_images_*` 에서 경로/데이터를 조회해 화면에 표시합니다.

### 5.3 SAP 업로드용 엑셀 생성

- 검토·수정이 끝난 행 단위 데이터(`items_current`)를 양식별 매핑 규칙에 따라 **SAP 업로드 포맷**으로 변환합니다.
- 템플릿 파일은 `static/sap_upload.xlsx` 를 사용하며:
  - B열(판매처), C/D/I/J/K(거래처·코드), L(상품명), P/T/Z/AD/AL 등 입력 컬럼은 값으로 채우고,
  - U열 등 계산 컬럼은 엑셀 수식을 활용합니다.
- `sap_upload.md` 에 각 컬럼 매핑·후처리 규칙이 상세히 정리되어 있습니다.  
  프론트에서 생성 API를 호출하면, 다운로드 가능한 엑셀 파일로 반환됩니다.

---

## 6. 참고 문서

- `database/SCHEMA.md`  
  - 전체 DB 스키마 설명
- `PERFORMANCE_DIAGNOSIS.md`  
  - 성능 진단 및 최적화 관련 메모

이 README는 **현재 코드 기준**으로 정리되어 있습니다.  
새로운 양식 추가나 RAG 인덱스 구조 변경 시 이 파일을 함께 업데이트하는 것을 권장합니다.

